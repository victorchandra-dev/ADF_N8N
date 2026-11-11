"""Durable WhatsApp action queue. Uses only Python's standard library."""
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LIST_ID = os.getenv('CLICKUP_LIST_ID', '1100310000198006')
ADF_LIST_ID = os.getenv('CLICKUP_ADF_LIST_ID', '1100380000193567')
# While paused, everything meant for Ama Da Flow goes to LIST_ID instead (e.g. no ClickUp access yet).
ADF_PAUSED = os.getenv('CLICKUP_ADF_PAUSED') == 'true'
# Groups whose requests never go to Ama Da Flow, even with #adf. People get "noAdf": true in people.json.
NO_ADF_GROUPS = set(filter(None, os.getenv('CLICKUP_NO_ADF_GROUPS', '').split(',')))
ACTIONS = {'create_task', 'save_idea', 'post_progress'}
RETENTION = 30 * 86400


def words(value):
    return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', str(value)).lower(), re.UNICODE)


def status_intent(update):
    text = ' '.join(words(update))
    if re.search(r"\b(not|no|don t|hasn t|haven t|almost|nearly|yet|soon|will|tomorrow|plan|planning|next|belum|hampir|akan|besok|nanti)\b|going to", text):
        return None
    if re.fullmatch(r'(?:(?:it|task|this task|is|now|sudah|telah)\s+)*(?:done|complete|completed|finished|selesai|beres)', text):
        return 'complete'
    if re.fullmatch(r'(?:(?:it|task|this task|is|now)\s+)*(?:in progress|on progress|started)|sedang dikerjakan', text):
        return 'in progress'
    return None


class APIError(Exception):
    def __init__(self, code, retryable=False, ambiguous=False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        self.ambiguous = ambiguous


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY, person TEXT NOT NULL, chat TEXT NOT NULL,
                    reference TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    state TEXT NOT NULL, stage TEXT NOT NULL DEFAULT 'start',
                    created REAL NOT NULL, updated REAL NOT NULL, next_run REAL NOT NULL,
                    expires REAL, attempts INTEGER NOT NULL DEFAULT 0,
                    token TEXT, last_error TEXT, uncertain_checks INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS action_due ON actions(state,next_run);
                CREATE TABLE IF NOT EXISTS outbox (
                    id TEXT PRIMARY KEY, action_id TEXT NOT NULL, chat TEXT NOT NULL,
                    text TEXT NOT NULL, created REAL NOT NULL, next_run REAL NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, sent REAL,
                    started REAL, last_error TEXT
                );
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def row(row):
        if row is None:
            return None
        value = dict(row)
        value['payload'] = json.loads(value['payload'])
        return value

    def submit(self, person, chat, reference, payload):
        action_id = hashlib.sha256((person + '\0' + reference).encode()).hexdigest()[:32]
        now = time.time()
        state = 'extracting' if payload['action'] == 'voice' else 'ready'
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO actions (id,person,chat,reference,kind,payload,state,created,updated,next_run) VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (action_id, person, chat, reference, payload['action'], json.dumps(payload), state, now, now, now))
            return self.row(db.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone())

    def get(self, action_id):
        with self.db() as db:
            return self.row(db.execute('SELECT * FROM actions WHERE id=?', (action_id,)).fetchone())

    def patch(self, action_id, *, notice=None, **fields):
        allowed = {'chat', 'kind', 'payload', 'state', 'stage', 'next_run', 'expires', 'attempts', 'token', 'last_error', 'uncertain_checks'}
        if not fields.keys() <= allowed:
            raise ValueError('Unsupported action field')
        if 'payload' in fields:
            fields['payload'] = json.dumps(fields['payload'])
        fields['updated'] = time.time()
        with self.db() as db:
            db.execute('UPDATE actions SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', [*fields.values(), action_id])
            if notice is not None:
                self.enqueue(db, *notice)

    def claim(self):
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM actions WHERE state IN ('ready','extracting','running') AND next_run<=? ORDER BY next_run,created LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE actions SET state='running',next_run=?,updated=? WHERE id=?", (now + 600, now, row['id']))
            return self.row(row)

    @staticmethod
    def enqueue(db, action, purpose, text):
        now = time.time()
        db.execute('INSERT OR IGNORE INTO outbox (id,action_id,chat,text,created,next_run) VALUES (?,?,?,?,?,?)',
                   (action['id'] + ':' + purpose, action['id'], action['chat'], text, now, now))

    def notify(self, action, purpose, text):
        with self.db() as db:
            self.enqueue(db, action, purpose, text)

    def cleanup(self):
        now = time.time()
        with self.db() as db:
            db.execute("DELETE FROM outbox WHERE action_id IN (SELECT id FROM actions WHERE state='pending' AND expires<=?)", (now,))
            db.execute("UPDATE actions SET state='expired',payload='{}',token=NULL WHERE state='pending' AND expires<=?", (now,))
            db.execute("UPDATE actions SET payload='{}',chat='',person='',reference='',token=NULL,last_error=NULL WHERE state IN ('done','cancelled','expired') AND updated<?", (now - RETENTION,))
            db.execute("DELETE FROM outbox WHERE action_id IN (SELECT id FROM actions WHERE state='attention' AND updated<?) OR created<?", (now - RETENTION, now - RETENTION))
            db.execute("UPDATE actions SET state='expired',payload='{}',chat='',person='',reference='',token=NULL,last_error=NULL WHERE state='attention' AND updated<?", (now - RETENTION,))



class API:
    def __init__(self):
        self.waha_key = os.environ['WAHA_API_KEY']
        self.n8n = os.getenv('N8N_URL', 'http://n8n:5678')

    def request(self, method, url, data=None, headers=None):
        raw = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(url, data=raw, method=method, headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *_):
                    return None
            with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
                body = response.read(8 * 1024 * 1024)
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            # Do not persist provider response bodies, which can contain user content.
            starting = error.code == 404 and url.startswith(self.n8n + '/webhook/')
            raise APIError('http_' + str(error.code), retryable=starting or error.code == 429 or error.code >= 500,
                           ambiguous=method != 'GET' and error.code >= 500) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise APIError('provider_unavailable', retryable=True, ambiguous=method != 'GET') from None

    def tool(self, service, method, path, data=None, list_id=None):
        # Ama Da Flow lists go to that workflow's gateway; other lists and WhatsApp replies go to Dotcross.
        hook = 'waha-action-tool' if list_id == ADF_LIST_ID else 'waha-action-tool-dotcross'
        result = self.request('POST', self.n8n + '/webhook/' + hook, {'service':service,'method':method,'path':path,'data':data,'list':list_id}, {'X-Api-Key':self.waha_key})
        status = result.get('statusCode', 502)
        if not isinstance(status, int) or not 200 <= status < 300:
            raise APIError('http_' + str(status), retryable=status == 429 or status >= 500, ambiguous=method != 'GET' and status >= 500)
        return result.get('body') or {}

    def cu(self, list_id, method, path, data=None):
        return self.tool('clickup', method, path, data, list_id)

    def tasks(self, list_id):
        tasks = []
        for page in range(1000):
            response = self.cu(list_id, 'GET', f'/list/{list_id}/task?include_closed=true&page={page}')
            batch = response.get('tasks', [])
            tasks.extend(batch)
            if response.get('last_page') is True or not batch:
                return tasks
        raise APIError('task_scan_limit')

    def get_task(self, list_id, task_id):
        if not re.fullmatch(r'[A-Za-z0-9]{5,20}', task_id):
            raise APIError('invalid_task_id')
        return self.cu(list_id, 'GET', '/task/' + task_id)

    def members(self, list_id):
        return self.cu(list_id, 'GET', f'/list/{list_id}/member').get('members', [])

    def create(self, list_id, payload):
        return self.cu(list_id, 'POST', f'/list/{list_id}/task', payload)

    def get_comments(self, list_id, task_id):
        comments, query = [], ''
        for _ in range(1000):
            batch = self.cu(list_id, 'GET', '/task/' + task_id + '/comment' + query).get('comments', [])
            comments.extend(batch)
            if len(batch) < 25:
                return comments
            last = batch[-1]
            next_query = '?' + urllib.parse.urlencode({'start': last['date'], 'start_id': last['id']})
            if next_query == query:
                raise APIError('comment_pagination_stalled')
            query = next_query
        raise APIError('comment_scan_limit')

    def comment(self, list_id, task_id, text):
        return self.cu(list_id, 'POST', '/task/' + task_id + '/comment', {'comment_text': text})

    def status(self, list_id, task_id, status):
        return self.cu(list_id, 'PUT', '/task/' + task_id, {'status': status})

    def send(self, chat_id, text):
        return self.tool('waha', 'POST', '/api/sendText', {'session': 'default', 'chatId': chat_id, 'text': text, 'linkPreview': False})

    def reply_exists(self, chat_id, text, since):
        chat = urllib.parse.quote(chat_id, safe='')
        rows = self.tool('waha', 'GET', '/api/default/chats/' + chat + '/messages?limit=50&downloadMedia=false')
        if not isinstance(rows, list):
            return False
        return any(row.get('fromMe') is True and row.get('body') == text and float(row.get('timestamp') or 0) >= since - 2 for row in rows)

    def extract(self, action, person, token):
        # #adf jobs use the Ama Da Flow model; everything else (and everything while paused) uses Dotcross.
        hook = 'waha-voice-action-worker' if action['payload'].get('adf') and not ADF_PAUSED else 'waha-voice-action-worker-dotcross'
        return self.request('POST', self.n8n + '/webhook/' + hook, {
            'jobId': action['id'], 'token': token, 'chatId': action['chat'],
            'reference': action['reference'], 'messageId': action['payload']['messageId'],
            'allowedActions': person['actions'], 'freeText': action['payload'].get('freeText') is True,
        }, {'X-Api-Key':self.waha_key})


class Runner:
    def __init__(self, store, api, people, groups=None):
        # groups maps a WhatsApp group ID to the ClickUp list its requests use; anything else uses LIST_ID.
        self.store, self.api, self.people, self.groups = store, api, people, groups or {}

    @staticmethod
    def list_id(action):
        # Fixed at intake, so a private yes on a group request keeps the group's list.
        list_id = action['payload'].get('listId') or LIST_ID
        return LIST_ID if ADF_PAUSED and list_id == ADF_LIST_ID else list_id

    @staticmethod
    def adf_ok(person, chat):
        return not person.get('noAdf') and chat not in NO_ADF_GROUPS

    def person(self, action):
        # chat may be a group, so look the sender up by their person ID.
        person = next((p for p in self.people.values() if p['person'] == action['person']), None)
        if not person:
            raise APIError('sender_no_longer_allowed')
        return person

    def in_scope(self, action, task):
        person = self.person(action)
        if task.get('list', {}).get('id') != self.list_id(action) or (person.get('taskIds') is not None and task.get('id') not in person['taskIds']):
            raise APIError('task_outside_scope')
        return task

    def resolve(self, action):
        payload = action['payload']
        ref = payload.get('task', '').strip()
        link = re.fullmatch(r'https?://app\.clickup\.com/t/(?:\d+/)?([a-zA-Z0-9]+)(?:[/?#].*)?', ref)
        bare = re.fullmatch(r'#?([a-zA-Z0-9]{5,20})', ref)
        task_id = link.group(1) if link else bare.group(1) if bare and any(c.isdigit() for c in bare.group(1)) else None
        if task_id:
            return self.in_scope(action, self.api.get_task(self.list_id(action), task_id))
        tasks = [t for t in self.api.tasks(self.list_id(action)) if t.get('list', {}).get('id') == self.list_id(action)]
        person = self.person(action)
        if person.get('taskIds') is not None:
            tasks = [t for t in tasks if t['id'] in person['taskIds']]
        said = words(ref)
        if not payload.get('update'):
            starts = [(t, words(t.get('name', ''))) for t in tasks if words(t.get('name', ''))]
            starts = [(t, name) for t, name in starts if said[:len(name)] == name]
            longest = max((len(name) for _, name in starts), default=0)
            matches = [t for t, name in starts if len(name) == longest]
            if len(matches) == 1:
                matches_text = list(re.finditer(r'[^\W_]+', ref, re.UNICODE))
                rest = ref[matches_text[longest - 1].end():].lstrip(' \t\n:,.;-')
                if not rest or len(rest) > 1000:
                    raise APIError('update_missing')
                payload['update'] = rest
                return self.in_scope(action, matches[0])
        else:
            matches = [t for t in tasks if words(t.get('name', '')) == said] if said else []
            if not matches and len(''.join(said)) >= 3:
                matches = [t for t in tasks if all(word in words(t.get('name', '')) for word in said)]
        if len(matches) != 1:
            raise APIError('task_ambiguous' if len(matches) > 1 else 'task_not_found')
        return self.in_scope(action, matches[0])

    def pending(self, action, preview):
        text = preview + ('\nList: Ama Da Flow' if self.list_id(action) == ADF_LIST_ID else '') + '\nReply yes or no within 15 minutes.'
        self.store.patch(action['id'], payload=action['payload'], state='pending', expires=time.time() + 900, attempts=0,
                         notice=(action, 'confirmation', text))

    def controls(self, action):
        payload = action['payload']
        now = time.time()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT state FROM actions WHERE id=?', (action['id'],)).fetchone()
            if current is None or current['state'] == 'done':
                return
            wanted = 'pending' if payload['action'] == 'confirm' else 'attention'
            candidates = [self.store.row(r) for r in db.execute('SELECT * FROM actions WHERE person=? AND state=?', (action['person'], wanted))]
            group = action['chat'].endswith('@g.us')
            if group:
                # In a group, yes/no only answers requests made in that group.
                candidates = [r for r in candidates if r['chat'] == action['chat']]
            code = payload.get('code', '')
            if code:
                candidates = [r for r in candidates if r['id'].startswith(code)]
            if group and not candidates:
                pass  # A stray "ok" in a group must not make the bot speak.
            elif len(candidates) != 1:
                # Codes stay hidden on prompts; they only appear here, when a bare reply is ambiguous.
                text = 'No matching request is waiting. Please send the request again.' if not candidates else 'More than one request is waiting. Reply ' + ('yes or no' if wanted == 'pending' else 'retry') + ' followed by its code:\n' + '\n'.join(r['id'][:10] + ' ' + (r['payload'].get('title') or r['payload'].get('taskName') or r['kind']) for r in candidates)
                self.store.enqueue(db, action, 'control', text)
            else:
                target = candidates[0]
                if payload['action'] == 'confirm' and payload.get('answer') == 'no':
                    db.execute("UPDATE actions SET state='cancelled',payload='{}',token=NULL,updated=? WHERE id=?", (now, target['id']))
                    self.store.enqueue(db, action, 'control', 'Cancelled "' + (target['payload'].get('title') or target['payload'].get('taskName') or 'the request') + '".')
                else:
                    proposal = target['payload']
                    stage = target['stage']
                    if payload['action'] == 'confirm':
                        proposal['confirmed'] = True
                    else:
                        proposal['retryRound'] = proposal.get('retryRound', 0) + 1
                        if stage in ('create_started', 'comment_started'):
                            # Explicit retry authorizes another write, following reconciliation.
                            stage = 'start'
                    db.execute("UPDATE actions SET state='ready',stage=?,payload=?,chat=?,next_run=?,updated=?,attempts=0,uncertain_checks=0 WHERE id=?",
                               (stage, json.dumps(proposal), action['chat'], now, now, target['id']))
                db.execute("DELETE FROM outbox WHERE id=? AND sent IS NULL", (target['id'] + ':confirmation',))
            # Target selection, mutation, outbox and control consumption share one transaction.
            db.execute("UPDATE actions SET state='done',updated=? WHERE id=?", (now, action['id']))

    def uncertain(self, action):
        checks = action['uncertain_checks'] + 1
        if checks >= 2:
            self.store.patch(action['id'], state='attention', uncertain_checks=checks, last_error='write_unconfirmed', notice=(action, 'uncertain-' + str(action['payload'].get('retryRound', 0)), 'I could not confirm whether ClickUp saved request ' + action['id'][:10] + '. Check ClickUp first. If it is absent, reply retry ' + action['id'][:10] + '.'))
        else:
            self.store.patch(action['id'], state='ready', uncertain_checks=checks, next_run=time.time() + 120)

    def checkpoint(self, action, stage, completed=False):
        action['stage'] = stage
        changes = {'stage': stage, 'payload': action['payload']}
        if completed:
            changes.update(attempts=0, uncertain_checks=0)
        self.store.patch(action['id'], **changes)

    def finish(self, action, text):
        self.store.patch(action['id'], state='done', payload=action['payload'], token=None, last_error=None, notice=(action, 'success', text))

    def create(self, action):
        payload = action['payload']
        if action['stage'] == 'start':
            existing = next((t for t in self.api.tasks(self.list_id(action)) if str(t.get('description', '')).strip().split('\n')[-1].strip() == action['reference']), None)
            if existing:
                self.in_scope(action, existing)
                payload['taskId'] = existing['id']
                self.checkpoint(action, 'created', completed=True)
            elif not payload.get('confirmed') and (payload.get('assignees') or payload.get('voice')):
                members = self.api.members(self.list_id(action)) if payload.get('assignees') else []
                matched, unmatched = [], []
                for name in payload.get('assignees', []):
                    said = words(name)
                    hits = [m for m in members if said and all(word in words((m.get('username') or '') + ' ' + (m.get('email') or '').split('@')[0]) for word in said)]
                    if len(hits) != 1:
                        unmatched.append(name)
                    elif hits[0]['id'] not in [m['id'] for m in matched]:
                        matched.append(hits[0])
                payload['assigneeIds'] = [m['id'] for m in matched]
                payload['unmatched'] = unmatched
                if matched or payload.get('voice'):
                    # AI-understood requests are always previewed, since a mishearing or misreading must not write to ClickUp.
                    if payload['action'] == 'save_idea':
                        preview = 'Save idea "' + payload['title'] + '"?'
                    else:
                        preview = 'Create task "' + payload['title'] + '"' + (' and assign ' + ', '.join(m.get('username') or m.get('email') or str(m['id']) for m in matched) if matched else '') + '?' + (' Unmatched names: ' + ', '.join(unmatched) if unmatched else '')
                    if payload.get('voice') and payload.get('description'):
                        preview += '\n' + payload['description'][:300]
                    self.pending(action, preview)
                    return
        if action['stage'] in ('start', 'create_started'):
            if action['stage'] == 'create_started':
                existing = next((t for t in self.api.tasks(self.list_id(action)) if str(t.get('description', '')).strip().split('\n')[-1].strip() == action['reference']), None)
                if not existing:
                    self.uncertain(action)
                    return
                self.in_scope(action, existing)
                payload['taskId'] = existing['id']
                self.checkpoint(action, 'created', completed=True)
            else:
                if payload.get('assigneeIds'):
                    valid = {m['id'] for m in self.api.members(self.list_id(action))}
                    if not set(payload['assigneeIds']) <= valid:
                        raise APIError('assignee_no_longer_member')
                data = {'name': payload['title'], 'markdown_content': '\n\n'.join(filter(None, [payload.get('description', ''), action['reference']])), 'tags': ['idea'] if payload['action'] == 'save_idea' else [], 'assignees': payload.get('assigneeIds', [])}
                self.checkpoint(action, 'create_started')
                try:
                    result = self.api.create(self.list_id(action), data)
                except APIError as error:
                    if not error.ambiguous:
                        self.checkpoint(action, 'start')
                    raise
                payload['taskId'] = result['id']
                self.checkpoint(action, 'created', completed=True)
        self.in_scope(action, self.api.get_task(self.list_id(action), payload['taskId']))
        text = ('Saved idea: ' if payload['action'] == 'save_idea' else 'Created task: ') + payload['title']
        if payload.get('unmatched'):
            text += '\nUnassigned names: ' + ', '.join(payload['unmatched'])
        self.finish(action, text + '\nhttps://app.clickup.com/t/' + payload['taskId'])

    def progress(self, action):
        payload = action['payload']
        if not payload.get('taskId'):
            task = self.resolve(action)
            payload.update(taskId=task['id'], taskName=task['name'], baseline=task['status']['status'])
            if not payload.get('update'):
                raise APIError('update_missing')
            intent = status_intent(payload['update'])
            if payload.get('voice') and not re.search(r'\b(will|tomorrow|akan|besok|nanti)\b', payload['update'], re.I):
                intent = 'complete' if payload.get('completed') is True else 'in progress' if payload.get('inProgress') is True else None
            payload['desiredStatus'] = intent
            self.store.patch(action['id'], payload=payload)
        if (payload.get('desiredStatus') == 'complete' or payload.get('voice')) and not payload.get('confirmed'):
            status = {'complete': ' and mark it complete', 'in progress': ' and set it in progress'}.get(payload.get('desiredStatus'), '')
            self.pending(action, 'Post progress on "' + payload['taskName'] + '"' + status + '?\n' + payload['update'])
            return
        task = self.in_scope(action, self.api.get_task(self.list_id(action), payload['taskId']))
        if action['stage'] in ('start', 'comment_started'):
            existing = next((c for c in self.api.get_comments(self.list_id(action), payload['taskId']) if str(c.get('comment_text', '')).strip().split('\n')[-1].strip() == action['reference']), None)
            if existing:
                if action['stage'] == 'start' and not payload.get('commentAttempted'):
                    self.finish(action, 'Progress was already recorded on ' + payload['taskName'] + '. Current status: ' + task['status']['status'] + '\nhttps://app.clickup.com/t/' + payload['taskId'])
                    return
                self.checkpoint(action, 'commented', completed=True)
            elif action['stage'] == 'comment_started':
                self.uncertain(action)
                return
            else:
                payload['commentAttempted'] = True
                self.checkpoint(action, 'comment_started')
                try:
                    self.api.comment(self.list_id(action), payload['taskId'], payload['update'] + '\n\n' + action['reference'])
                except APIError as error:
                    if not error.ambiguous:
                        self.checkpoint(action, 'start')
                    raise
                self.checkpoint(action, 'commented', completed=True)
        desired = payload.get('desiredStatus')
        if desired and action['stage'] != 'status_applied':
            task = self.in_scope(action, self.api.get_task(self.list_id(action), payload['taskId']))
            current = task['status']['status']
            if current != desired:
                if current != payload['baseline']:
                    raise APIError('status_changed_since_request')
                self.checkpoint(action, 'status_started')
                try:
                    self.api.status(self.list_id(action), payload['taskId'], desired)
                except APIError as error:
                    if not error.ambiguous:
                        self.checkpoint(action, 'commented')
                    raise
            self.checkpoint(action, 'status_applied', completed=True)
        text = 'Posted progress on ' + payload['taskName'] + ('. Status: ' + desired if desired else '')
        self.finish(action, text + '\nhttps://app.clickup.com/t/' + payload['taskId'])

    def failure(self, action, error):
        current = self.store.get(action['id'])
        attempts = current['attempts'] + 1
        partial = current['stage'] in ('commented', 'status_started')
        if error.retryable and attempts <= 8:
            message = 'Your progress comment is saved, but the status update has not been confirmed. I will retry that step.' if partial else 'Request ' + action['id'][:10] + ' is delayed. I will retry it.'
            # Plain text may be personal chat, so it gets no delay notices before the AI has read it.
            quiet = current['kind'] == 'voice' and current['payload'].get('freeText')
            self.store.patch(action['id'], state='extracting' if current['kind'] == 'voice' else 'ready', attempts=attempts, last_error=error.code, next_run=time.time() + min(600, 30 * 2 ** (attempts - 1)), notice=None if quiet else (action, 'delayed-' + str(current['payload'].get('retryRound', 0)), message))
            return
        messages = {
            'task_not_found': 'I could not find that task in this list. Send progress: <task link> <update>.',
            'task_ambiguous': 'More than one task matches. Send progress: <task link> <update>.',
            'update_missing': 'Include the progress update after the task link or name.',
            'task_outside_scope': 'That task is outside the list for this chat. Add #adf for an Ama Da Flow task.',
            'status_changed_since_request': 'The progress comment is saved. The task status changed since your request, so please send a fresh status request.',
        }
        message = messages.get(error.code, ('Your comment is saved. ' if partial else '') + 'I could not finish request ' + action['id'][:10] + '. Reply retry ' + action['id'][:10] + ' after the connection or permissions are restored.')
        self.store.patch(action['id'], state='attention', attempts=attempts, last_error=error.code, notice=(action, 'attention-' + str(current['payload'].get('retryRound', 0)) + '-' + str(attempts), message))

    def run_once(self):
        self.store.cleanup()
        action = self.store.claim()
        if not action:
            return False
        try:
            person = self.person(action)
            kind = action['kind']
            if kind in ACTIONS and kind not in person['actions']:
                raise APIError('action_not_allowed')
            if kind in ('confirm', 'retry'):
                self.controls(action)
            elif kind == 'voice':
                if action['attempts'] >= 8:
                    raise APIError('voice_processing_timeout')
                token = secrets.token_hex(24)
                self.store.patch(action['id'], token=token)
                self.api.extract(action, person, token)
                with self.store.db() as db:
                    db.execute("UPDATE actions SET state='extracting',next_run=?,attempts=attempts+1 WHERE id=? AND kind='voice' AND token=? AND state='running'", (time.time() + 600, action['id'], token))
            elif kind in ('create_task', 'save_idea'):
                self.create(action)
            elif kind == 'post_progress':
                self.progress(action)
            elif kind == 'clarify':
                self.finish(action, action['payload']['replyText'])
            elif kind == 'ignore':
                self.store.patch(action['id'], state='done', payload={}, token=None, last_error=None)
            else:
                raise APIError('unknown_action')
        except APIError as error:
            self.failure(action, error)
        except Exception:
            self.failure(action, APIError('processing_error', retryable=True))
        return True

    def send_once(self):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM outbox WHERE sent IS NULL AND next_run<=? ORDER BY created LIMIT 1', (time.time(),)).fetchone()
        if row is None:
            return False
        message = dict(row)
        try:
            if message['started'] is None or not self.api.reply_exists(message['chat'], message['text'], message['started']):
                with self.store.db() as db:
                    db.execute('UPDATE outbox SET started=? WHERE id=?', (time.time(), message['id']))
                self.api.send(message['chat'], message['text'])
            with self.store.db() as db:
                db.execute('UPDATE outbox SET sent=?,last_error=NULL WHERE id=?', (time.time(), message['id']))
        except Exception:
            with self.store.db() as db:
                db.execute('UPDATE outbox SET attempts=attempts+1,last_error=?,next_run=? WHERE id=?', ('delivery_failed', time.time() + min(3600, 30 * 2 ** min(message['attempts'], 7)), message['id']))
        return True


def validated_plan(value):
    if not isinstance(value, dict) or value.get('action') not in ACTIONS | {'clarify', 'ignore'}:
        raise ValueError('Invalid plan')
    if value['action'] == 'ignore':
        return {'action':'ignore'}
    def field(name, limit, required=True):
        text = value.get(name, '')
        if not isinstance(text, str) or len(text) > limit or (required and not text.strip()):
            raise ValueError('Invalid plan field')
        return text.strip()
    kind = value['action']
    if kind == 'clarify':
        return {'action':kind,'replyText':field('replyText',300)}
    if kind == 'post_progress':
        return {'action':kind,'task':field('task',1200,False),'update':field('update',1000,False), 'completed':value.get('completed') is True,'inProgress':value.get('inProgress') is True}
    assignees = value.get('assignees', [])
    if not isinstance(assignees, list) or len(assignees) > 5 or any(not isinstance(x,str) or len(x)>60 for x in assignees):
        raise ValueError('Invalid assignees')
    return {'action':kind,'title':field('title',200),'description':field('description',2000,False),'assignees':assignees}


def application(store, runner, api_key):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, code, payload):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/healthz':
                self.respond(200, {'status':'ok'})
            else:
                self.respond(404, {'error':'not_found'})

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('X-Api-Key',''), api_key):
                self.respond(401, {'error':'unauthorized'})
                return
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 8192:
                    raise ValueError('Invalid body length')
                body = json.loads(self.rfile.read(length))
                if self.path == '/submit':
                    chat, reference = body.get('chatId',''), body.get('reference','')
                    person = runner.people.get(chat)
                    if not person or not re.fullmatch(r'WAHA pilot message [A-Za-z0-9-]{8,128}',reference):
                        raise ValueError('Invalid sender or message')
                    reply_to = body.get('replyTo')
                    if reply_to is not None and (not isinstance(reply_to,str) or not re.fullmatch(r'[0-9-]{5,40}@g\.us',reply_to) or body.get('messageId')):
                        raise ValueError('Invalid group')
                    if body.get('messageId') and 'action' not in body:
                        message_id = body['messageId']
                        if not isinstance(message_id,str) or len(message_id)>250 or not message_id.startswith('false_' + chat + '_'):
                            raise ValueError('Invalid voice reference')
                        payload = {'action':'voice','messageId':message_id}
                        if body.get('freeText') is True:
                            payload['freeText'] = True
                        if body.get('workspace') == 'adf' and runner.adf_ok(person, chat):
                            payload['adf'] = True
                    elif body.get('action') in ('confirm','retry'):
                        payload = {'action':body['action'],'answer':body.get('answer'),'code':body.get('code','').lower()}
                        if (payload['action'] == 'confirm' and payload['answer'] not in ('yes','no')) or not re.fullmatch(r'[a-f0-9]{0,32}',payload['code']):
                            raise ValueError('Invalid confirmation')
                    else:
                        payload = validated_plan(body)
                        if payload['action'] in ACTIONS and payload['action'] not in person['actions']:
                            raise ValueError('Action not allowed')
                        adf = body.get('workspace') == 'adf' and runner.adf_ok(person, reply_to or chat)
                        payload['listId'] = ADF_LIST_ID if adf else runner.groups.get(reply_to, LIST_ID)
                    if reply_to and runner.groups.get(reply_to) == ADF_LIST_ID and not runner.adf_ok(person, reply_to):
                        raise ValueError('Sender may not use Ama Da Flow')
                    action = store.submit(person['person'],reply_to or chat,reference,payload)
                    self.respond(200, {'accepted':True,'id':action['id'],'state':action['state']})
                elif self.path in ('/plan','/failure','/handoff'):
                    with store.db() as db:
                        db.execute('BEGIN IMMEDIATE')
                        action = store.row(db.execute('SELECT * FROM actions WHERE id=?',(body.get('jobId'),)).fetchone())
                        if not action or action['kind']!='voice' or action['state'] not in ('running','extracting') or not action['token'] or not hmac.compare_digest(action['token'],body.get('token') or ''):
                            self.respond(409, {'error':'stale_job'})
                            return
                        if self.path == '/handoff':
                            # Dotcross heard "Ama Da Flow" in the message: rerun the job on the Ama Da Flow workflow instead.
                            handoff = not ADF_PAUSED and not action['payload'].get('adf') and runner.adf_ok(runner.person(action), action['chat'])
                            if handoff:
                                payload = {**action['payload'], 'adf': True}
                                db.execute("UPDATE actions SET payload=?,state='extracting',token=NULL,next_run=?,updated=? WHERE id=?", (json.dumps(payload),time.time(),time.time(),action['id']))
                            self.respond(200, {'accepted':True,'handoff':handoff})
                            return
                        if self.path == '/plan':
                            payload = validated_plan(body.get('plan'))
                            if payload['action'] in ACTIONS and payload['action'] not in runner.person(action)['actions']:
                                raise ValueError('Action not allowed')
                            payload['voice'] = True
                            adf = action['payload'].get('adf') or ((body.get('plan') or {}).get('workspace') == 'adf' and runner.adf_ok(runner.person(action), action['chat']))
                            payload['listId'] = ADF_LIST_ID if adf else action['payload'].get('listId') or LIST_ID
                            payload['freeText'] = action['payload'].get('freeText') is True
                            db.execute("UPDATE actions SET payload=?,kind=?,state='ready',token=NULL,attempts=0,next_run=?,updated=? WHERE id=?", (json.dumps(payload),payload['action'],time.time(),time.time(),action['id']))
                        else:
                            attempts=action['attempts']+1
                            db.execute("UPDATE actions SET state=?,token=NULL,attempts=?,last_error='voice_processing_failed',next_run=? WHERE id=?", ('attention' if attempts>=8 else 'extracting',attempts,time.time()+min(600,30*2**min(attempts,4)),action['id']))
                        if self.path == '/failure':
                            source = 'message' if action['payload'].get('freeText') else 'voice'
                            message = 'Processing your ' + source + ' is delayed for request ' + action['id'][:10] + '. I will retry. You can also send a command such as task: ...'
                            if attempts >= 8:
                                message = 'I could not process ' + source + ' request ' + action['id'][:10] + '. Send a command such as task: ... or reply retry ' + action['id'][:10] + '.'
                            if attempts >= 8 or source == 'voice':
                                store.enqueue(db,action,'voice-failure-' + ('final' if attempts >= 8 else 'delayed'),message)
                    self.respond(200, {'accepted':True})
                else:
                    self.respond(404, {'error':'not_found'})
            except (ValueError,TypeError,KeyError,APIError):
                self.respond(400, {'error':'invalid_request'})
            except Exception:
                self.respond(503, {'error':'temporarily_unavailable'})
    return Handler


class ActionServer(ThreadingHTTPServer):
    request_queue_size = 64
    daemon_threads = True


def main():
    os.umask(0o077)
    data = Path(os.getenv('ACTION_DATA','/data'))
    data.mkdir(parents=True,exist_ok=True)
    # Hold one process-wide writer lock, including across accidental duplicate deployments.
    lock = open(data / 'worker.lock','a')
    fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
    people = {}
    for entry in json.loads(Path(os.getenv('PEOPLE_FILE','/app/people.json')).read_text()):
        for alias in entry['ids']:
            people[alias] = {'person':entry['ids'][0], 'actions':entry['actions'], 'noAdf':entry.get('noAdf') is True, **({'taskIds':entry['taskIds']} if 'taskIds' in entry else {})}
    groups = json.loads(Path(os.getenv('GROUPS_FILE','/app/groups.json')).read_text())
    if not all(re.fullmatch(r'[0-9-]{5,40}@g\.us',g) and re.fullmatch(r'\d{1,20}',str(l)) for g,l in groups.items()):
        raise SystemExit('groups.json must map <group>@g.us to a numeric ClickUp list ID')
    store = Store(data / 'actions.sqlite3')
    api = API()
    runner = Runner(store,api,people,groups)
    stop = threading.Event()
    def work():
        while not stop.is_set():
            try:
                active = runner.run_once()
                runner.send_once()
            except Exception:
                active = False
            stop.wait(0.2 if active else 1)
    threading.Thread(target=work,daemon=True).start()
    ActionServer(('0.0.0.0',8000),application(store,runner,api.waha_key)).serve_forever()


if __name__ == '__main__':
    main()

import tempfile
import unittest
from pathlib import Path
from worker import Store, status_intent

def all_actions(store):
    with store.db() as db:
        return [store.row(row) for row in db.execute('SELECT * FROM actions ORDER BY created,id')]

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'actions.sqlite3')
    def tearDown(self):
        self.tmp.cleanup()
    def test_duplicate_intake_has_one_action(self):
        a = self.store.submit('person', 'chat', 'reference', {'action':'create_task','title':'Call vendor'})
        b = self.store.submit('person', 'chat', 'reference', {'action':'create_task','title':'Call vendor'})
        self.assertEqual(a['id'], b['id'])
        self.assertEqual(len(all_actions(self.store)), 1)
    def test_future_status_stays_comment(self):
        self.assertIsNone(status_intent('we will mark it in progress tomorrow'))
        self.assertEqual(status_intent('now is on progress'), 'in progress')
        self.assertEqual(status_intent('is completed'), 'complete')
        self.assertIsNone(status_intent('finished the first draft'))


class FlowTests(unittest.TestCase):
    def setUp(self):
        from worker import Runner
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / 'actions.sqlite3')
        self.api = FakeAPI()
        self.runner = Runner(self.store, self.api, {'phone': {'person':'person','actions':['create_task','save_idea','post_progress']}, 'lid': {'person':'person','actions':['create_task','save_idea','post_progress']}})
    def tearDown(self):
        self.tmp.cleanup()
    def add(self, payload, reference='ref', chat='phone'):
        return self.store.submit('person', chat, reference, payload)
    def test_two_pending_requests_are_preserved_and_need_code(self):
        a=self.add({'action':'create_task','title':'First','assignees':['Victor']},'one')
        b=self.add({'action':'create_task','title':'Second','assignees':['Victor']},'two')
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual([x['state'] for x in all_actions(self.store)], ['pending','pending'])
        self.add({'action':'confirm','answer':'yes'},'yes')
        self.runner.run_once()
        self.assertEqual(len(self.api.created),0)
        with self.store.db() as db: texts=[r['text'] for r in db.execute('SELECT text FROM outbox ORDER BY created')]
        self.assertTrue(all(a['id'][:10] not in t and b['id'][:10] not in t for t in texts[:2]))
        self.assertIn(a['id'][:10]+' First',texts[2]); self.assertIn(b['id'][:10]+' Second',texts[2])
        self.add({'action':'confirm','answer':'yes','code':a['id'][:10]},'yes-code','lid')
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual(self.api.created[0]['name'],'First')
        self.assertEqual(self.store.get(b['id'])['state'],'pending')
    def test_failure_after_confirmation_keeps_retryable_action(self):
        a=self.add({'action':'create_task','title':'First','assignees':['Victor']})
        self.runner.run_once()
        self.add({'action':'confirm','answer':'yes'},'yes')
        self.runner.run_once()
        self.api.fail_create=True
        self.runner.run_once()
        self.assertEqual(self.store.get(a['id'])['state'],'ready')
        self.api.fail_create=False
        self.store.patch(a['id'],next_run=0)
        self.runner.run_once()
        self.assertEqual(len(self.api.created),1)
    def test_partial_progress_resumes_without_duplicate_comment(self):
        a=self.add({'action':'post_progress','task':'86abc123','update':'now is on progress'})
        self.api.fail_status=True
        self.runner.run_once()
        self.assertEqual(len(self.api.comments),1)
        self.assertEqual(self.store.get(a['id'])['stage'],'commented')
        self.api.fail_status=False; self.store.patch(a['id'],next_run=0)
        self.runner.run_once()
        self.assertEqual(len(self.api.comments),1)
        self.assertEqual(self.api.task['status']['status'],'in progress')
        self.api.task['status']['status']='complete'
        self.add({'action':'post_progress','task':'86abc123','update':'now is on progress'})
        self.runner.run_once()
        self.assertEqual(self.api.task['status']['status'],'complete')
    def test_uncertain_creation_reconciles_marker(self):
        a=self.add({'action':'create_task','title':'Call vendor'})
        self.api.uncertain_create=True
        self.runner.run_once()
        self.assertEqual(len(self.api.created),1)
        self.store.patch(a['id'],next_run=0)
        self.runner.run_once()
        self.assertEqual(len(self.api.created),1)
        self.assertEqual(self.store.get(a['id'])['state'],'done')
    def test_changed_scope_is_rechecked(self):
        a=self.add({'action':'post_progress','task':'86abc123','update':'done'})
        self.runner.run_once()
        self.api.task['list']['id']='elsewhere'
        self.add({'action':'confirm','answer':'yes'},'yes')
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual(len(self.api.comments),0)
        self.assertEqual(self.store.get(a['id'])['state'],'attention')
    def test_pending_payload_is_actually_removed_at_expiry(self):
        a=self.add({'action':'create_task','title':'Private proposal','assignees':['Victor']})
        self.runner.run_once(); self.store.patch(a['id'],expires=1)
        self.store.cleanup()
        self.assertEqual(self.store.get(a['id'])['state'],'expired')
        self.assertEqual(self.store.get(a['id'])['payload'],{})
    def test_reply_failure_does_not_repeat_clickup_action(self):
        a=self.add({'action':'create_task','title':'Call vendor'})
        self.runner.run_once()
        self.api.fail_reply=True
        self.runner.send_once()
        self.assertEqual(len(self.api.created),1)
        self.assertEqual(self.store.get(a['id'])['state'],'done')
        self.api.fail_reply=False
        with self.store.db() as db:
            db.execute('UPDATE outbox SET next_run=0 WHERE sent IS NULL')
        self.runner.send_once()
        self.assertEqual(len(self.api.created),1)
        self.assertEqual(len(self.api.sent),1)
    def test_status_changed_by_someone_else_is_not_overwritten(self):
        a=self.add({'action':'post_progress','task':'86abc123','update':'now is in progress'})
        self.api.fail_status=True; self.runner.run_once()
        self.api.fail_status=False; self.api.task['status']['status']='complete'
        self.store.patch(a['id'],next_run=0); self.runner.run_once()
        self.assertEqual(self.api.task['status']['status'],'complete')
        self.assertEqual(self.store.get(a['id'])['state'],'attention')
    def test_legacy_comment_replay_does_not_reopen_completed_task(self):
        self.api.task['status']['status']='complete'
        self.api.comments=[{'id':'legacy','comment_text':'now is on progress\n\nref'}]
        self.add({'action':'post_progress','task':'86abc123','update':'now is on progress'})
        self.runner.run_once()
        self.assertEqual(self.api.task['status']['status'],'complete')
        self.assertEqual(len(self.api.comments),1)
    def test_exact_name_and_name_prefix_resolve(self):
        a=self.add({'action':'post_progress','task':'Launch','update':'Waiting for samples'})
        self.runner.run_once()
        self.assertEqual(self.store.get(a['id'])['state'],'done')
        b=self.add({'action':'post_progress','task':'Launch is completed','update':''},'second')
        self.runner.run_once()
        self.assertEqual(self.store.get(b['id'])['state'],'pending')
    def test_explicit_retry_of_unconfirmed_write_reconciles_then_reissues(self):
        a=self.add({'action':'create_task','title':'Call vendor'})
        self.store.patch(a['id'],stage='create_started',state='attention')
        self.add({'action':'retry','code':a['id'][:10]},'retry')
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual(len(self.api.created),1)
    def test_voice_dispatch_does_not_retry_forever(self):
        a=self.add({'action':'voice','messageId':'message'})
        self.store.patch(a['id'],attempts=8)
        self.runner.run_once()
        self.assertEqual(self.store.get(a['id'])['state'],'attention')
    def test_retry_does_not_grant_a_missing_confirmation(self):
        a=self.add({'action':'post_progress','task':'86abc123','update':'done'})
        self.store.patch(a['id'],state='attention',last_error='http_404')
        self.add({'action':'retry','code':a['id'][:10]},'retry')
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual(self.store.get(a['id'])['state'],'pending')
        self.assertEqual(self.api.comments,[])
    def test_confirmation_target_and_control_are_consumed_atomically(self):
        a=self.add({'action':'create_task','title':'Deck','assignees':['Victor']})
        self.runner.run_once()
        control=self.add({'action':'confirm','answer':'yes'},'yes')
        with self.store.db() as db:
            db.execute("CREATE TRIGGER injected_crash BEFORE UPDATE OF state ON actions WHEN NEW.id='" + control['id'] + "' AND NEW.state='done' BEGIN SELECT RAISE(ABORT,'injected crash'); END")
        with self.assertRaises(Exception): self.runner.controls(control)
        self.assertEqual(self.store.get(a['id'])['state'],'pending')
        self.assertEqual(self.store.get(control['id'])['state'],'ready')
    def test_persistent_rate_limit_reaches_attention(self):
        a=self.add({'action':'create_task','title':'Call vendor'})
        self.api.fail_create=True
        for _ in range(12):
            self.store.patch(a['id'],next_run=0)
            self.runner.run_once()
        self.assertEqual(self.store.get(a['id'])['state'],'attention')
    def test_restart_preserves_completed_action_and_deduplication(self):
        a=self.add({'action':'create_task','title':'Call vendor'})
        self.runner.run_once()
        reopened=Store(Path(self.tmp.name)/'actions.sqlite3')
        repeated=reopened.submit('person','phone','ref',{'action':'create_task','title':'Call vendor'})
        self.assertEqual(repeated['id'],a['id'])
        self.assertEqual(repeated['state'],'done')
        self.assertIsNone(reopened.claim())
    def test_create_uses_clickup_markdown_content_field(self):
        self.add({'action':'create_task','title':'Call vendor','description':'# Follow up'})
        self.runner.run_once()
        self.assertIn('markdown_content', self.api.created[0])
    def test_pending_and_its_prompt_commit_together(self):
        a=self.add({'action':'create_task','title':'Deck'})
        with self.store.db() as db:
            db.execute("CREATE TRIGGER fail_prompt BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT,'injected crash'); END")
        with self.assertRaises(Exception): self.runner.pending(a,'Create Deck?')
        self.assertEqual(self.store.get(a['id'])['state'],'ready')

class FakeAPI:
    def __init__(self):
        self.task={'id':'86abc123','name':'Launch','list':{'id':'1100310000198006'},'status':{'status':'to do'},'date_updated':'1'}
        self.created=[]; self.comments=[]; self.sent=[]
        self.fail_create=False; self.uncertain_create=False; self.fail_status=False; self.fail_reply=False
    def tasks(self, list_id): return [t for t in [self.task,*self.created] if t['list']['id']==list_id]
    def get_task(self, list_id, task_id): return next((dict(t) for t in self.created if t['id']==task_id),None) or {**self.task,'list':dict(self.task['list']),'status':dict(self.task['status'])}
    def members(self, list_id): return [{'id':101,'username':'Victor Chandra','email':'victor@example.com'}]
    def create(self, list_id, payload):
        from worker import APIError
        if self.fail_create: raise APIError('rate_limited',retryable=True)
        task={**payload,'id':'new123456','list':{'id':list_id},'description':payload['markdown_content']}
        self.created.append(task)
        if self.uncertain_create: raise APIError('timeout',retryable=True,ambiguous=True)
        return task
    def get_comments(self, list_id, task_id): return self.comments
    def comment(self, list_id, task_id, text):
        row={'id':'c'+str(len(self.comments)),'comment_text':text}; self.comments.append(row); return row
    def status(self, list_id, task_id, status):
        from worker import APIError
        if self.fail_status: raise APIError('rate_limited',retryable=True)
        self.task['status']['status']=status
    def send(self, chat_id, text):
        from worker import APIError
        if self.fail_reply: raise APIError('unavailable',retryable=True)
        self.sent.append((chat_id,text)); return {'id':'sent1'}
    def reply_exists(self, chat_id, text, since): return False

class HTTPTests(unittest.TestCase):
    def setUp(self):
        from worker import Runner, application, ActionServer
        import threading
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'actions.sqlite3')
        self.runner=Runner(self.store,FakeAPI(),{'phone':{'person':'person','actions':['create_task','save_idea','post_progress']}},{'120363099999999999@g.us':'901'})
        self.server=ActionServer(('127.0.0.1',0),application(self.store,self.runner,'test-key'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()
    def post(self,path,payload,key='test-key'):
        import json,urllib.request,urllib.error
        request=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+path,data=json.dumps(payload).encode(),headers={'X-Api-Key':key,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(request,timeout=5) as result: return result.status,json.load(result)
        except urllib.error.HTTPError as result:
            with result: return result.code,json.load(result)
    def test_concurrent_http_delivery_persists_once(self):
        from concurrent.futures import ThreadPoolExecutor
        payload={'chatId':'phone','reference':'WAHA pilot message ABCDEF123456','action':'save_idea','title':'Bundle','description':'Seasonal bundle'}
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows=list(pool.map(lambda _:self.post('/submit',payload),range(16)))
        self.assertTrue(all(code==200 for code,_ in rows))
        self.assertEqual(len({row['id'] for _,row in rows}),1)
        self.assertEqual(len(all_actions(self.store)),1)
    def test_unauthenticated_calls_and_untrusted_senders_are_rejected(self):
        self.assertEqual(self.post('/submit',{},key='wrong')[0],401)
        self.assertEqual(self.post('/submit',{'chatId':'stranger','reference':'WAHA pilot message ABCDEF123456'})[0],400)
        self.assertEqual(len(all_actions(self.store)),0)
    def test_voice_callback_is_bound_to_the_current_job_token(self):
        a=self.store.submit('person','phone','WAHA pilot message ABCDEF123456',{'action':'voice','messageId':'false_phone_ABCDEF123456'})
        self.assertEqual(self.post('/plan',{'jobId':a['id'],'plan':{'action':'save_idea','title':'Bundle'}})[0],409)
        self.store.patch(a['id'],token='current')
        body={'jobId':a['id'],'token':'stale','plan':{'action':'save_idea','title':'Bundle'}}
        self.assertEqual(self.post('/plan',body)[0],409)
        body['token']='current'
        self.assertEqual(self.post('/plan',body)[0],200)
        self.assertEqual(self.post('/plan',body)[0],409)
        self.assertEqual(self.store.get(a['id'])['kind'],'save_idea')
    def test_handoff_reruns_job_on_ama_da_flow_once(self):
        status,row=self.post('/submit',{'chatId':'phone','reference':'WAHA pilot message HANDOFF12345','messageId':'false_phone_HANDOFF12345'})
        a=self.store.get(row['id']); self.store.patch(a['id'],token='t',state='extracting')
        self.assertEqual(self.post('/handoff',{'jobId':a['id'],'token':'t'}),(200,{'accepted':True,'handoff':True}))
        b=self.store.get(a['id']); self.assertTrue(b['payload']['adf']); self.assertEqual((b['state'],b['token']),('extracting',None))
        self.assertEqual(self.post('/handoff',{'jobId':a['id'],'token':'t'})[0],409)
        self.store.patch(a['id'],token='u',state='extracting')
        self.assertEqual(self.post('/handoff',{'jobId':a['id'],'token':'u'})[1]['handoff'],False)
        import worker
        self.assertEqual(self.post('/plan',{'jobId':a['id'],'token':'u','plan':{'action':'save_idea','title':'Bundle','description':''}})[0],200)
        self.assertEqual(self.store.get(a['id'])['payload']['listId'],worker.ADF_LIST_ID)
    def test_no_adf_people_and_groups_never_reach_ama_da_flow(self):
        import worker
        self.runner.people['blocked']={'person':'blocked','actions':['create_task','save_idea','post_progress'],'noAdf':True}
        self.runner.groups['120363088888888888@g.us']=worker.ADF_LIST_ID
        status,row=self.post('/submit',{'chatId':'blocked','reference':'WAHA pilot message NOADF1234567','action':'save_idea','title':'x','description':'','workspace':'adf'})
        self.assertEqual(self.store.get(row['id'])['payload']['listId'],worker.LIST_ID)
        self.assertEqual(self.post('/submit',{'chatId':'blocked','replyTo':'120363088888888888@g.us','reference':'WAHA pilot message NOADF7654321','action':'save_idea','title':'x','description':''})[0],400)
        status,row=self.post('/submit',{'chatId':'blocked','reference':'WAHA pilot message NOADFVOICE12','messageId':'false_blocked_NOADFVOICE12','workspace':'adf'})
        a=self.store.get(row['id']); self.assertNotIn('adf',a['payload'])
        self.store.patch(a['id'],token='t',state='extracting')
        self.assertEqual(self.post('/handoff',{'jobId':a['id'],'token':'t'})[1]['handoff'],False)
        worker.NO_ADF_GROUPS.add('120363077777777777@g.us')
        try:
            status,row=self.post('/submit',{'chatId':'phone','replyTo':'120363077777777777@g.us','reference':'WAHA pilot message NOADFGROUP12','action':'save_idea','title':'x','description':'','workspace':'adf'})
            self.assertEqual(self.store.get(row['id'])['payload']['listId'],worker.LIST_ID)
        finally:
            worker.NO_ADF_GROUPS.discard('120363077777777777@g.us')
    def test_group_mention_becomes_ai_job_for_that_group(self):
        import worker
        g='120363099999999999@g.us'
        status,row=self.post('/submit',{'chatId':'phone','replyTo':g,'reference':'WAHA pilot message MENTION12345','messageId':'false_'+g+'_MENTION12345_phone','freeText':True})
        self.assertEqual(status,200)
        a=self.store.get(row['id']); self.assertEqual((a['chat'],a['payload']['listId'],a['payload'].get('adf')),(g,'901',None))
        self.assertEqual(self.post('/submit',{'chatId':'phone','replyTo':g,'reference':'WAHA pilot message MENTION67890','messageId':'false_other@g.us_MENTION67890'})[0],400)
        self.assertEqual(self.post('/submit',{'chatId':'phone','replyTo':g,'reference':'WAHA pilot message MENTIONVOICE','messageId':'false_'+g+'_MENTIONVOICE_phone'})[0],400)
        self.runner.groups['120363088888888888@g.us']=worker.ADF_LIST_ID
        status,row=self.post('/submit',{'chatId':'phone','replyTo':'120363088888888888@g.us','reference':'WAHA pilot message MENTIONADF12','messageId':'false_120363088888888888@g.us_MENTIONADF12_phone','freeText':True})
        a=self.store.get(row['id']); self.assertTrue(a['payload']['adf'])
        self.store.patch(a['id'],token='t',state='extracting')
        self.assertEqual(self.post('/plan',{'jobId':a['id'],'token':'t','plan':{'action':'save_idea','title':'x','description':''}})[0],200)
        self.assertEqual(self.store.get(a['id'])['payload']['listId'],worker.ADF_LIST_ID)
    def test_confirmations_cannot_be_bypassed_with_retry(self):
        a=self.store.submit('person','phone','pending',{'action':'create_task','title':'Deck','assignees':['Victor']})
        self.runner.run_once()
        self.store.submit('person','phone','retry',{'action':'retry','code':a['id'][:10]})
        self.runner.run_once()
        self.assertEqual(self.store.get(a['id'])['state'],'pending')

class GatewayTests(unittest.TestCase):
    def test_every_clickup_call_names_its_list(self):
        from worker import API
        api=API.__new__(API); api.n8n='http://n8n'; api.waha_key='k'; sent=[]
        api.request=lambda m,u,d=None,h=None: sent.append(d) or {'statusCode':200,'body':{}}
        api.get_task('901','86abc123'); api.get_comments('901','86abc123'); api.comment('901','86abc123','hi')
        api.status('901','86abc123','complete'); api.members('901'); api.create('901',{}); api.tasks('901')
        self.assertEqual([d['list'] for d in sent],['901']*7)
    def test_each_workspace_uses_its_own_workflow(self):
        import worker
        from worker import API
        api=API.__new__(API); api.n8n='http://n8n'; api.waha_key='k'; urls=[]
        api.request=lambda m,u,d=None,h=None: urls.append(u) or {'statusCode':200,'body':{}}
        api.members(worker.ADF_LIST_ID); api.members(worker.LIST_ID); api.send('phone','hi')
        job=lambda adf: {'id':'x','chat':'phone','reference':'r','payload':{'messageId':'m',**({'adf':True} if adf else {})}}
        api.extract(job(True),{'actions':[]},'t'); api.extract(job(False),{'actions':[]},'t')
        self.assertEqual([u.rsplit('/',1)[1] for u in urls],['waha-action-tool','waha-action-tool-dotcross','waha-action-tool-dotcross','waha-voice-action-worker','waha-voice-action-worker-dotcross'])


if __name__ == '__main__':
    unittest.main()

class PlainTextTests(HTTPTests):
    def plan(self, plan, ref='ABCDEF123456'):
        status,row=self.post('/submit',{'chatId':'phone','reference':'WAHA pilot message '+ref,'messageId':'false_phone_'+ref,'freeText':True})
        self.assertEqual(status,200)
        a=self.store.get(row['id']); self.assertEqual(a['payload'],{'action':'voice','messageId':'false_phone_'+ref,'freeText':True})
        self.store.patch(a['id'],token='t',state='extracting')
        self.assertEqual(self.post('/plan',{'jobId':a['id'],'token':'t','plan':plan})[0],200)
        self.runner.run_once()
        return self.store.get(a['id'])
    def outbox(self):
        with self.store.db() as db: return [r['text'] for r in db.execute('SELECT text FROM outbox ORDER BY created')]
    def test_ignore_ends_silently(self):
        a=self.plan({'action':'ignore'})
        self.assertEqual((a['kind'],a['state']),('ignore','done'))
        self.assertEqual(self.outbox(),[])
    def test_ai_task_and_idea_wait_for_yes(self):
        a=self.plan({'action':'create_task','title':'Send samples','description':'Before Friday','assignees':[]})
        self.assertEqual(a['state'],'pending'); self.assertEqual(self.runner.api.created,[])
        self.assertIn('Create task "Send samples"?\nBefore Friday',self.outbox()[0])
        b=self.plan({'action':'save_idea','title':'Bundle','description':''},'ABCDEF654321')
        self.assertEqual(b['state'],'pending'); self.assertIn('Save idea "Bundle"?',self.outbox()[1])
        self.store.submit('person','phone','yes',{'action':'confirm','answer':'yes','code':a['id'][:10]})
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual([t['name'] for t in self.runner.api.created],['Send samples'])
    def test_ai_progress_comment_waits_for_yes(self):
        a=self.plan({'action':'post_progress','task':'Launch','update':'Waiting for samples','completed':False,'inProgress':False})
        self.assertEqual(a['state'],'pending'); self.assertEqual(self.runner.api.comments,[])
        self.assertIn('Post progress on "Launch"?\nWaiting for samples',self.outbox()[0])
    def test_free_text_flag_reaches_n8n(self):
        sent=[]
        from worker import API
        api=API.__new__(API); api.n8n='http://n8n'; api.waha_key='k'; api.request=lambda *a: sent.append(a[2])
        api.extract({'id':'x','chat':'phone','reference':'r','payload':{'messageId':'m','freeText':True}},{'actions':[]},'t')
        self.assertTrue(sent[0]['freeText'])
    def test_text_job_delays_stay_quiet_until_final(self):
        status,row=self.post('/submit',{'chatId':'phone','reference':'WAHA pilot message QUIET1234567','messageId':'false_phone_QUIET1234567','freeText':True})
        a=self.store.get(row['id'])
        for n in range(8):
            self.store.patch(a['id'],token='t',state='extracting')
            self.assertEqual(self.post('/failure',{'jobId':a['id'],'token':'t'})[0],200)
            self.assertEqual(len(self.outbox()),0 if n<7 else 1)
        self.assertIn('could not process message request',self.outbox()[0])

class GroupReplyTests(HTTPTests):
    G='120363012345678901@g.us'
    def submit(self,body):
        return self.post('/submit',{'chatId':'phone','reference':'WAHA pilot message '+body.pop('ref','GROUP1234567'),**body})
    def chats(self):
        with self.store.db() as db: return [(r['chat'],r['text']) for r in db.execute('SELECT chat,text FROM outbox ORDER BY created')]
    def test_group_task_replies_in_the_group(self):
        status,row=self.submit({'replyTo':self.G,'action':'create_task','title':'Deck','tags':[],'assignees':[]})
        self.assertEqual(status,200); self.runner.run_once()
        self.assertEqual(self.store.get(row['id'])['state'],'done')
        self.assertEqual([c for c,_ in self.chats()],[self.G])
    def test_group_confirmation_flow_stays_in_the_group(self):
        _,row=self.submit({'replyTo':self.G,'action':'create_task','title':'Deck','tags':[],'assignees':['Victor']})
        self.runner.run_once(); self.assertEqual(self.store.get(row['id'])['state'],'pending')
        self.submit({'ref':'GROUPYES1234','replyTo':self.G,'action':'confirm','answer':'yes','code':''})
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual(self.store.get(row['id'])['state'],'done')
        self.assertTrue(all(c==self.G for c,_ in self.chats()))
    def test_group_yes_is_silent_and_cannot_confirm_a_private_request(self):
        _,row=self.submit({'action':'create_task','title':'Private','tags':[],'assignees':['Victor']})
        self.runner.run_once(); before=len(self.chats())
        self.submit({'ref':'GROUPOK12345','replyTo':self.G,'action':'confirm','answer':'yes','code':''})
        self.runner.run_once()
        self.assertEqual(self.store.get(row['id'])['state'],'pending')
        self.assertEqual(len(self.chats()),before)
    def test_private_yes_confirms_a_group_request(self):
        _,row=self.submit({'replyTo':self.G,'action':'create_task','title':'Deck','tags':[],'assignees':['Victor']})
        self.runner.run_once()
        self.submit({'ref':'PRIVYES12345','action':'confirm','answer':'yes','code':''})
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual(self.store.get(row['id'])['state'],'done')
    def test_bad_group_ids_are_rejected(self):
        for body in ({'replyTo':'x@g.us','action':'save_idea','title':'a','description':'b'},
                     {'replyTo':'123@c.us','action':'save_idea','title':'a','description':'b'},
                     {'replyTo':self.G,'messageId':'false_phone_GROUP1234567','freeText':True}):
            self.assertEqual(self.submit(dict(body))[0],400)
        self.assertEqual(all_actions(self.store),[])
    def test_mapped_group_uses_its_own_list(self):
        M='120363099999999999@g.us'
        _,row=self.submit({'replyTo':M,'action':'create_task','title':'Deck','tags':[],'assignees':[]})
        self.runner.run_once()
        self.assertEqual(self.store.get(row['id'])['state'],'done')
        self.assertEqual(self.runner.api.created[0]['list']['id'],'901')
        _,other=self.submit({'ref':'UNMAPPED1234','replyTo':self.G,'action':'create_task','title':'Deck','tags':[],'assignees':[]})
        self.runner.run_once()
        self.assertEqual(self.runner.api.created[1]['list']['id'],'1100310000198006')
    def test_members_without_username_do_not_break_assignment(self):
        # ClickUp returns username null for members who never set a name.
        self.runner.api.members=lambda list_id: [{'id':7,'username':None,'email':None},{'id':101,'username':'Victor Chandra','email':'victor@example.com'}]
        _,row=self.submit({'action':'create_task','title':'Deck','tags':[],'assignees':['victor','tifanny']})
        self.runner.run_once()
        self.assertEqual(self.store.get(row['id'])['state'],'pending')
        self.assertEqual(self.store.get(row['id'])['payload']['assigneeIds'],[101])
    def test_mapped_group_cannot_touch_another_lists_task(self):
        M='120363099999999999@g.us'
        _,row=self.submit({'replyTo':M,'action':'post_progress','task':'86abc123','update':'waiting'})
        self.runner.run_once()
        self.assertEqual(self.store.get(row['id'])['last_error'],'task_outside_scope')
        self.assertEqual(self.runner.api.comments,[])
    def test_private_yes_keeps_the_group_list(self):
        M='120363099999999999@g.us'
        _,row=self.submit({'replyTo':M,'action':'create_task','title':'Deck','tags':[],'assignees':['Victor']})
        self.runner.run_once()
        self.submit({'ref':'PRIVYES99999','action':'confirm','answer':'yes','code':''})
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual(self.runner.api.created[0]['list']['id'],'901')
    def test_adf_tag_routes_private_and_dotcross_requests(self):
        _,a=self.submit({'action':'create_task','title':'Deck','tags':[],'assignees':[],'workspace':'adf'})
        _,b=self.submit({'ref':'PRIVATE12345','action':'create_task','title':'Plain','tags':[],'assignees':[]})
        self.runner.run_once(); self.runner.run_once()
        self.assertEqual([t['list']['id'] for t in self.runner.api.created],['1100380000193567','1100310000198006'])
    def test_ai_workspace_routes_and_shows_list_in_preview(self):
        from worker import ADF_LIST_ID
        _,row=self.submit({'messageId':'false_phone_AIJOB1234567','freeText':True})
        self.runner.api.extract=lambda *a: None
        self.runner.run_once()
        token=self.store.get(row['id'])['token']
        self.assertEqual(self.post('/plan',{'jobId':row['id'],'token':token,'plan':{'action':'create_task','title':'Deck','description':'','assignees':[],'workspace':'adf'}})[0],200)
        self.runner.run_once()
        self.assertEqual(self.store.get(row['id'])['payload']['listId'],ADF_LIST_ID)
        self.assertIn('List: Ama Da Flow',self.chats()[-1][1])
    def test_paused_adf_falls_back_to_voice_inbox(self):
        import worker
        worker.ADF_PAUSED=True
        try:
            _,row=self.submit({'replyTo':'120363415330600046@g.us','action':'create_task','title':'Deck','tags':[],'assignees':[],'workspace':'adf'})
            self.runner.run_once()
            self.assertEqual(self.store.get(row['id'])['state'],'done')
            self.assertEqual(self.runner.api.created[0]['list']['id'],'1100310000198006')
        finally:
            worker.ADF_PAUSED=False


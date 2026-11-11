# Testing the WhatsApp Voice Inbox workflow

This guide checks the workflow end to end after a change or deploy. Part A uses a phone. Part B is for whoever runs the server. Part C covers the automated tests.

## Before you start

- Send the test messages from a number in `actions/people.json`. Messages from other numbers are ignored without a reply, which is a test of its own (B3).
- Send them in a **direct chat** with the pilot WhatsApp number, except the group tests in A6. In groups, only `task:`, `idea:`, `progress:` and yes/no/retry are read.
- Every test writes to the real [Voice Inbox list](https://app.clickup.com/1100310000034143/v/li/1100310000198006). Put "test" in each title so the tasks are easy to find and delete afterwards. The bot cannot delete tasks.
- Wait for each reply before you send the next message. A reply usually takes 5–20 seconds; voice notes take longer.

## Part A: from the phone

### A1. Commands with a prefix (no AI)

| # | Send | Expected reply | Pass if |
| --- | --- | --- | --- |
| 1 | `task: Test prefix task` | A link to the new task | The task appears in Voice Inbox |
| 2 | `task: Test assign @victor` | `Create task "Test assign" and assign …?` then `Reply yes or no within 15 minutes.` | Nothing is created until you reply |
| 3 | `yes` (after #2) | A link to the task | The task is assigned to the named person |
| 4 | `idea: Test idea bundle` | A link to the item | The item has the `idea` tag |
| 5 | `progress: <task link from #1> waiting for samples` | Confirmation that the comment was posted | The comment is on the task |
| 6 | `progress: <task link from #1> now is on progress` | Confirmation, status changed | The task status is `in progress` |
| 7 | `progress: <task link from #1> done` | `Post progress on "…" and mark it complete?` | The task stays open until you reply |
| 8 | `no` (after #7) | `Cancelled "…".` | The task is still open, with no new comment |
| 8a | `*task: Test bold*` with a link on a second line | A link to the new task | The title is "Test bold" and the link is in the task description |

### A2. Plain text (AI)

| # | Send | Expected reply | Pass if |
| --- | --- | --- | --- |
| 9 | `please create a task to test the A380 budget review` | `Create task "…"?` plus a short description | Nothing is created yet |
| 10 | `yes` | A link to the task | The task exists with a sensible title |
| 11 | `I have an idea, test a loyalty card for regulars` | `Save idea "…"?` | Saved after `yes` |
| 12 | `thanks, see you tomorrow` | **No reply** | No reply arrives within 2 minutes |
| 13 | `thanks` or `noted thanks` (one or two words) | **No reply** | No reply. Note: `ok`, `yes` and `no` are control words. With nothing waiting they reply `No matching request is waiting.` |

### A3. Voice notes (AI)

| # | Send | Expected reply | Pass if |
| --- | --- | --- | --- |
| 14 | A voice note: "create a task to test the supplier call on Friday" | A preview that ends with `Reply yes or no within 15 minutes.` | The preview matches what you said |
| 15 | `yes` | A link to the task | The task exists |
| 16 | A voice note with small talk only ("hi, just checking in") | No reply, or a short request to clarify | Nothing is created |

### A4. Confirmation edge cases

| # | Do this | Expected |
| --- | --- | --- |
| 17 | Send two requests that need confirmation (e.g. #2 twice with different titles), then send `yes` | A reply listing both requests, each with a 10-character code |
| 18 | Send `yes <code>` using one code from #17 | Only that request is created; the other is still waiting |
| 19 | Send a request that needs confirmation and wait 16 minutes, then send `yes` | `No matching request is waiting. Please send the request again.` |
| 20 | Reply `yes please` to a preview | Ignored: no reply, and the request expires. Known limit: only single words like `yes`, `ok`, `ya`, `iya` are accepted |

### A5. Messages that must be ignored

| # | Do this | Expected |
| --- | --- | --- |
| 21 | In a group, send `hello team, test the budget` or `yes` | No reply, no task |
| 22 | Ask someone who isn't in `people.json` to send `task: Test stranger` | No reply, no task |
| 23 | Send only a link, e.g. `https://example.com` | No reply |

### A6. Group chats

Use a group that both you and the pilot number are in. Replies go to the group the request came from.

| # | Send in the group | Expected | Pass if |
| --- | --- | --- | --- |
| 24 | `task: Test from group` | The task link, posted **in the group** | The task exists |
| 25 | `task: Test group assign @victor` | A preview in the group | Reply `yes` in the group. The task link follows in the group |
| 26 | `idea: Test group idea` | A link in the group | Saved with the `idea` tag |
| 27 | `ok` in the group, with nothing waiting from that group | **No reply** | The bot stays silent |
| 28 | Make a request in your private chat, then send `yes` in the group | **No reply** | The private request still waits. Confirm it in the private chat |
| 29 | A voice note, or a plain request without a prefix | No reply | Groups never go to the AI |
| 30 | Someone not in `people.json` sends `task: Test stranger` | No reply | No task |

## Part B: on the server

These steps are read-only. They show field names, states and counts, never message text.

### B1. Deploy is healthy

```bash
ssh root@naspad-server 'curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:5678/webhook/waha-voice-inbox-pilot; docker inspect -f "{{.State.Health.Status}}" adfn8n-actions-1'
```

Pass: `403` (the intake refuses unauthenticated calls) and `healthy`.

### B2. What happened to the last messages

```bash
ssh root@naspad-server 'docker exec adfn8n-actions-1 python -c "
import sqlite3
d=sqlite3.connect(\"file:/data/actions.sqlite3?mode=ro\",uri=True)
for r in d.execute(\"select substr(id,1,10),kind,state,stage,attempts,coalesce(substr(last_error,1,60),\x27-\x27),round((strftime(\x27%s\x27,\x27now\x27)-updated)/60) from actions order by created desc limit 10\"): print(*r)
print(\"unsent replies:\",d.execute(\"select count(*) from outbox where sent is null\").fetchone()[0])"'
```

Each row shows: code, `kind`, `state`, stage, attempts, last error, and minutes since the last update.

Read the newest rows first:

| Test | Expected `kind` / `state` |
| --- | --- |
| Prefix task (#1) | `create_task` / `done` |
| Waiting for yes/no (#2, #9, #14) | `create_task`, `save_idea` or `post_progress` / `pending`, then `done` after `yes` or `cancelled` after `no` |
| Your `yes` or `no` reply | A separate `confirm` / `done` row |
| Plain text or voice still being read by the AI | `voice` / `extracting`. If it stays there, check `last_error` |
| Casual chat (#12, #16) | `ignore` / `done`, with no reply sent |
| Expired (#19) | `expired` |
| Group chat without a prefix, stranger, link, one- or two-word chat (#13, #21–23, #29, #30) | **No new row** |

`unsent replies` should return to `0` within a minute. If it stays above zero, WhatsApp delivery is failing.

### B3. Ignored senders don't make WAHA retry

An ignored message must still get HTTP 200. Otherwise WAHA retries it 8 times. A row count that stays the same after tests #21–23 confirms this.

## Part C: automated tests

Run these on your machine after any code change, before deploying:

```bash
node tests/voice-pilot.selftest.mjs
```

```bash
python3 -m unittest discover -s actions -p 'test_*.py'
```

The Node self-test also checks that `people.json`, the intake list and the reply allow-list contain the same WhatsApp IDs.

## Cleanup

Delete every task with "test" in its title from Voice Inbox in ClickUp. The bot cannot delete tasks.

## Troubleshooting

| Symptom | Likely cause | Check |
| --- | --- | --- |
| No reply to anything | n8n or the worker is down | B1 |
| No reply to one new person | Their phone or LID is missing from one of the three lists | Node self-test, and `people.json` on the server |
| Prefix commands work, plain text and voice don't | Orvix or Whisper is failing | B2: rows stuck in `voice` / `extracting` with a `last_error` |
| A preview arrives but `yes` does nothing | The reply had more than one word, or 15 minutes had passed | Send the request again |
| `task:` works in a direct chat but not in a group | WAHA reported the group sender in an unexpected form | Tell whoever runs the server. The intake reads the sender from `participant` |
| A reply arrives twice | WhatsApp delivery timed out and was retried | Known and rare. No action needed |

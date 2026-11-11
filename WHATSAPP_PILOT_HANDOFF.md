# WhatsApp voice pilot handoff

Updated on 2026-11-09 after the gateway body fix, 200-on-ignore intake, hidden confirmation codes and plain-text AI requests. See "Changes on 2026-11-09" below.

## Current deployment

The workflow is published on `naspad-server`, under `/opt/adfn8n`. Its ID is `waTextPilot26Nov6`. The local workflow export is `whatsapp-voice-pilot.json`. The editor is available at [n8n](https://n8n.naspadstudio.id/workflow/waTextPilot26Nov6).

[Voice Inbox in ClickUp](https://app.clickup.com/1100310000034143/v/li/1100310000198006) has List ID `1100310000198006`. All existing pilot members retain access to this list, as explicitly approved. Their phone and LID aliases and permitted actions are configured in `actions/people.json`. The n8n intake and tool gateway also validate allowed senders. Update these together when adding or restricting a person.

The server runs n8n, WAHA, local Whisper and a new `actions` service. The actions service uses Python's standard library and SQLite, with one processing worker and a persistent outbound reply queue. Its data is in `/opt/adfn8n/actions-data/actions.sqlite3`. Its HTTP API is accessible only inside the Docker network.

Use all four Compose files for deployment.

```sh
cd /opt/adfn8n
docker compose -f compose.yaml -f compose.waha.yaml -f compose.voice.yaml -f compose.actions.yaml up -d
```

## Supported requests

| Request | Behavior |
| --- | --- |
| `task: Review the homepage` | Creates a task and replies with its link. |
| `task: Prepare the deck @victor` | Resolves the assignee and asks for confirmation. Unmatched names are disclosed. |
| `idea: Try a seasonal product bundle` | Creates a Voice Inbox item with the `idea` tag. |
| `progress: <task link or ID> Waiting for samples` | Adds a progress comment. |
| `progress: <task link or ID> now is on progress` | Posts the comment and sets `in progress`. |
| `progress: <task link or ID> done` | Asks for confirmation before posting and setting the closed `complete` status. |
| Voice note | Whisper transcribes locally, Orvix GPT-6 Sol extracts one action, and the service applies the same permissions and recovery rules. The extracted action is always previewed and needs yes/no before anything is written. |
| Plain text without a prefix (3+ words, not a bare link) | Sent through the same Orvix extraction as voice, without Whisper. Casual chat returns `ignore` and gets no reply. Any other action is previewed and needs yes/no. Shorter messages and bare links are ignored without an AI call. |
| `task:`, `idea:` or `progress:` in a group | The sender comes from `participant` and must be in `people.json`. Replies, including yes/no prompts, go to the group. A yes/no in a group only answers that person's requests from the same group; with none waiting, the bot stays silent. A private yes can still confirm a group request. Groups never reach the AI. |

Named tasks can be used in progress requests. Exact or unique whole-word matches resolve within Voice Inbox. Ambiguous names and missing details prompt a request for the task link and update.

Confirmation prompts end with "Reply yes or no within 15 minutes." and show no code. Bare yes/no applies when exactly one proposal is waiting for that person. If several are waiting, the reply lists each one's 10-character code and title, and `yes <code>` or `no <code>` picks one. Phone and LID aliases share the same identity. Multiple proposals remain separate. A retry preserves whether the original action was actually confirmed.

If a recoverable request needs attention, its reply gives a code for `retry <code>`. If an API write could have succeeded despite a timeout, the system checks ClickUp reference markers first. After unsuccessful reconciliation, it asks the sender to check ClickUp before explicitly retrying. Status conflicts require a fresh request.

## Workflow structure and credentials

1. `Receive WAHA message` authenticates the event. `Validate test message` filters senders and parses text commands or voice references. `Persist incoming action` saves the action before the intake webhook acknowledges it.
2. The worker dispatches voice jobs to `waha-voice-action-worker`. The existing authorized-media validation, Whisper transcription, business context and Orvix extraction nodes run in n8n. Their resulting action is persisted through `/plan`. Failures are reported through `/failure`.
3. The worker makes ClickUp and WhatsApp requests through `waha-action-tool`. This authenticated gateway uses the existing n8n credentials. Allowed operations are bounded, task operations recheck Voice Inbox membership, and outbound messages are limited to pilot sender IDs.
4. The service checkpoints task creation, comment posting and status changes. Its unique action key deduplicates message deliveries. A completed action stays completed on replay. Replies are queued separately, so a delivery retry does not rerun a ClickUp action.

The actions service reuses the existing `/opt/adfn8n/.waha-key` through Compose. ClickUp credentials stay in n8n. Automatic approval review rejected an earlier plan to export decrypted credentials to temporary files, and the deployed gateway avoids that export.

All three production webhook paths are explicit.

- `waha-voice-inbox-pilot`
- `waha-voice-action-worker`
- `waha-action-tool`

WAHA session `default` remains configured for the `message` event with authenticated delivery. Delivery retries use exponential backoff, starting at 3 seconds, with 8 attempts. Its full existing session configuration was preserved.

## Recovery and privacy

- Confirmations and their notifications commit in one SQLite transaction. Applying a yes/no and consuming that control message also commit together.
- Known transient errors retry with bounded backoff. Write attempts retain their retry counts. Voice dispatch leases last 10 minutes, and stale callback tokens are rejected.
- Comment retries search paginated ClickUp comments for the message reference. Legacy task and comment markers remain recognised.
- If a comment was saved but its status update failed, recovery resumes from the status step and reports partial success.
- Existing task status is checked before changing it. If another person changed it since the request, the service asks for a fresh request.
- Future-tense text such as “will mark it in progress tomorrow” remains a comment. Voice extraction also instructs the model to exclude future plans and partial completion from status changes.
- The service stores message references and proposed/final action fields. Audio and complete transcripts are not submitted to its database. n8n execution payload saving remains disabled. WAHA's audio cache uses tmpfs with a 180-second lifetime.
- Pending proposal payloads and their queued prompts are removed when they expire after 15 minutes. Finished action details, attention payloads and reply content are cleared after 30 days. Minimal hashed deduplication tombstones remain. Cleanup runs in the worker loop.
- Transcripts still go to Orvix for interpretation. Its retention policy has not been verified.

Remote APIs impose limits. WhatsApp delivery acknowledgements can be uncertain, so a rare timeout can still produce a duplicate reply. ClickUp status updates lack an atomic compare-and-set operation. The scope/status rechecks reduce races with manual edits, but cannot remove the interval between checking and writing. Long outages before intake persistence can exceed WAHA's retry window and require a resend.

## Verification and rollback

Run these from the local workspace.

```sh
node tests/voice-pilot.selftest.mjs
python3 -m unittest discover -s actions -p 'test_*.py'
```

The Python suite includes a temporary localhost HTTP server, which requires network permission in a restricted sandbox.

Verification performed during deployment includes concurrent intake, replay protection, multi-request confirmations, phone/LID identity, cancellation/expiry, crash rollback, retry budgets, uncertain write reconciliation, partial status failure, scope changes, callback tokens and reply recovery. Read-only ClickUp and WAHA calls through the real n8n gateway succeeded. Disallowed gateway operations were rejected. An isolated future-dated test record survived an actual container restart and was then removed. The published nodes, connections and settings were compared with the tested export.

A fresh real WhatsApp voice note and task/idea/progress requests are still needed to verify the entire live user round trip after this deployment. Synthetic tests exercised writes against a fake provider.

The original workflow backup is `/opt/adfn8n/backups/voice-before-recovery-20261107.json`. Back up the actions database using SQLite's backup API while the worker is running. If rolling back n8n, stop the actions worker first and review outstanding queue entries before resuming the old workflow. The old workflow does not consult the new action ledger.

## Changes on 2026-11-09

- **Gateway body fix.** n8n HTTP Request 4.2 silently drops `specifyBody`/`jsonBody` when `sendBody` is an expression. Before this fix, the tool gateway sent no body on POST/PUT, so no ClickUp write or WhatsApp reply had worked live. Each gateway is now split by `ClickUp write request`/`WAHA write request` into a GET node and an `Execute … write` node with a literal `sendBody: true`. The self-test rejects expression-valued `sendBody`.
- **Ignored messages answer 200.** `Validate test message` returns `{ignored: true}` instead of nothing, and `Message accepted` routes it to the no-op `Ignore message`. This stops WAHA retrying every non-pilot message 8 times. `alwaysOutputData` did not work for this.
- **Plain-text AI requests.** Text jobs reuse the voice ledger kind with `freeText: true` and store only the message ID. In n8n, `Text job` routes them to `Request message text` → `Use message text` instead of audio and Whisper. Orvix can return `ignore`, which ends silently. Text jobs send no delay notices, only the final failure notice.
- **Live verification.** A `task:` create, a progress update with confirmation, and the rejection cases passed on the live system. Plain-text requests and voice notes have not been tested live since these changes.
- **Verifying a deploy.** Read `workflow_history` at `activeVersionId` in `/home/node/.n8n/database.sqlite` (the n8n container has the sqlite3 node module) and diff it against the repo export. Backups from today are in `/opt/adfn8n/backups/` with the `-20261109` suffix.
- **Two more pilot numbers.** `6281510174878` (LID `22652362195020`) and `6282113099490` (LID `104419446239310`) have the same three actions as the others. They were added to `people.json`, the intake list and the gateway's reply allow-list. The Node self-test now fails if these three lists differ. Backups: `people-before-2new-20261109.json` and `voice-before-2new-20261109.json`.
- **Third new number.** `6281264322144` (LID `88042584932494`) was added the same way. Backups: `people-before-3rdnew-20261109.json` and `voice-before-3rdnew-20261109.json`.
- **Testing guide.** See `docs/WHATSAPP_TESTING_GUIDE.md` for phone tests, read-only server checks and cleanup.
- **Group chats.** `Validate test message` reads the group sender from `participant` (or `author`) and takes the message key from `false_<group>@g.us_<key>[_<participant>]`. Only prefix commands are accepted, and the reply goes to the sender's private chat, so the reply allow-list needs no group IDs. A stranger's `task:` and a member's casual text in a synthetic group message both returned 200 ignored, with no ledger row. WAHA used to drop every group message before it reached n8n (`WAHA_SESSION_CONFIG_IGNORE_GROUPS=true`). It is now `false` in `compose.waha.yaml`, so every group message reaches the intake and is ignored there unless it is a prefix command from a pilot member. Backup: `compose.waha-before-groups-20261109.yaml`. A real `task:` sent in a group on 2026-11-09 created the task and replied in the sender's private chat. WAHA prints a generated Swagger password to its log on every start because none is configured. Swagger is disabled and the port is bound to loopback, so it is harmless, but setting `WHATSAPP_SWAGGER_PASSWORD` in `.waha.env` would stop it. Backup: `voice-before-groups-20261109.json`.
- **Group replies.** Intake sends the group as `replyTo`. The worker stores it as the action's `chat`, so replies go to the group, and looks the sender up by person ID instead of by chat. The gateway may send to any `<digits>@g.us` group the number is in, as well as to pilot members. Backups: `worker-before-groupreply-20261109.py` and `voice-before-groupreply-20261109.json`.
- **Formatting and multi-line tasks.** WhatsApp formatting (`*`, `_`, `~`) around `task:`, `idea:` or `progress:` no longer hides the prefix. Previously `*task: …*` was silently ignored. In `task:`, the first line is the title and further lines become the task description, so a pasted link no longer pushes the title past 200 characters. Backup: `voice-before-formatting-20261109.json`.

## One ClickUp list per WhatsApp group (2026-11-10)

Each group can send its requests to its own ClickUp list. Private chats and unmapped groups still use Voice Inbox (`CLICKUP_LIST_ID`). The list is fixed when a request arrives, so a private `yes` to a group request still writes to the group's list. A group can only create, find and update tasks in its own list.

To add a group:

1. Find the group ID on the server: `. /opt/adfn8n/.waha-key; curl -s -H "X-Api-Key: $WAHA_API_KEY" http://127.0.0.1:5679/api/default/groups | python3 -c 'import json,sys; [print(g.get("id",{}).get("_serialized", g.get("id")), g.get("subject") or g.get("name")) for g in json.load(sys.stdin)]'`
2. Find the list ID in the list's ClickUp URL (`.../v/li/<listId>`). Dotcross lists use the n8n credential `ClickUp account`; Ama Da Flow lists use `ClickUp ADF` and must also be added to `ADF_LISTS` in `Validate tool request`. Since the split, an Ama Da Flow group also goes in `ADF_GROUPS` in `Validate test message` of both workflows, and its list goes in `LISTS` of the Ama Da Flow gateway. A Dotcross list goes in `LISTS` of `whatsapp-voice-dotcross.json`.
3. Add it to `actions/groups.json`, for example `{"120363012345678901@g.us": "901234567890"}`.
4. Add the same list ID to `const LISTS = [...]` in `Validate tool request`. `node tests/voice-pilot.selftest.mjs` fails until these lists match.
5. Deploy `actions/groups.json`, `actions/worker.py`, `compose.actions.yaml` and the workflow. Then run `docker compose ... up -d actions` and use the n8n import → publish → restart steps.

Group senders must still be in `people.json`.

Current mapping: ghibah nusantara, AmaDaFlow MARKETING team, Website + Ai and ADF - team workflow use Ama Da Flow (`1100380000193567`, workspace `1100380000030289`). IJV (formerly Test) uses `1100310000205713`. DotCross and private chats use Voice Inbox.

**#adf override.** In any chat, `#adf` anywhere in a message sends it to Ama Da Flow (`CLICKUP_ADF_LIST_ID`), and the tag is removed from the text. For voice notes and plain text, the AI also returns `"workspace":"adf"` when the speaker says the request is for Ama Da Flow. AI requests are always previewed, and the preview shows `List: Ama Da Flow`. Without `#adf`, progress on an Ama Da Flow task link from a Voice Inbox chat is rejected with a hint to add `#adf`.

**Ama Da Flow pause (2026-11-10).** `CLICKUP_ADF_PAUSED` in `compose.actions.yaml` sends the ADF groups and `#adf` requests to Voice Inbox when `"true"`. It was on while the Dotcross token could not reach workspace `1100380000030289`, and was turned off (`"false"`) the same day once the separate `ClickUp ADF` credential was added. Flipping it needs only `up -d actions`.

**One ClickUp key per workspace (2026-11-10).** Every ClickUp call from the worker names its list (`list` in the gateway request). `Validate tool request` rejects calls without an allowed list, requires `/list/<id>/...` paths to match it, and sets `adf` when the list is in `ADF_LISTS`. `Read tool task scope`, `Execute ClickUp tool` and `Execute ClickUp write` each sit behind an `<name>: ADF?` IF with an `(ADF)` twin that uses the `ClickUp ADF` credential (the Ama Da Flow login's token). `Verify tool task scope` now requires the task to be in exactly the requested list, so one workspace's key never touches the other's tasks. Deploy the worker before the workflow: the old gateway ignores the extra `list` field, but the new one rejects requests without it.

**Members without a ClickUp name (2026-11-10).** ClickUp returns `username: null` for members who never set a name. Assignee matching crashed on that (`processing_error`, "Request … is delayed"), which hit every `@name` create in Ama Da Flow. Matching now treats a missing name or email as empty. Backup: `worker-before-nullname-20261110.py`.

**Group members registered (2026-11-10).** Every member of the five mapped groups was added with all three actions: `19173408218`, `34610210629`, `5214777041441`, `6281994770520`, `6282359361110` and `6285161912580`, with their LIDs from WAHA `GET /api/default/groups/<id>@g.us/participants/v2` (each entry has `id` = LID and `pn` = phone). The bot's own number `6281119903888` is excluded. People who join later still have to be added by hand. Backups: `people-before-groupmembers-20261110.json` and `voice-before-groupmembers-20261110.json`.

**Split into Ama Da Flow and Dotcross (prepared 2026-11-11, not deployed).** `whatsapp-voice-pilot.json` is now the `Ama Da Flow` workflow. It keeps ID `waTextPilot26Nov6` and the three webhook paths, uses only `ClickUp ADF` for writes, and extracts with Claude Haiku 5.5 through the `Anthropic API (ADF)` Header Auth credential (`x-api-key`). The new `whatsapp-voice-dotcross.json` (`Dotcross`, ID `waDotcross26Nov11`) keeps Orvix and `ClickUp account`. Its paths end in `-dotcross`. WAHA must send every message to both intakes. Each intake keeps its own half using the same `ROUTE` rule: Ama Da Flow takes its four groups plus `#adf` from any chat, and Dotcross takes everything else (private chats, voice notes, IJV, DotCross, private `yes`/`no`). The worker sends ADF-list ClickUp calls and `#adf` AI jobs to the Ama Da Flow paths. Everything else, including all WhatsApp replies, goes to the Dotcross paths. The model no longer picks a workspace. Instead, Dotcross's `Check for Ama Da Flow` looks for "Ama Da Flow", "AmaDaFlow" or "ADF" in the transcript or text. On a match it calls the worker's `/handoff`, which marks the job `adf` and reruns it on the Ama Da Flow workflow: Whisper runs again there, Haiku extracts, and the transcript is never passed between workflows. When paused or not allowed, `/handoff` answers `handoff:false` and Dotcross continues with Orvix. **Never Ama Da Flow:** the IJV group (`CLICKUP_NO_ADF_GROUPS`) and people with `"noAdf": true` in people.json (currently `6281264322144`). Their `#adf` is dropped and they get no hand-off. A noAdf person's messages in Ama Da Flow groups are ignored. The intakes and `Check for Ama Da Flow` hold copies of both lists, and the self-test checks that they match. `Read knowledge page` in Ama Da Flow still reads the Dotcross knowledge doc with `ClickUp account`. Deploy order:
1. Create the Anthropic credential. Back up the live workflow on the server. After importing Ama Da Flow, select that credential on `Extract action with Claude Haiku 5.5`. The file holds a placeholder ID, and an unmatched credential silently fails every #adf AI job.
2. Import and publish Dotcross.
3. Add a second session webhook to `waha-voice-inbox-dotcross` with the same headers as the first. Duplicate intakes are harmless, because `submit` ignores a repeated person+reference.
4. Run `up -d actions`.
5. Import and publish Ama Da Flow, then restart n8n.

Self-test: `node tests/voice-pilot.selftest.mjs` covers both files.

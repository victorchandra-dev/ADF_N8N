# WhatsApp recovery implementation plan

The approved flow review in this chat defines the scope. Preserve current Voice Inbox access for all existing pilot members, as explicitly requested.

Use n8n for authenticated event intake and voice transcription/extraction. Use a Python standard-library service with SQLite and a single worker for persistent actions, confirmations, ClickUp writes and an outbound reply queue. Audio and transcripts remain transient in n8n. Persist only message references, processing metadata and proposed/final action fields.

- [x] Add regression tests for concurrent intake, duplicate status events, confirmation replacement/expiry/identity, partial writes, uncertain write reconciliation, future wording, text ideas and reply recovery.
- [x] Implement the service in `actions/worker.py`, with per-person identity and permissions in `actions/people.json`. Use a unique action key, durable checkpoints and an outbox. Existing reference markers remain compatible with older tasks/comments. Revalidate scope before writes.
- [x] Integrate the existing n8n workflow with durable intake and a separate authenticated voice-processing webhook. Keep its credentials, media validation, Whisper and Orvix nodes. The intake webhook acknowledges after persistence. Report extraction failures to the action service.
- [x] Add `compose.actions.yaml`, deploy on naspad-server with restrictive credentials and a persistent volume, and configure WAHA delivery retries. Preserve pending confirmations during migration.
- [x] Run unit/regression tests, exercise the real n8n HTTP nodes against synthetic jobs without WhatsApp delivery, verify restart recovery and publish the workflow after a backup. Review the final implementation and update the handoff.

Review focus includes ambiguous API timeouts, status changes by another user, simultaneous confirmations from phone/LID aliases, sensitive retention and downtime during deployment. Completion requires reporting any remaining uncertainty in delivery or provider behavior.

Implementation decisions and review fixes are recorded in WHATSAPP_PILOT_HANDOFF.md. Automatic approval review rejected credential export. The final architecture keeps ClickUp credentials in n8n and uses a bounded authenticated tool gateway. Independent review found confirmation, crash, retry-budget, callback-token and timeout issues, all covered by regression checks after correction. Live user-message round-trip verification remains a follow-up.

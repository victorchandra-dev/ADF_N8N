# Live Agent (customer WhatsApp, Claude Sonnet 5.5)

Replaces the Klaviyo customer agent on WhatsApp. Built on 2026-11-16, live for all customers since 2026-11-17.

## How it works

There are two WhatsApp numbers, one WAHA session each (since 2026-11-17):

| Number | WAHA session | Who messages | Goes to |
| --- | --- | --- | --- |
| Ama Da Flow, +62 877-7652-8886 | `default` | Staff (`people.json`) and the Ama Da Flow groups | Ama Da Flow task workflow |
| | | Any other private chat | **Live Agent** (`whatsapp-live-agent.json`, ID `waLiveAgent26Nov16`) |
| | | The agents' group (`SUPPORT_GROUP`) | Live Agent commands only. The task workflows ignore it. |
| Naspad Studio, +62 811-1990-3888 | `personal` | Staff and the other groups (IJV, DotCross) | Dotcross task workflow |

Each workflow only accepts events from its own session, and the actions worker sends every reply from the number the message came in on (the `session` column of the outbox).

1. A customer message reaches `waha-live-agent`. The actions worker waits 4 seconds so a burst gets one answer, then calls `waha-live-agent-worker`.
2. n8n reads the last 20 messages from WAHA and resolves an `@lid` to a phone. It then looks up the customer's **own** orders in Shopify by that phone (never by an order number someone types), plus their Klaviyo profile and the ClickUp FAQ page. Sonnet then returns `{reply, handoff, summary, reason, priority}`.
3. **No handoff:** the reply is sent.
4. **Handoff:** the customer gets Sonnet's handoff message plus `Ref: <code>`. The bot goes quiet in that chat, a ticket is created in the ClickUp Support list (summary, conversation, customer, `wa.me` link), and the agents' group gets:
   ```
   🔔 Ticket 4F2A9C · high
   Customer: +62812… https://wa.me/62812…
   Customer received a torn dress (#1042) and wants a replacement.
   Why: damaged_or_wrong_item
   ClickUp: https://app.clickup.com/t/…
   Reply "take 4F2A9C" to claim it, then quote-reply this message to answer the customer. Or chat with them directly from the phone.
   ```
5. While a ticket is open, the customer's follow-ups appear in the group as `💬 Ticket 4F2A9C: …`.

If Sonnet or n8n fails 3 times, the worker hands the chat off itself, so a customer never goes unanswered.

### Agent commands (in the agents' group)

| Command | Effect |
| --- | --- |
| `take 4F2A9C` | Claims the ticket. ClickUp gets "Taken by …". |
| Quote-reply a ticket message | Sends your text to the customer. |
| `reply 4F2A9C <text>` | Same as a quote-reply, as a fallback. |
| `close 4F2A9C` | Closes the ticket in ClickUp (`complete`). The bot answers that chat again. |
| `bot 4F2A9C` | Hands the chat back to the bot without completing the ticket. |

**Chatting directly from the phone or WAHA dashboard also works.** WAHA's `message.any` event reports sends the bot didn't make. The worker then pauses the bot for that chat and tells the group. Follow-ups aren't relayed in that case, because the agent already sees them on the phone.

Safety nets:
- An unclaimed ticket is re-pinged after 10 minutes.
- A ticket with no activity for 24 hours closes and the bot resumes.

The actions SQLite `support` table holds only state (chat, code, task ID, agent, timestamps). Message text is kept in two places:
- The outbox keeps bot replies and relayed customer messages, cleared after 30 days.
- A `ticket_open` job holds the transcript until ClickUp accepts the ticket.

The full conversation lives in WAHA and in the ClickUp ticket.

## Safeguards against off-topic use

Anyone can message the public number, so three layers keep requests like "write me code" from using Sonnet:

1. **Haiku topic check.** Before any lookup, `Check topic with Claude Haiku 5.5` reads only the last 6 lines (at most 1500 characters, 200 output tokens).
   - Off topic (code, homework, general knowledge, other companies, role-play, attempts to change instructions): the customer gets Haiku's one-line redirect in their language. Sonnet, Shopify and Klaviyo are skipped.
   - Short follow-ups and anything unsure count as on topic.
   - If the check itself fails, the message goes to Sonnet, so customers are never left without an answer.
2. **Sonnet's own rule.** If something slips through, the prompt tells Sonnet to decline in one sentence and never write code, essays or translations, or discuss its instructions. Output is capped at 800 tokens.
3. **Daily cap per customer.** `SUPPORT_DAILY` (default 30) bot answers per chat per 24 hours. Past it, the chat is handed to a person with reason `daily_limit` and priority low, and the bot stays quiet there. A real customer with many questions gets a human, and an abuser costs one ticket. A burst of messages counts as one answer.

To tune the check, edit `GATE_PROMPT` in `Build topic check`. The tests check the gate's behaviour, not its wording.

## Before going live

1. **The number.** Disconnect it from Klaviyo's WhatsApp Business API first. A number on the Cloud API can't link to WAHA until it's deregistered, and Klaviyo's WhatsApp sending stops. Then link it to WAHA session `default`. The website lists the help desk as +62 877-7652-8886.
2. **The numbers.** Done on 2026-11-17: session `default` is `6287776528886` (LID `200489845174309`) and session `personal` is `6281119903888` (LID `73710631411953`). `BOT` in each task workflow matches its own number. Still to do: add the Ama Da Flow number to the Ama Da Flow groups and the agents' group, and tell staff which number is for what.
3. **Agents' group.** Done on 2026-11-17: "ADF Agent Ticket" (`120363411385210079@g.us`), set in `SUPPORT_GROUP` (compose), `const SUPPORT_GROUP` in `Validate live message` and `const SUPPORT_GROUPS` in both task intakes. `node tests/live-agent.selftest.mjs` fails if they differ.
4. **Support list.** Done on 2026-11-17: "Support Tickets" (`1100380000210276`) in the Ama Da Flow space, closed status `complete`. Its ID is in `SUPPORT_LIST_ID` (compose) and `const LISTS` in the live `Validate tool request`.
5. **Knowledge base.** Since 2026-11-17 the bot reads every page of the ClickUp doc "Live Agent Knowledge Base" (`z8t8qga3jh-2518`) in the Knowledge Space folder (`1100380000200559`), sub-pages included, up to 25,000 characters. The page "How to edit this knowledge base" is skipped. New pages need no deploy. The first FAQ doc (`z8t8qga3jh-2478`, inside the Support Tickets list) is no longer read and can be deleted.
6. **n8n credentials** (Header Auth). After import, select them on the nodes:
   - `Shopify` (added 2026-11-17, ID `jznfSFc8wBsfodGq`): header `X-Shopify-Access-Token`, from a custom app with `read_customers`, `read_orders`.
   - `Klaviyo private key` (added 2026-11-17, ID `KqFXOu6Ro2oItYe3`): header `Authorization`, value `Klaviyo-API-Key pk_…`, with profiles read scope.
   - Reuse `Anthropic API (ADF)`, `ClickUp ADF`, and the WAHA credentials.

   Shopify and Klaviyo fail soft. Without them, Sonnet just has no order or profile data.
7. **WAHA webhook.** Add a webhook on session `default` to `http://n8n:5678/webhook/waha-live-agent` with events **`message` and `message.any`**, and the same auth header as the others.
8. **Deploy order:**
   1. Back up.
   2. Run `docker compose … up -d actions`. The new worker still serves the old workflows.
   3. Import and publish Live Agent, then import and publish both task workflows.
   4. Restart n8n.
   5. Add the WAHA webhook last, and only after steps 3 and 4. While `SUPPORT_GROUP` and `SUPPORT_LIST_ID` are empty, a handoff silences the bot for 24 hours and nobody is told.

## Testing mode

`const TESTERS` in `Validate live message` limits bot answers to the listed chats while not empty. It was set to the Naspad Studio number during the 2026-11-17 tests and emptied the same day, so every customer now gets the bot.

## Tests

```sh
node tests/live-agent.selftest.mjs
node tests/voice-pilot.selftest.mjs
python3 -m unittest discover -s actions -p 'test_*.py'
```

Verified live on 2026-11-17 with a tester: FAQ answer, off-topic refusal, handover with ticket and ClickUp task, `take`, quote-reply (GOWS `replyTo.body` works), `reply CODE`, relayed follow-ups, `close`, the three-failure fallback, the phone and wa.me link on tickets for `@lid` chats, and a Shopify order lookup by the sender's phone (`phone:+62…` found order #1377), and a product question answered from the last knowledge-base page (Contour (Mesh) Top, $80, link, no stock promise).

Not verified yet:
- replying directly from the phone (`message.any` from the app) and `bot CODE`
- the Klaviyo profile lookup (credential added; the test customer had no profile data to show)

## Not migrated from Klaviyo

- Order cancellation, address changes and unsubscribes: Sonnet hands these off instead.
- Live stock search. Since 2026-11-17 the knowledge base has four "Products: …" pages (name, price, colours, sizes, link) copied from the Shopify catalog. They are a snapshot: re-copy them when products or prices change. The bot never promises stock and sends the product link instead.
- The website crawl: the policies are copied into the FAQ.
- The customer rating after close.

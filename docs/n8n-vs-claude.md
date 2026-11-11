# n8n + Orvix vs Claude — WhatsApp pilot (2026-11-11)

> **✅ Keep for now: n8n + Orvix.** It works, verified live on 2026-11-09/10. A rebuild saves almost nothing.
> **Next step (optional):** swap only the Orvix node for **Claude Haiku 5.5** if Orvix's data retention can't be verified, or if a test shows Haiku matches Orvix.

Volume: ~15 AI calls/day (~500/month). Prices assume 16,500 IDR per USD and ~2,800 tokens per call.

| Option | ~500/mo | 2,000/mo | 5,000/mo |
|---|---|---|---|
| **Orvix (flat) — keep** | **100k IDR** | **100k** | **100k** |
| Claude Haiku 5.5 | ~3k | ~13k | ~33k |
| Claude Sonnet 5.5 | ~66k | ~264k | ~660k |
| Claude Opus 5.5 | ~140–215k | ~530k+ | ~1.3M+ |

| | n8n + Orvix | Claude |
|---|---|---|
| Price | Flat IDR | Haiku cheaper (~$6/mo less); USD card |
| JSON output | Needs recovery code | Always valid JSON (structured outputs) |
| Privacy | Retention unverified | Published policy |
| Quality | Errors caught by the yes/no preview | Haiku untested on ID/EN voice notes |

**Don't remove n8n:** it saves no money and Whisper stays either way. The n8n gateway holds the ClickUp tokens and checks which list each group may write to; moving that into new Python code risks writes to the wrong list. That's 2–4 days of work to fix problems that are mostly solved.

_Not measured: no real-message quality test; token counts are estimates._

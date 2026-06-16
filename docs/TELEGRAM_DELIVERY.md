# Telegram Delivery — Operational Guide

Push-only delivery of operational digests and critical alerts to Telegram.

---

## What This Is

Telegram delivery sends operational summaries and critical alerts to a configured
Telegram chat. It is **push-only** and **advisory**. The system observes and
reports — you decide what to do.

What it is NOT:
- Not a chatbot. The bot does not respond to messages.
- Not a conversational agent. There is no command interface.
- Not an automation trigger. Receiving an alert does not cause the system to act.

---

## Bot Setup

1. Open Telegram and message `@BotFather`.
2. Send `/newbot` and follow the prompts to create a bot.
3. Copy the token — it looks like `123456789:ABCdef...`.
4. This token goes in `TELEGRAM_BOT_TOKEN` (see Configuration below).
   **Never commit it to version control.**

## Channel / Chat Setup

1. Create a private channel or use an existing chat/group.
2. Add your bot as an admin with "Send Messages" permission.
3. Get the `chat_id`:
   - For private chats: send a message to the bot, then call
     `https://api.telegram.org/bot<TOKEN>/getUpdates` to find the `chat.id`.
   - For channels: the chat_id is typically a negative number (e.g. `-1001234567890`).
4. This ID goes in `TELEGRAM_CHAT_ID`.

**Required bot permission:** "Send Messages" only.
No admin access, no read access to messages, no file upload needed.

---

## Configuration

All Telegram settings are in `.env`. Copy from `.env.example`:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_DAILY_DIGEST_ENABLED=true
TELEGRAM_CRITICAL_ALERTS_ENABLED=true
TELEGRAM_QUIET_HOURS_START=22:00
TELEGRAM_QUIET_HOURS_END=08:00
```

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_ENABLED` | `false` | Master switch — nothing is sent unless this is `true` |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Bot API token from BotFather |
| `TELEGRAM_CHAT_ID` | *(empty)* | Target chat, group, or channel ID |
| `TELEGRAM_DAILY_DIGEST_ENABLED` | `true` | Send daily digest at 08:00 UTC |
| `TELEGRAM_CRITICAL_ALERTS_ENABLED` | `true` | Send immediate critical alerts |
| `TELEGRAM_QUIET_HOURS_START` | `22:00` | No immediate alerts after this time (UTC) |
| `TELEGRAM_QUIET_HOURS_END` | `08:00` | No immediate alerts before this time (UTC) |

---

## Delivery Behavior

### Scheduled Deliveries

- **Daily digest:** 08:00 UTC every day (if `TELEGRAM_DAILY_DIGEST_ENABLED=true`)
  - System status, scan count, snapshot count, top recommendations, storage/scheduler summary
- **Weekly digest:** Mondays at 08:00 UTC (if daily digest enabled)
  - 7-day scan count, active vs resolved concerns, top persistent issues

### Immediate Alerts

Triggered when a critical condition is detected during a scan or self-check:
- Scheduler job degraded (5+ consecutive failures)
- Storage pressure critical
- Survivability check failure

### Routing Rules

| Severity | Routing |
|---|---|
| `critical` | Immediate (subject to quiet hours, rate limit, dedup) |
| `warning` | Next scheduled digest |
| `info` | Next scheduled digest |

---

## Quiet Hours

During the quiet window, no **immediate** critical alerts are sent. Alerts that
fire during quiet hours are **silently suppressed** (counted in delivery health
metrics, not queued). Scheduled digests are not affected by quiet hours.

Default quiet window: 22:00–08:00 UTC (10pm to 8am).

To disable quiet hours entirely, set both to the same value: `22:00`/`22:00`.

---

## Rate Limiting

Maximum 10 immediate alerts per hour. If this limit is reached, additional
immediate alerts are suppressed until the hour rolls over. Suppressions are
counted in delivery health metrics.

---

## Duplicate Suppression

If the same alert type fires again within 1 hour, the duplicate is suppressed.
This prevents alert storms from repeated scan failures. The first alert in a
1-hour window always goes through.

---

## Failure Behavior

Telegram delivery failures are:
- Logged at WARNING level
- Counted in delivery health metrics (visible via `/operations/selfcheck`)
- Surfaced in maintenance reports

They **never** cause:
- Scan failures
- Scheduler job failures
- Application crashes
- Retry storms (maximum 2 retries with 2-second delays)

If Telegram is unavailable (network outage, bot token revoked), the system
continues operating normally. Delivery resumes when Telegram is reachable again.

---

## Privacy Expectations

The bot token is:
- Stored only in `.env` (never committed to version control)
- Never logged, printed, or included in error messages
- Never exposed in API responses or reports

Message content contains operational metrics only:
- System status
- Scan/snapshot counts
- Recommendation summaries (titles only, no raw evidence)
- Storage and scheduler status

No LLM event content, no personal data, no secrets are sent via Telegram.

---

## Operational Expectations

- Messages are plain operational summaries, not raw JSON or full reports
- Each message answers: "What matters right now?"
- Messages are designed for mobile readability
- Maximum message length: 4000 characters (Telegram's limit is 4096)
- Large messages are truncated with a notice pointing to the full report

---

## Monitoring Delivery Health

Delivery metrics are tracked in-memory and exposed via:
- `GET /operations/selfcheck` — includes a "Telegram Delivery" check item
- Maintenance report — includes a "Telegram Delivery Health" section

Tracked metrics:
- Success count, failure count
- Quiet-hour suppression count
- Duplicate suppression count
- Rate-limit suppression count
- Average delivery latency (ms)
- Last failure error

---

## First-Time Setup Checklist

Use `scripts/reality_check.sh` to validate configuration and send a test message:

```bash
bash scripts/reality_check.sh
```

The script will:
1. Validate `.env` Telegram configuration
2. Send a test message to verify connectivity
3. Run a scan and generate a digest
4. Send the digest
5. Print an operational checklist

---

## Intentionally Not Implemented

- Command handling (no chatbot)
- Message history or read receipts
- Per-user filtering or routing
- Webhook mode (polling is simpler and sufficient for a single-operator VPS)
- Inline keyboard or action buttons
- File/document attachments

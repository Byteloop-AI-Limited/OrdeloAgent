---
status: accepted
---

# Pauses have a mandatory end and availability is computed from the clock

On Telegram a rider can be messaged at any time, so the daily WhatsApp shift question (needed only because of WhatsApp's 24-hour window) goes away for Telegram riders: they are on by default and step away with `/off` for 6 hours, 1 day or 3 days. Restaurant admins will switch their alerts off the same way. The owner required an end time on every pause so nobody forgets to come back, and the same mechanism for both audiences.

The obvious design sets `is_in_shift = false` and has a cron job set it back when the time is up. It was rejected because a missed, failed or mis-pointed run (the shared `ORDELO_APP_URL` has pointed at stale tunnels before) leaves a person switched off with nobody noticing, which is the very failure the end time was meant to prevent.

Instead a pause is a row in one channel-neutral table, `pauses` (`availability/pauses.sql`), with `audience` (`rider` | `rest_admin`), `principal` (the phone), optional `scope` (`rest_ref` for an admin) and a **mandatory** `ends_at`. Whether someone is paused is computed live by one SQL function, `is_paused()`: an open row whose `ends_at` is still in the future. Dispatch (`get_available_riders`) and, from phase R6, the restaurant alert destinations call it directly, so the moment the end time passes the person is available again with no job involved. A sweep, `job_pause_sweep()`, only closes expired rows and asks the app to send "your break ends soon" and "you're back on", marking each message only after a 2xx reply. A late sweep delays a message; it can never make availability wrong. Durations come only from `ordelo_config` (`PAUSE_DURATIONS_<AUDIENCE>`), so there is no open-ended pause; a second `/off` replaces the end time rather than stacking. A restaurant admin may not pause if that would leave the restaurant with no unpaused admin (phase R6).

Python reaches pauses only through `ordelo/pauses.py` (`pause`, `resume`, `current`), a deep module over three service-role RPCs; the bots' `/off`, `/on` and `/shift` handlers call it. WhatsApp riders keep the daily shift cycle unchanged; `is_in_shift` stays the WhatsApp mechanism and is not used for pauses.

Considered and rejected: flipping `is_in_shift` with a reset job (above); a per-audience table (two copies of the same rules); stacking extensions (surprising end times and no hard cap).

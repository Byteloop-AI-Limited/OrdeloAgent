---
status: accepted
---

# What a restaurant's silence means is decided in SQL, once

Web-only restaurants should not have unanswered orders auto-accepted: silence means decline, after a longer answer time, with more reminders and a countdown for the customer. The confirmation timeout already lived in `process_restaurant_confirmation()` (cron, every 10 seconds), which only marked the order `restaurant_timedout` and left Python to auto-accept it.

Rejected: letting the Python timeout handler read a new config key and decline. Two places would then know the timeout rules (the job that finds the overdue order, the handler that decides what it means), the order would sit in `restaurant_timedout` between the two steps, and a lost webhook would leave an overdue order undecided. Also rejected: a new status per policy, or a per-restaurant table of settings (columns instead of `ordelo_config` rows is not needed for two keys).

Instead one function, `restaurant_confirmation_policy(rest_ref)` (`restaurant_admin/restaurant_confirmation_policy.sql`), is the only reader of the timeout keys and returns `timeout_minutes` and `timeout_action`. The job calls it and, for a never-answered order with action `decline`, writes `auto_decline` and `status = 'declined'` in the same UPDATE. Python only does side effects, by reusing the decline handler (`timed_out=True`): refund, customer, then admins and ops. The customer order view reads the same function to show an absolute deadline, so the countdown cannot disagree with the job. The accept path is untouched, and an accepted order that never got a pickup time is always auto-accepted because somebody answered.

An order an admin accepted but gave no pickup time is never declined; it is timed out (default pickup time) 15 seconds after the accept. That grace is a constant in `process_restaurant_confirmation()`, not a config key: the owner decided on 17 Nov 2026 that it does not vary by restaurant, so do not add a key for it.

Configured auto-accept (`restaurant_master.auto_accept`) is a different thing: nobody is asked, so it never reaches the timeout and also suppresses prompts, reminders and the "No Rider Found" message. `docs/pickup_time_logic.md` has the three modes side by side.

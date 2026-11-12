# Voiceover handoff: Byteloop Riders films (riders, riders-30)

Written 2026-11-09 by the studio session. Script: Project doc `ordelo-studio/rider-film/SCRIPT.md` (approved wording). Timeline: `srt/riders.cues.srt`, `srt/riders-30.cues.srt` (one cue per scene, current script timings; placeholders until the takes exist).

## Voice
Same as the restaurant films, see `VOICE.md`: **Lily - Velvety Actress** (`pFZP5JQG7iQjIQuC4Bku`), `eleven_multilingual_v2`, stability 0.5, similarity 0.75, style 0.3, speed 1, speaker boost on, `mp3_44100_128`. Trim leading/trailing silence to about 0.2 s.

## TTS-only spellings (SRT and on-screen text keep digits)
- `0.7 miles` → "nought point seven miles"
- `£7` → "seven pounds"
- "Byteloop" as written (BYTE-loop).

## Time budget
Each scene stretches up to **1.4×** its current window to fit a longer take (motion plays slower); beyond that its last frame holds. `fits` = estimated take (15 chars/s) ≤ 1.4 × window.

## riders (62.43 s now)

| Cue | File | Window | Est. take | Fits | Text (TTS text if different) |
| --- | --- | --- | --- | --- | --- |
| 1 | `voiceover/riders/01-rider-welcome.mp3` | 5.0 s | 7.6 s | no (+0.6 s held) | Welcome to Byteloop Riders. Deliver for local restaurants and run every job from Telegram. No new app to download. |
| 2 | `voiceover/riders/02-rider-onboarding.mp3` | 11.0 s | 9.6 s | yes | To join, open our link and tap Share my phone number. Pick your town and vehicle, and once we activate your account, job offers start coming in. |
| 3 | `voiceover/riders/03-rider-alert-tone.mp3` | 6.5 s | 6.9 s | yes | First, give the bot its own alert sound, so you can tell a job apart from everything else on your phone. |
| 4 | `voiceover/riders/04-rider-job-alert.mp3` | 9.0 s | 8.6 s | yes | Every offer shows the distance and your pay. This one's 0.7 miles for £7. Miss it, and it pings you again until the job is taken.<br>TTS: "Every offer shows the distance and your pay. This one's nought point seven miles for seven pounds. Miss it, and it pings you again until the job is taken." |
| 5 | `voiceover/riders/05-rider-got-the-job.mp3` | 8.0 s | 8.3 s | yes | Accept, and the job is yours. Our AI assistant sends your pickup time and delivery instructions, and guides you step by step. |
| 6 | `voiceover/riders/06-rider-pickup-code.mp3` | 3.2 s | 6.5 s | no (+2.0 s held) | At the restaurant, type in the two-digit code they give you. A thumbs-up means you're good to go. |
| 7 | `voiceover/riders/07-rider-customer-code.mp3` | 3.8 s | 6.3 s | no (+1.1 s held) | At the door, ask the customer for their two-digit code. Thumbs-up, and the delivery's complete. |
| 8 | `voiceover/riders/08-rider-control-centre.mp3` | 11.0 s | 9.6 s | yes | Telegram is your control centre. Check your current job, past jobs, earnings and payout status, and switch job alerts off when you're off shift. |
| 9 | `voiceover/riders/09-rider-end-card.mp3` | 5.0 s | 3.9 s | yes | Byteloop Riders. Scan to join, and start riding this week. |

## riders-30 (30 s now)

| Cue | File | Window | Est. take | Fits | Text (TTS text if different) |
| --- | --- | --- | --- | --- | --- |
| 1 | `voiceover/riders-30/01-rider-welcome.mp3` | 3.0 s | 3.9 s | yes | Ride with Byteloop. Every job runs on Telegram. No new app. |
| 2 | `voiceover/riders-30/02-rider-onboarding.mp3` | 5.0 s | 5.5 s | yes | Tap our link, share your number, and once we activate you, offers start coming in. |
| 3 | `voiceover/riders-30/03-rider-job-alert.mp3` | 2.5 s | 0.9 s | yes | 0.7 miles, £7.<br>TTS: "Nought point seven miles, seven pounds." |
| 4 | `voiceover/riders-30/04-rider-got-the-job.mp3` | 4.0 s | 3.6 s | yes | Accept, and our AI assistant guides you to the pickup. |
| 5 | `voiceover/riders-30/05-rider-pickup-code.mp3` | 3.0 s | 3.2 s | yes | Type the restaurant's code, then the customer's. |
| 6 | `voiceover/riders-30/06-rider-customer-code.mp3` | 2.5 s | 1.8 s | yes | Thumbs-up, and you're done. |
| 7 | `voiceover/riders-30/07-rider-control-centre.mp3` | 6.0 s | 5.5 s | yes | Track your jobs, earnings and payouts, and switch alerts off when you're off shift. |
| 8 | `voiceover/riders-30/08-rider-end-card.mp3` | 4.0 s | 2.0 s | yes | Byteloop Riders. Scan to join. |

## Optional shorter lines (not approved; only if Lohith picks them)
| Film / cue | Approved | Shorter alternative | Est. |
| --- | --- | --- | --- |
| riders 1 | Welcome to Byteloop Riders. Deliver for local restaurants and run every job from Telegram. No new app to download. | Welcome to Byteloop Riders. Deliver for local restaurants, all from Telegram. No new app. | 5.9 s (fits 7.0) |
| riders 6 | At the restaurant, type in the two-digit code they give you. A thumbs-up means you're good to go. | At pickup, send the restaurant's code. Thumbs-up: good to go. | 4.1 s (fits 4.5) |
| riders 7 | At the door, ask the customer for their two-digit code. Thumbs-up, and the delivery's complete. | At the door, send the customer's code. Thumbs-up, and it's delivered. | 4.7 s (fits 5.3) |

## After the takes (studio session, skill `ordelo-studio-voiceover-cycle`)
1. Save one mp3 per cue with the file names above (riders-30 is recorded separately: its lines differ).
2. Update `voiceover/manifest.json` (`riders`, `riders-30`: real `audio_duration_s`, recomputed `audio_start_s` with 0.3 s gaps, drop `placeholder`).
3. Rewrite `srt/riders.cues.srt` / `srt/riders-30.cues.srt` with the real take lengths (cue i = scene i), then `node scripts/sync-cues.mjs`, `node scripts/sync-voiceover.mjs` (cloud copy), `npm run srt`.
4. Do **not** run `sync-cues` before the real takes exist: the placeholder cue files would switch the films to cue mode (the end card would gain 12 frames).
5. Check `srt/<film>.report.txt`, locate words with `silencedetect`, retime only the named beat constants at the top of each scene file, republish the preview, stop for sign-off.

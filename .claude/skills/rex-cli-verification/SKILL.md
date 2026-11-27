---
name: rex-cli-verification
description: Set up and reuse Rex tabs and panes for Ordelo verification, owner approvals, and compact log evidence. Use when coordinating a verification run in Rex or preparing an owner-run Claude Code pane.
---

# Rex CLI for Ordelo verification

Use one named tab for the verification run in the session the owner is viewing. Keep the service panes available for log reads. Rex calls tabs windows and panes blocks.

## Find and reuse the targets

```zsh
REX=$(command -v rex) || REX="/Applications/Rex.app/Contents/Helpers/Rex Server.rex/Contents/MacOS/rex"
"$REX" ls --json | jq -c '.sessions[] | {label, session_id}'
"$REX" block ls -s "$services_session" --json
```

Set `services_session` to the session that runs the services, typically `RunServices`. Identify the backend and frontend blocks by process or startup output. If the named session is absent, confirm the Rex connection and where the services are running before choosing a target. Use the embedded CLI guide (`"$REX" __internal skill`) or command-specific `--help` when flags vary by version.

Keep the full session, window and block IDs from the first discovery or creation call. Pass `-s` and `-b` explicitly from shells outside Rex. Refresh IDs after a reconnect, a missing target or uncertain creation, then use the verified IDs for the rest of the run.

## Set up approvals

Set `verification_session` to the selected session ID and `project_dir` to the checkout for the step. Reuse the existing verification tab if it belongs to this run.

```zsh
created=$("$REX" window new -s "$verification_session" verify-all -c "$project_dir" --json)
printf '%s\n' "$created" | jq -e '{window_id, approval_block: .block_ids[0]}'
```

Keep the approval prompt in a shell so it can resume if the prompt exits. For a separate work pane, anchor the split to the saved approval block and keep focus on the prompt:

```zsh
"$REX" split -s "$verification_session" -b "$approval_block" --split=right --focus=false --json |
  jq -e '.block_ids[0]'
```

- Show one step at a time with the exact action, target and restoration command when applicable. The owner types `yes` in that pane. Treat `no` as a stop and re-prompt after unrelated input.
- Confirm the current step's answer from the pane or a run-specific approval file before acting. If the prompt exits, show the first unanswered step again. The coordinator never types the owner's answer.
- When a Rex call times out, inspect the session or foreground process before resending a command or creating another tab.

## Keep captures small

Filter output in the shell before returning it to the conversation. Use the process method for liveness or exit status, a short report for a completed run, and captures for the current approval or a specific timestamp, order number or hook. Keep full transcripts and verbose test output in private scratch files if needed for diagnosis.

```zsh
"$REX" block call -s "$verification_session" -b "$approval_block" process
"$REX" capture -s "$verification_session" -b "$approval_block" --trim --unwrap | tail -n 20
"$REX" capture -s "$services_session" -b "$backend_block" --trim --unwrap |
  rg -F -- "$evidence_marker" | tail -n 8
```

`--unwrap` keeps order numbers and URLs searchable without merging separate log records. Read session inventory only when a target changes. If opening a pane for a long task, pass a short prompt that points to the brief file and ask for a short report with the result, evidence and blockers.

## Prepare an owner-run Claude Code pane

Ask the owner which model to use before preparing a launch. Offer **Opus 5.5** or **Sonnet**, confirm the selected model identifier or alias in their Claude Code environment, and use medium effort. If the chosen model is unavailable, report it and wait for their choice.

The owner supplied this Opus command for manual use with explicit approval of the permission mode:

```zsh
claude --permission-mode bypassPermissions --model claude-opus-5.5 --effort medium
```

For Sonnet, substitute the owner's confirmed Sonnet identifier or alias. The command's permission mode applies to Claude Code. Owner approval for each live database or routing action still happens in the verification pane. Follow the host's delegation workflow when the user requests agent delegation.

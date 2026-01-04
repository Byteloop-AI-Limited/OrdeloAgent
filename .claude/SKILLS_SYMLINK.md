# Skills Directory Symlink

The `.claude/skills` directory is a symbolic link pointing to `.codex/skills`.

## Setup

```bash
ln -s ../.codex/skills .claude/skills
```

## Structure

```
.codex/skills/          # Source of truth
.claude/skills -> ../.codex/skills   # Symlink
```

## Purpose

This allows skills to be maintained in a single location (`.codex/skills`) while being accessible from both `.claude/skills` and `.codex/skills` paths.

## Created

2026-01-04

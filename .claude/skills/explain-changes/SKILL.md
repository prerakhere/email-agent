---
name: explain-changes
description: Before a commit, explain every changed or new file in plain English (what it is, why it changed), report test/lint status, and propose a commit message. Use when the user runs /explain-changes or asks what is about to be committed.
---

Goal: let a developer who is new to this stack understand exactly what will be committed, and approve it knowingly.

1. Run `git status --short` and `git diff HEAD --stat`, then read the actual diffs (and new untracked files that are not gitignored).
2. For EACH changed or new file, write 1-2 plain-English sentences: what the file is for and what changed/why. No jargon without a short definition.
3. Run `uv run pytest -q` and `uv run ruff check .` and report pass/fail in one line.
4. Flag anything surprising: files unrelated to the current task, anything that looks like a secret, very large changes, files that should be gitignored.
5. Check whether WORKLOG.md (and LEARNING.md if a concept was explained) were updated for this work; say so if not.
6. Suggest ONE atomic commit message (why, not what). If the changes mix unrelated ideas, suggest splitting into several commits and say which files go in each.
7. Do NOT commit. Wait for the user to approve.

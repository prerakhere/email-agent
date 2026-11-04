---
name: learn
description: Explain a concept (LangGraph, LangChain, LangSmith, Python, Azure, Claude Code...) and append it to LEARNING.md. Use when the user says "/learn <topic>" or asks to note something in the learning file.
argument-hint: <topic>
---

Topic: $ARGUMENTS

1. Explain the topic to the user in chat: concise, concrete, aimed at someone new to it.
2. Append a new section to the END of `LEARNING.md` (gitignored, never commit it). Number it after the last
   existing `## N.` heading. Contents: what it is, why it matters, a tiny example, and
   "Where it shows up in this project" (tie it to the Gmail agent and the current phase).
3. Never rewrite earlier sections unless the user asks. Keep the section under ~25 lines.
4. If the topic depends on a version-specific API, say so and point to the official docs rather than guessing.

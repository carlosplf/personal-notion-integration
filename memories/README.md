# Memories folder

This folder stores persistent context for the Discord assistant.

## Required files

### `personal-assistant.md` (agent memory, required)
- Defines assistant behavior rules: tone, response style, priorities, and safety boundaries.
- This content is injected as agent-level context in every assistant request.

### `about-me.md` (user memory, required)
- Stores stable user profile information: work, preferences, priorities, routines, and personal context.
- This content is injected selectively when relevant to the current request.

## Optional files

You can add more `.md` files (for example: `work.md`, `research.md`, `family.md`, `health.md`).
The assistant can use them as additional user memory context when relevant.

## Guidelines

- Keep each file short, factual, and up to date.
- Do not store secrets (passwords, private keys, tokens).
- Use one topic per file for easier maintenance.

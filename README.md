# Personal Assistant :rocket:

![Personal Assistant Banner](./banner/personal-assistant-banner.png)

A personal digital assistant on Telegram to help with your daily routine across multiple domains: tasks, email, calendar, expenses, meals, fitness, news, and more.

Notion is one of the available connections, alongside OpenAI, Gmail, Google Calendar, and other assistant capabilities.

## What this project is

This bot centralizes personal productivity workflows in Telegram using conversational messages and LLM-powered tool-calling.

Current focus:
- Task capture and prioritization (Notion)
- Calendar summary and event creation (Google Calendar)
- Email management: send, search, read (Gmail)
- Expense, meal, and exercise tracking (Notion)
- Metabolism and fitness analytics
- News digests and contact search

## Architecture at a glance

Main modules:
- `run.py`: app entrypoint
- `telegram_bot.py`: Telegram bot client and message handlers
- `google_auth_server.py`: background HTTP server for Google OAuth2 callback
- `notion_connector/`: task, notes, expenses, meals, and exercises read/write integration
- `gmail_connector/`: Gmail auth and email sending/reading
- `calendar_connector/`: Google Calendar read/write integration
- `openai_connector/`: LLM prompts/parsing/summaries
- `assistant_connector/`: conversational agent runtime, tool registry, and SQLite memory
- `templates/`: email rendering templates
- `utils/`: logging, credential loading, timezone helpers

The conversational assistant is config-driven:
- Agent + tool catalog: `assistant_connector/config/agents.json`
- New tools can be added by declaring JSON metadata and implementing a Python handler.

## Setup

### 1) Python environment

```sh
python3 -m venv ./env
source ./env/bin/activate
pip install -r requirements.txt
```

### 2) Google credentials (Gmail + Calendar)

Follow the Google API quickstart to create OAuth credentials:
- https://developers.google.com/gmail/api/quickstart/python

Place `credentials.json` in the project root.

Google authentication is done **per-user via Telegram** using the `/google_auth` command (no manual `token.json` needed):
1. Send `/google_auth` in the bot chat.
2. Click the link, sign in with Google, and grant permissions.
3. The bot stores the token securely per user in the SQLite database.

### 3) Notion credentials

Notion credentials are configured **per-user via the bot** (not in `.env`). After starting the bot, send `/setup` or tell the bot `configure notion_api_key: secret_xxx`. See [User credentials](#user-credentials) below.

### 4) Configure `.env`

Create a `.env` at project root.

**Required to run the server:**

```env
# Telegram
TELEGRAM_BOT_TOKEN="your_telegram_bot_token_here"           # required — get from @BotFather
TELEGRAM_ALLOWED_USER_IDS="123456789"                       # required — comma-separated Telegram user IDs
CREDENTIAL_ENCRYPTION_KEY="..."                             # required — generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# OpenAI
OPENAI_KEY="sk-..."

# Google OAuth (for Gmail + Calendar)
GOOGLE_OAUTH_CALLBACK_URL="https://yourdomain.com/auth/google/callback"  # public URL for OAuth redirect
GOOGLE_AUTH_SERVER_PORT="8080"                              # port for the local OAuth callback HTTP server
```

**Optional server-level defaults** (can be overridden per-user via `/setup`):

```env
LLM_MODEL="gpt-4.1-mini"                                   # LLM model for the assistant
TIMEZONE="America/Sao_Paulo"                                # timezone for dates and scheduled tasks
LOG_PATH="."
API_DAYS_TO_CONSIDER="0"                                    # includes overdue + next N days in task queries
AUDIO_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe"             # model used to transcribe voice messages
```

**Optional assistant tuning:**

```env
ASSISTANT_AGENT_ID="personal_assistant"
ASSISTANT_MEMORY_PATH="./assistant_memory.sqlite3"
ASSISTANT_MAX_MESSAGES_PER_SESSION="300"
ASSISTANT_MAX_TOOL_CALLS_PER_SESSION="300"
ASSISTANT_MAX_STORED_MESSAGE_CHARS="4000"
ASSISTANT_MAX_STORED_TOOL_PAYLOAD_CHARS="12000"
ASSISTANT_MAX_HISTORY_CHARS="12000"
ASSISTANT_MAX_TOOL_OUTPUT_CHARS="8000"
```

> **Note:** Notion and email variables (`NOTION_API_KEY`, `NOTION_DATABASE_ID`, `EMAIL_FROM`, `EMAIL_TO`, etc.) can still be set in `.env` as global defaults, but are overridden by the per-user credentials stored in the database. See [User credentials](#user-credentials).

## User credentials

Integration credentials (Notion keys, email settings) are stored **per-user and encrypted** in SQLite — not in `.env`. Each Telegram user configures their own credentials via the bot.

**Set a credential:**
> *"configure notion_api_key: secret_xxx"*
> *"configure email_from: me@example.com"*

Or use the `/setup` command for a guided panel.

**Supported credential keys:**

| Key | Description |
|-----|-------------|
| `notion_api_key` | Notion integration secret |
| `notion_database_id` | Main tasks database ID |
| `notion_notes_db_id` | Notes database ID |
| `notion_expenses_db_id` | Expenses database ID |
| `notion_meals_db_id` | Meals database ID |
| `notion_exercises_db_id` | Exercises database ID |
| `notion_monthly_bills_db_id` | Monthly bills database ID |
| `email_from` | Gmail address to send from |
| `email_to` | Default email recipient |
| `display_name` | Display name used in emails |
| `email_tone` | Tone for assistant-written emails |
| `email_signature` | Signature appended to emails |
| `email_style_guide` | Extra style instructions for email |
| `email_subject_prefix` | Optional prefix added to email subjects |

Google (Gmail + Calendar) credentials are managed automatically via `/google_auth` — no manual key entry needed.


## Run

```sh
python run.py
```

## Telegram commands and conversational mode

The bot works entirely through natural language messages in Telegram. There are no slash commands to memorize — just talk to it.

Built-in commands:
- `/reset` (or `/new_chat`) — Clear the conversation history for the current chat.
- `/setup` — Show the integration setup panel (Notion, Email, Google).
- `/google_auth` — Start the Google OAuth2 flow to authorize Gmail and Google Calendar.

### What the assistant can do

In any message, the assistant can:
- **Notion tasks**: list, create, and edit tasks; manage projects and due dates.
- **Notion notes**: create and list notes with date filters.
- **Expenses**: register and analyze monthly expenses by category.
- **Meals**: log meals with food, quantity (in grams), and estimated calories.
- **Exercises**: register, edit, and analyze workouts; track calories burned.
- **Metabolism**: calculate BMR/TDEE and track changes over time.
- **Google Calendar**: list upcoming events and create new events.
- **Gmail**: send emails (with explicit confirmation), search and read messages.
- **Scheduled tasks**: create recurring or one-time tasks delivered via Telegram (and optionally email).
- **Tech news**: fetch the latest news from configured RSS sources.
- **Contacts**: search contacts from `memories/contacts.csv` and register new contacts in persistent memory (`contacts.csv`).
- **Voice messages**: voice notes are transcribed automatically (Whisper) and processed as text.

For expense analysis, `analyze_monthly_expenses` supports a `date` parameter (YYYY-MM-DD) to isolate a specific day.
Meal registration requires explicit quantity in grams and estimated calories (LLM-provided, no local fallback).

## Run as Ubuntu service (systemd)

Service template:

`deploy/systemd/personal-assistant-bot.service`

Install and start (system service, requires sudo):

```sh
sudo cp deploy/systemd/personal-assistant-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now personal-assistant-bot
sudo systemctl status personal-assistant-bot --no-pager
```

If sudo is unavailable, run as a user service:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/systemd/personal-assistant-bot.service ~/.config/systemd/user/personal-assistant-bot.service
sed -i '/^User=/d; s/multi-user.target/default.target/' ~/.config/systemd/user/personal-assistant-bot.service
systemctl --user daemon-reload
systemctl --user enable --now personal-assistant-bot
systemctl --user status personal-assistant-bot --no-pager
```

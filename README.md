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

### 3) Notion credentials (optional but required for task commands)

Follow the Notion auth guide:
- https://developers.notion.com/docs/authorization

### 4) Configure `.env`

Create a `.env` at project root:

```env
NOTION_DATABASE_ID="8be..."
NOTION_NOTES_DB_ID="9af..."             # Notion database ID for notes
NOTION_EXPENSES_DB_ID="7cd..."          # Notion expenses DB (Nome, Data, Categoria, Descrição, Valor)
NOTION_MEALS_DB_ID="5ab..."             # Notion meals DB (Alimento, Refeição, Quantidade em gramas, Calorias)
NOTION_EXERCISES_DB_ID="6de..."         # Notion exercises DB (Data, Atividade, Calorias, Observações, Done)
NOTION_MONTHLY_BILLS_DB_ID="3bc..."     # Notion monthly bills DB (optional)
NOTION_API_KEY="secret_x0l..."
OPENAI_KEY="sk-..."
LLM_MODEL="gpt-4.1-mini"               # model used for the assistant
TIMEZONE="America/Sao_Paulo"           # default timezone for dates and scheduled tasks
EMAIL_FROM="example@gmail.com"
EMAIL_TO="example@gmail.com"            # default recipient for email tools
DISPLAY_NAME="Username"
EMAIL_ASSISTANT_TONE="professional, friendly, and objective" # default tone for assistant-generated emails
EMAIL_ASSISTANT_SIGNATURE="Carlos\nPersonal Assistant"        # default signature appended to the email body
EMAIL_ASSISTANT_STYLE_GUIDE="Use short sentences and end with a clear CTA." # extra style instructions
EMAIL_ASSISTANT_SUBJECT_PREFIX="[Assistant]"                 # optional subject prefix
LOG_PATH="."
TELEGRAM_BOT_TOKEN="your_telegram_bot_token_here"           # required — get from @BotFather
TELEGRAM_ALLOWED_USER_IDS="123456789"                       # required — comma-separated Telegram user IDs allowed to use the bot
GOOGLE_OAUTH_CALLBACK_URL="https://yourdomain.com/auth/google/callback" # public URL for OAuth redirect
GOOGLE_AUTH_SERVER_PORT="8080"          # port for the local OAuth callback HTTP server
CREDENTIAL_ENCRYPTION_KEY="..."        # required — Fernet key; generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
API_DAYS_TO_CONSIDER="0"               # optional, includes overdue + next N days
ASSISTANT_AGENT_ID="personal_assistant" # optional, agent id loaded from JSON config
ASSISTANT_MEMORY_PATH="./assistant_memory.sqlite3" # optional, SQLite file for persistent chat memory
ASSISTANT_MAX_MESSAGES_PER_SESSION="300" # optional, max persisted messages per session
ASSISTANT_MAX_TOOL_CALLS_PER_SESSION="300" # optional, max persisted tool calls per session
ASSISTANT_MAX_STORED_MESSAGE_CHARS="4000" # optional, max chars per stored message
ASSISTANT_MAX_STORED_TOOL_PAYLOAD_CHARS="12000" # optional, max chars per stored tool payload
ASSISTANT_MAX_HISTORY_CHARS="12000" # optional, max history chars sent to the LLM per request
ASSISTANT_MAX_TOOL_OUTPUT_CHARS="8000" # optional, max tool output chars sent back to the LLM
AUDIO_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe" # optional, model used to transcribe voice messages
```

Notes:
- `TELEGRAM_BOT_TOKEN` is required to run the assistant. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram.
- `TELEGRAM_ALLOWED_USER_IDS` should contain your Telegram user ID for private operation. Access is denied by default if empty (fail-closed behavior).
- `CREDENTIAL_ENCRYPTION_KEY` is required — user credentials (Google tokens, Notion keys) are stored encrypted.
- `GOOGLE_OAUTH_CALLBACK_URL` must be a publicly reachable URL pointing to the machine running the bot (used for the OAuth redirect from Google).
- Notion vars are required for Notion-related flows.
- Per-user credentials (Notion API key, email settings, etc.) can be configured by sending `configure <key>: <value>` to the bot, or via the `/setup` command.

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
- **Contacts**: search contacts from `memories/contacts.csv`.
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

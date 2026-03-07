# Personal Assistant for Discord :rocket:

![Personal Assistant Banner](./banner/personal-assistant-banner.png)

A personal digital assistant on Discord to help with your daily routine across multiple domains: tasks, email, calendar, readings, and news.

Notion is one of the available connections, alongside OpenAI, Gmail, Google Calendar, and other assistant capabilities.

## What this project is

This bot centralizes personal productivity workflows in Discord using slash commands and LLM support.

Current focus:
- Task capture and prioritization
- Calendar summary and event creation
- Email-ready task summaries

Planned/expanding scope:
- Reading workflows
- News digests
- Broader personal assistant automations

## Architecture at a glance

Main modules:
- `run.py`: app entrypoint
- `discord_bot.py`: Discord client and slash commands
- `notion_connector/`: task, notes, expenses, and meals read/write integration
- `gmail_connector/`: Gmail auth and email sending
- `calendar_connector/`: Google Calendar read/write integration
- `openai_connector/`: LLM prompts/parsing/summaries
- `assistant_connector/`: conversational agent runtime, tool registry, and SQLite memory
- `templates/`: email rendering templates
- `utils/`: logging, credential loading, parsing helpers

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

Place `credentials.json` in the project root. After first auth flow, `token.json` is generated.

### 3) Notion credentials (optional but required for task commands)

Follow the Notion auth guide:
- https://developers.notion.com/docs/authorization

### 4) Configure `.env`

Create a `.env` at project root:

```env
NOTION_DATABASE_ID="8be..."
NOTION_NOTES_DB_ID="9af..."             # Notion database ID for notes (/note and /notes)
NOTION_EXPENSES_DB_ID="7cd..."          # Notion expenses DB (Nome, Data, Categoria, Descrição, Valor)
NOTION_MEALS_DB_ID="5ab..."             # Notion meals DB (Alimento, Refeição, Quantidade em gramas, Calorias)
NOTION_EXERCISES_DB_ID="6de..."         # Notion exercises DB (Data, Atividade, Calorias, Observações, Done)
NOTION_API_KEY="secret_x0l..."
OPENAI_KEY="sk-..."
LLM_MODEL="gpt-4.1-mini"               # model used across assistant flows (/tasks, /calendar, /add_*, /bot)
TIMEZONE="America/Sao_Paulo"           # default timezone for scheduled tasks when input has no offset
EMAIL_FROM="example@gmail.com"
EMAIL_TO="example@gmail.com"            # optional for /bot; required for legacy automatic email flows
DISPLAY_NAME="Username"
EMAIL_ASSISTANT_TONE="professional, friendly, and objective" # default tone for assistant-generated emails
EMAIL_ASSISTANT_SIGNATURE="Carlos\nPersonal Assistant"        # default signature appended to the email body
EMAIL_ASSISTANT_STYLE_GUIDE="Use short sentences and end with a clear CTA." # extra style instructions
EMAIL_ASSISTANT_SUBJECT_PREFIX="[Assistant]"                 # optional subject prefix
LOG_PATH="."
DISCORD_BOT_TOKEN="your_bot_token_here"
DISCORD_GUILD_ID="123456789012345678" # optional, faster slash-command sync
DISCORD_ALLOWED_USER_ID="123456789012345678" # required for private operation; only this user can access slash + DM
API_DAYS_TO_CONSIDER="0"               # optional, includes overdue + next N days
ASSISTANT_AGENT_ID="personal_assistant" # optional, agent id loaded from JSON config
ASSISTANT_MEMORY_PATH="./assistant_memory.sqlite3" # optional, SQLite file for persistent chat memory
ASSISTANT_MAX_MESSAGES_PER_SESSION="300" # optional, max persisted messages per session
ASSISTANT_MAX_TOOL_CALLS_PER_SESSION="300" # optional, max persisted tool calls per session
ASSISTANT_MAX_STORED_MESSAGE_CHARS="4000" # optional, max chars per stored message
ASSISTANT_MAX_STORED_TOOL_PAYLOAD_CHARS="12000" # optional, max chars per stored tool payload
ASSISTANT_MAX_HISTORY_CHARS="12000" # optional, max history chars sent to the LLM per request
ASSISTANT_MAX_TOOL_OUTPUT_CHARS="8000" # optional, max tool output chars sent back to the LLM
AUDIO_TRANSCRIBE_MODEL="gpt-4o-mini-transcribe" # optional, model used to transcribe DM audio attachments
```

Notes:
- `DISCORD_BOT_TOKEN` is required to run the assistant.
- `DISCORD_ALLOWED_USER_ID` should be set to your Discord user ID for private operation.
- If `DISCORD_ALLOWED_USER_ID` is empty, access is denied by default (fail-closed behavior).
- Notion vars are required for Notion-related task and notes flows.
- To send email through `/bot`, keep Gmail OAuth configured (`credentials.json` + `token.json`) and set `EMAIL_ASSISTANT_*` fields.
- In `/bot`, the `send_email` tool requires an explicit recipient in the user message; the subject is defined by the LLM.

## Run

```sh
python run.py
```

## Discord commands (current)

- `/tasks` - List scheduled assistant tasks stored in SQLite.
- `/create_task <message> <scheduled_for> [max_attempts] [timezone] [email_to]` - Create a scheduled assistant task (`scheduled_for` can omit offset; uses `TIMEZONE` or explicit `timezone` override such as `America/Sao_Paulo` or `GMT-3`). Delivery is always sent to Discord DM, and optionally also to `email_to`.
- `/notion_tasks` - Fetch Notion tasks and return a prioritized Markdown summary.
- `/add_task <text>` - Parse natural language and create a Notion task.
- `/note` - Open a multiline modal and create a note in Notion Notes.
- `/notes` - List notes from 5 days back to 5 days ahead.
- `/calendar` - Summarize the next 7 days from Google Calendar.
- `/add_event <text>` - Parse natural language and create a calendar event.
- `/day` - Detailed summary for today (tasks + events).
- `/tomorrow` - Detailed summary for tomorrow (tasks + events).
- `/week` - Concise summary for the current week (Sunday to Saturday).
- `/bot <text>` - Conversational assistant with tool-calling + persistent memory.
- `/pa <text>` - Alias of `/bot`.

### Conversational mode via DM

- You can chat directly in DM without slash commands; every DM message is processed in the same assistant flow as `/bot` and `/pa`.
- In DM, you can send `/reset` (or `/new_chat`) as plain text to clear the conversation history for that DM chat.
- DM audio attachments are transcribed and processed by the same assistant flow.
- In conversational mode, the assistant can use tools for Notion tasks/notes/meals/exercises (`register_notion_meal`, `analyze_notion_meals`, `register_notion_exercise`, `edit_notion_exercise`, `analyze_notion_exercises`) and should use `done=false` to plan future workouts and `done=true` when marking completed activities; meal registration is LLM-driven and must send calories + quantity in grams (no local calorie fallback); it can also use calendar, scheduled tasks in SQLite, app health (`get_application_hardware_status`), email sending (with explicit confirmation for write actions), email reading/search (`search_emails`, `read_email`, `search_email_attachments`, `analyze_email_attachment`), tech news (`list_tech_news`), and contact search from `memories/contacts.csv` (`search_contacts`).
- For expense analysis, `analyze_monthly_expenses` supports `date` (YYYY-MM-DD) to isolate and detail one specific day (e.g., today).

## Run as Ubuntu service (systemd)

Service template:

`deploy/systemd/personal-notion-discord-bot.service`

Install and start (system service, requires sudo):

```sh
sudo cp deploy/systemd/personal-notion-discord-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now personal-notion-discord-bot
sudo systemctl status personal-notion-discord-bot --no-pager
```

If sudo is unavailable, run as a user service:

```sh
mkdir -p ~/.config/systemd/user
cp deploy/systemd/personal-notion-discord-bot.service ~/.config/systemd/user/personal-notion-discord-bot.service
sed -i '/^User=/d; s/multi-user.target/default.target/' ~/.config/systemd/user/personal-notion-discord-bot.service
systemctl --user daemon-reload
systemctl --user enable --now personal-notion-discord-bot
systemctl --user status personal-notion-discord-bot --no-pager
```

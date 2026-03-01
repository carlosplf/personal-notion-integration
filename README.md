# Personal Assistant for Discord :rocket:

![Personal Assistant Banner](./banner/personal-assistant-banner.png)

A personal digital assistant on Discord to help with your daily routine across multiple domains: tasks, email, calendar, readings, and news.

The project is integration-first: Notion is one of the connectors (not the center of the architecture), alongside OpenAI, Gmail, Google Calendar, and other assistant capabilities.

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
- `notion_connector/`: task read/write integration
- `gmail_connector/`: Gmail auth and email sending
- `calendar_connector/`: Google Calendar read/write integration
- `openai_connector/`: LLM prompts/parsing/summaries
- `templates/`: email rendering templates
- `utils/`: logging, credential loading, parsing helpers

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
NOTION_API_KEY="secret_x0l..."
OPENAI_KEY="sk-..."
EMAIL_FROM="example@gmail.com"
EMAIL_TO="example@gmail.com"
DISPLAY_NAME="Username"
LOG_PATH="."
DISCORD_BOT_TOKEN="your_bot_token_here"
DISCORD_GUILD_ID="123456789012345678" # optional, faster slash-command sync
API_DAYS_TO_CONSIDER="0"               # optional, includes overdue + next N days
```

Notes:
- `DISCORD_BOT_TOKEN` is required to run the assistant.
- Notion vars are required for Notion-related task flows.

## Run

```sh
python run.py
```

## Discord commands (current)

- `/tasks` → fetches tasks and returns a prioritized markdown summary.
- `/add_task <texto>` → parses natural language and creates a task in Notion.
- `/calendar` → summarizes your next 7 days from Google Calendar.
- `/add_event <texto>` → parses natural language and creates a calendar event.

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

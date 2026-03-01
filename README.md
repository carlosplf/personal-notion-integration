# Notion Bot to send email with Tasks :rocket:

Based on a Notion control panel, the software will fetch the tasks that must be completed in the next __N__ days and send them by email daily.

The idea is to use this API connection with Notion to automate more things, and include more information in the automated email.

## How to use

### Setup Notion

The software is based on a specific table structure (dataset) in Notion.

The dataset to be used as a task base must contain the following properties for each item:
- Tags (used as effort/context hints like `TAKES TIME`, `FAST`, `FUP`)
- Deadline (date field used to filter the closest tasks)
- ASAP (checkbox) (not used for now)
- DONE (checkbox)

Without these properties, task collection will not work correctly.

### Create a Google GMail API credentials

Visit the [website](https://developers.google.com/gmail/api/quickstart/python) to follow the tutorial and create a project on Google Cloud with proper credentials.

The Google Cloud credentials file must be in the project root folder with the name `'credentials.json'`. After the authentication, a `token.json` file will be created.
This project now also supports Google Calendar read/write access (`calendar.readonly` and `calendar.events`) through `calendar_connector/`.

### Create your Notion credentials

Follow the [Notion guide](https://developers.notion.com/docs/authorization) and create your API credentials. Put it inside a `.env` file, following this format:

```js
NOTION_DATABASE_ID="8be..."
NOTION_API_KEY="secret_x0l..."
```

### Add email configurations (optional)

The software will look for some settings like source and destination email inside the '.env' file in the root folder of the project. The file must follow the following format:

```js
EMAIL_FROM="example@gmail.com"
EMAIL_TO="example@gmail.com"
DISPLAY_NAME="Username"
```

### Get your OpenAI key

An OpenAPI API Key can be generated [here](https://platform.openai.com/account/api-keys). Put it inside the `.env` file.

```js
OPENAI_KEY="sk-rm..."
```

### Configure log path

This software uses the [logging](https://docs.python.org/3/library/logging.html) python library. A path must be inserted in the `.env` file. Log messages will be streamed to the log file AND to the terminal output.

```js
LOG_PATH="."
```

### Add Discord bot token

Create your bot in the Discord Developer Portal and put the token in `.env`:

```js
DISCORD_BOT_TOKEN="your_bot_token_here"
DISCORD_GUILD_ID="123456789012345678" // optional, recommended for instant slash command sync
API_DAYS_TO_CONSIDER="0" // optional, includes overdue tasks plus tasks due in the next N days
```

### Install requirements and run the bot :racing_car:

Now that all the necessary informations are present in the `.env` file, you just need to install the python requirements and run the software.

```sh
python3 -m venv ./env
pip install -r requirements.txt
python run.py
```

## Discord usage

After `python run.py`, use the slash command:

- `/tasks` -> fetches tasks from Notion and returns a standardized Markdown summary in the Discord channel.
- `/add_task <texto>` -> uses LLM to interpret text, extract task/project/date/tags and create the task in Notion.

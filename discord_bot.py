import os

import discord
from dotenv import load_dotenv

from calendar_connector import calendar_connector
from notion_connector import notion_connector
from openai_connector import llm_api
from task_summary_flow import collect_tasks_and_summary
from utils import create_logger

MAX_DISCORD_MESSAGE_LENGTH = 2000


def _truncate_text(text, limit):
    if len(text) <= limit:
        return text
    return f"{text[:limit - 3]}..."


def build_tasks_response(tasks, summary):
    content = f"## Tarefas encontradas: {len(tasks)}\n\n{summary}"
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def build_error_response(error):
    return _truncate_text(
        f"Failed to collect tasks: {error}",
        MAX_DISCORD_MESSAGE_LENGTH,
    )


def build_add_task_success_response(task_data):
    tags = ", ".join(task_data.get("tags", [])) if task_data.get("tags") else "sem tags"
    content = (
        "✅ Tarefa criada no Notion.\n"
        f"- **Tarefa:** {task_data['task_name']}\n"
        f"- **Projeto:** {task_data['project']}\n"
        f"- **Data:** {task_data['due_date']}\n"
        f"- **Tags:** {tags}"
    )
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def build_calendar_response(summary):
    content = f"## Agenda (7 dias)\n\n{summary}"
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def build_add_event_success_response(event_data):
    content = (
        "✅ Evento criado no Google Calendar.\n"
        f"- **Título:** {event_data['summary']}\n"
        f"- **Início:** {event_data['start']}\n"
        f"- **Fim:** {event_data['end']}\n"
        f"- **Link:** {event_data.get('html_link', 'N/A')}"
    )
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def create_discord_client(project_logger=None):
    logger = project_logger or create_logger.create_logger()
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = discord.app_commands.CommandTree(client)
    n_days = int(os.getenv("API_DAYS_TO_CONSIDER", "0"))

    @tree.command(name="tasks", description="Fetch tasks from Notion and summarize with GPT")
    async def tasks_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            tasks, summary = collect_tasks_and_summary(logger, n_days=n_days)
            await interaction.followup.send(build_tasks_response(tasks, summary))
        except Exception as error:
            logger.exception("Error running /tasks command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="add_task", description="Add a task to Notion using natural language")
    async def add_task_command(interaction: discord.Interaction, input_text: str):
        await interaction.response.defer(thinking=True)
        try:
            parsed_task = llm_api.parse_add_task_input(input_text, logger)
            created_task = notion_connector.create_task_in_control_panel(parsed_task, logger)
            await interaction.followup.send(build_add_task_success_response(created_task))
        except Exception as error:
            logger.exception("Error running /add_task command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="calendar", description="Summarize your calendar events for the next 7 days")
    async def calendar_command(interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            events = calendar_connector.list_week_events(project_logger=logger)
            summary = llm_api.summarize_calendar_events(events, logger)
            await interaction.followup.send(build_calendar_response(summary))
        except Exception as error:
            logger.exception("Error running /calendar command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="add_event", description="Add a calendar event using natural language")
    async def add_event_command(interaction: discord.Interaction, input_text: str):
        await interaction.response.defer(thinking=True)
        try:
            parsed_event = llm_api.parse_add_event_input(input_text, logger)
            created_event = calendar_connector.create_calendar_event(
                project_logger=logger,
                summary=parsed_event["summary"],
                start_datetime=parsed_event["start_datetime"],
                end_datetime=parsed_event["end_datetime"],
                description=parsed_event["description"],
                timezone=parsed_event["timezone"],
            )
            await interaction.followup.send(build_add_event_success_response(created_event))
        except Exception as error:
            logger.exception("Error running /add_event command")
            await interaction.followup.send(build_error_response(error))

    @client.event
    async def on_ready():
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            tree.copy_global_to(guild=guild)
            await tree.sync(guild=guild)
            logger.info("Discord bot online as %s (guild sync)", client.user)
            return
        await tree.sync()
        logger.info("Discord bot online as %s (global sync)", client.user)

    return client


def run_discord_bot():
    load_dotenv()
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        raise ValueError("Missing required environment variable: DISCORD_BOT_TOKEN")
    client = create_discord_client()
    client.run(bot_token)

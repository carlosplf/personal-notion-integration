import asyncio
import datetime
import os

import discord
from dotenv import load_dotenv

from assistant_connector import create_assistant_service
from calendar_connector import calendar_connector
from notion_connector import notion_connector
from openai_connector import llm_api
from task_summary_flow import collect_tasks_and_summary
from utils import create_logger

MAX_DISCORD_MESSAGE_LENGTH = 2000
ACCESS_DENIED_MESSAGE = (
    "🔒 Access denied: this assistant is restricted to an authorized Discord user."
)
SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".ogg",
    ".oga",
    ".webm",
    ".mp4",
    ".mpeg",
}


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


def build_add_note_success_response(note_data):
    content = (
        "✅ Note created in Notion.\n"
        f"- **Name:** {note_data['note_name']}\n"
        f"- **Date:** {note_data['date']}\n"
        f"- **Tag:** {note_data['tag']}"
    )
    if note_data.get("url"):
        content += f"\n- **URL:** {note_data['url']}"
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def build_notes_response(notes):
    if not notes:
        return "## Notes (-5 to +5 days)\n\nNo notes found for this period."

    lines = []
    for note in notes:
        note_date = _extract_iso_date(note.get("date"))
        tags = ", ".join(note.get("tags", [])) if note.get("tags") else "no tags"
        line = f"- **{note_date}** — **{note.get('name', 'Untitled')}** ({tags})"
        observations = str(note.get("observations", "")).strip()
        if observations:
            lines.append(f"{line}\n  - {observations}")
        else:
            lines.append(line)
        if note.get("url"):
            lines[-1] = f"{lines[-1]}\n  - URL: {note['url']}"

    content = f"## Notes (-5 to +5 days)\n\n{chr(10).join(lines)}"
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def _default_note_name_from_input(input_text):
    for raw_line in str(input_text or "").splitlines():
        line = raw_line.strip()
        if line:
            normalized = line.lstrip("#-* ").strip()
            return (normalized or line)[:120]
    return "New note"


def _is_authorized_discord_user(user_id, allowed_user_id):
    allowed = str(allowed_user_id or "").strip()
    if not allowed:
        return False
    return str(user_id) == allowed


def _is_audio_attachment(attachment):
    content_type = str(getattr(attachment, "content_type", "") or "").lower()
    if content_type.startswith("audio/"):
        return True
    filename = str(getattr(attachment, "filename", "") or "").lower()
    return any(filename.endswith(extension) for extension in SUPPORTED_AUDIO_EXTENSIONS)


def _select_audio_attachment(attachments):
    for attachment in attachments or []:
        if _is_audio_attachment(attachment):
            return attachment
    return None


def build_note_payload_from_input(input_text, project_logger):
    clean_input = str(input_text or "").strip()
    if not clean_input:
        raise ValueError("Note input cannot be empty")

    parsed_note = {}
    try:
        parsed_note = llm_api.parse_add_note_input(clean_input, project_logger)
    except Exception:
        parsed_note = {}

    return {
        "note_name": str(parsed_note.get("note_name", "")).strip() or _default_note_name_from_input(clean_input),
        "tag": str(parsed_note.get("tag", "GENERAL")).strip() or "GENERAL",
        "url": str(parsed_note.get("url", "")).strip(),
        "observations": clean_input,
    }


def _extract_iso_date(value):
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    return raw_value.split("T", 1)[0]


def _format_time_label(value):
    raw_value = str(value or "").strip()
    if "T" not in raw_value:
        return "Dia inteiro"
    return raw_value.split("T", 1)[1][:5]


def filter_tasks_for_today(tasks):
    today = datetime.date.today().isoformat()
    return [task for task in tasks if _extract_iso_date(task.get("deadline")) == today]


def filter_events_for_today(events):
    today = datetime.date.today().isoformat()
    return [event for event in events if _extract_iso_date(event.get("start")) == today]


def _current_week_bounds():
    today = datetime.date.today()
    days_since_sunday = (today.weekday() + 1) % 7
    week_start = today - datetime.timedelta(days=days_since_sunday)
    week_end = week_start + datetime.timedelta(days=6)
    return week_start, week_end


def filter_tasks_for_tomorrow(tasks):
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    return [task for task in tasks if _extract_iso_date(task.get("deadline")) == tomorrow]


def filter_events_for_tomorrow(events):
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    return [event for event in events if _extract_iso_date(event.get("start")) == tomorrow]


def filter_tasks_for_current_week(tasks):
    week_start, week_end = _current_week_bounds()
    filtered = []
    for task in tasks:
        iso_date = _extract_iso_date(task.get("deadline"))
        if not iso_date:
            continue
        try:
            due_date = datetime.date.fromisoformat(iso_date)
        except ValueError:
            continue
        if week_start <= due_date <= week_end:
            filtered.append(task)
    return filtered


def filter_events_for_current_week(events):
    week_start, week_end = _current_week_bounds()
    filtered = []
    for event in events:
        iso_date = _extract_iso_date(event.get("start"))
        if not iso_date:
            continue
        try:
            event_date = datetime.date.fromisoformat(iso_date)
        except ValueError:
            continue
        if week_start <= event_date <= week_end:
            filtered.append(event)
    return filtered


def build_day_response(today_tasks, today_events):
    task_lines = []
    if today_tasks:
        for task in today_tasks:
            task_name = task.get("name", "Sem nome")
            project_name = task.get("project", "Sem projeto")
            deadline_label = _format_time_label(task.get("deadline"))
            task_lines.append(f"- **{task_name}** ({project_name}) — {deadline_label}")
    else:
        task_lines.append("- Sem tarefas do Notion para hoje.")

    event_lines = []
    if today_events:
        for event in today_events:
            event_name = event.get("summary", "Sem título")
            time_label = _format_time_label(event.get("start"))
            location = event.get("location")
            if location:
                event_lines.append(f"- **{time_label}** — {event_name} ({location})")
            else:
                event_lines.append(f"- **{time_label}** — {event_name}")
    else:
        event_lines.append("- Sem eventos na agenda para hoje.")

    content = (
        "## Resumo de hoje\n\n"
        f"### Tarefas do Notion ({len(today_tasks)})\n"
        f"{chr(10).join(task_lines)}\n\n"
        f"### Eventos da agenda ({len(today_events)})\n"
        f"{chr(10).join(event_lines)}"
    )
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def _is_markdown_formatted(text):
    stripped = str(text or "").lstrip()
    return (
        stripped.startswith("#")
        or stripped.startswith("- ")
        or stripped.startswith("* ")
        or stripped.startswith("1. ")
        or "```" in stripped
    )


def _ensure_markdown_response(text):
    clean_text = str(text or "").strip()
    if not clean_text:
        clean_text = "Desculpe, não consegui responder agora."
    if _is_markdown_formatted(clean_text):
        return clean_text
    return f"## Assistente pessoal\n\n{clean_text}"


def build_bot_response(answer):
    content = _ensure_markdown_response(answer)
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def create_discord_client(project_logger=None):
    logger = project_logger or create_logger.create_logger()
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = discord.app_commands.CommandTree(client)
    n_days = int(os.getenv("API_DAYS_TO_CONSIDER", "0"))
    allowed_user_id = str(os.getenv("DISCORD_ALLOWED_USER_ID", "")).strip()
    assistant_service = None

    def get_assistant_service():
        nonlocal assistant_service
        if assistant_service is None:
            assistant_service = create_assistant_service(project_logger=logger)
        return assistant_service

    async def _run_personal_assistant_chat(user_id, channel_id, guild_id, input_text):
        service = get_assistant_service()
        answer = await asyncio.to_thread(
            service.chat,
            user_id=str(user_id),
            channel_id=str(channel_id),
            guild_id=str(guild_id) if guild_id else None,
            message=input_text,
        )
        return answer

    async def _run_personal_assistant_command(interaction: discord.Interaction, command_name: str, input_text: str):
        if not await _ensure_authorized_interaction(interaction, command_name):
            return
        await interaction.response.defer(thinking=True)
        try:
            answer = await _run_personal_assistant_chat(
                user_id=interaction.user.id,
                channel_id=interaction.channel_id,
                guild_id=interaction.guild_id,
                input_text=input_text,
            )
            await interaction.followup.send(build_bot_response(answer))
        except Exception as error:
            logger.exception("Error running /%s command", command_name)
            await interaction.followup.send(build_error_response(error))

    async def _ensure_authorized_interaction(interaction: discord.Interaction, command_name: str):
        if _is_authorized_discord_user(interaction.user.id, allowed_user_id):
            return True
        warning_message = ACCESS_DENIED_MESSAGE
        logger.warning("Unauthorized /%s attempt by user_id=%s", command_name, interaction.user.id)
        if interaction.response.is_done():
            await interaction.followup.send(warning_message, ephemeral=True)
        else:
            await interaction.response.send_message(warning_message, ephemeral=True)
        return False

    async def _create_note_from_input(interaction: discord.Interaction, input_text: str):
        try:
            note_payload = build_note_payload_from_input(input_text, logger)
            created_note = notion_connector.create_note_in_notes_db(note_payload, logger)
            await interaction.followup.send(build_add_note_success_response(created_note))
        except Exception as error:
            logger.exception("Error running /note command")
            await interaction.followup.send(build_error_response(error))

    class NoteInputModal(discord.ui.Modal, title="Add note"):
        note_text = discord.ui.TextInput(
            label="Note content",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=4000,
            placeholder="Write your note with as much detail as needed...",
        )

        async def on_submit(self, interaction: discord.Interaction):
            if not _is_authorized_discord_user(interaction.user.id, allowed_user_id):
                await interaction.response.send_message(ACCESS_DENIED_MESSAGE, ephemeral=True)
                return
            await interaction.response.defer(thinking=True)
            await _create_note_from_input(interaction, str(self.note_text))

        async def on_error(self, interaction: discord.Interaction, error: Exception):
            logger.exception("Error in /note modal")
            if interaction.response.is_done():
                await interaction.followup.send(build_error_response(error))
            else:
                await interaction.response.send_message(build_error_response(error))

    @tree.command(name="tasks", description="Fetch tasks from Notion and summarize with GPT")
    async def tasks_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "tasks"):
            return
        await interaction.response.defer(thinking=True)
        try:
            tasks, summary = collect_tasks_and_summary(logger, n_days=n_days)
            await interaction.followup.send(build_tasks_response(tasks, summary))
        except Exception as error:
            logger.exception("Error running /tasks command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="add_task", description="Add a task to Notion using natural language")
    async def add_task_command(interaction: discord.Interaction, input_text: str):
        if not await _ensure_authorized_interaction(interaction, "add_task"):
            return
        await interaction.response.defer(thinking=True)
        try:
            parsed_task = llm_api.parse_add_task_input(input_text, logger)
            created_task = notion_connector.create_task_in_control_panel(parsed_task, logger)
            await interaction.followup.send(build_add_task_success_response(created_task))
        except Exception as error:
            logger.exception("Error running /add_task command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="note", description="Add a detailed note to Notion Notes")
    async def add_note_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "note"):
            return
        try:
            await interaction.response.send_modal(NoteInputModal())
        except Exception as error:
            logger.exception("Error opening /note modal")
            if interaction.response.is_done():
                await interaction.followup.send(build_error_response(error))
            else:
                await interaction.response.send_message(build_error_response(error))

    @tree.command(name="notes", description="List notes from 5 days back to 5 days ahead")
    async def notes_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "notes"):
            return
        await interaction.response.defer(thinking=True)
        try:
            notes = notion_connector.collect_notes_around_today(
                days_back=5,
                days_forward=5,
                project_logger=logger,
            )
            await interaction.followup.send(build_notes_response(notes))
        except Exception as error:
            logger.exception("Error running /notes command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="calendar", description="Summarize your calendar events for the next 7 days")
    async def calendar_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "calendar"):
            return
        await interaction.response.defer(thinking=True)
        try:
            events = calendar_connector.list_week_events(project_logger=logger)
            summary = llm_api.summarize_calendar_events(events, logger)
            await interaction.followup.send(build_calendar_response(summary))
        except Exception as error:
            logger.exception("Error running /calendar command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="day", description="Summarize today's Notion tasks and calendar events")
    async def day_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "day"):
            return
        await interaction.response.defer(thinking=True)
        try:
            tasks = notion_connector.collect_tasks_from_control_panel(
                n_days=0,
                project_logger=logger,
            )
            events = calendar_connector.list_week_events(project_logger=logger)
            today_tasks = filter_tasks_for_today(tasks)
            today_events = filter_events_for_today(events)
            summary = llm_api.summarize_day_context(today_tasks, today_events, logger)
            await interaction.followup.send(build_bot_response(summary))
        except Exception as error:
            logger.exception("Error running /day command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="tomorrow", description="Summarize tomorrow's Notion tasks and calendar events")
    async def tomorrow_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "tomorrow"):
            return
        await interaction.response.defer(thinking=True)
        try:
            tasks = notion_connector.collect_tasks_from_control_panel(
                n_days=1,
                project_logger=logger,
            )
            events = calendar_connector.list_week_events(project_logger=logger)
            tomorrow_tasks = filter_tasks_for_tomorrow(tasks)
            tomorrow_events = filter_events_for_tomorrow(events)
            summary = llm_api.summarize_period_context("amanhã", tomorrow_tasks, tomorrow_events, logger)
            await interaction.followup.send(build_bot_response(summary))
        except Exception as error:
            logger.exception("Error running /tomorrow command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="week", description="Summarize current week's Notion tasks and calendar events")
    async def week_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "week"):
            return
        await interaction.response.defer(thinking=True)
        try:
            week_start, week_end = _current_week_bounds()
            days_until_week_end = max((week_end - datetime.date.today()).days, 0)
            tasks = notion_connector.collect_tasks_from_control_panel(
                n_days=days_until_week_end,
                project_logger=logger,
            )
            events = calendar_connector.list_current_week_events(project_logger=logger)
            week_tasks = filter_tasks_for_current_week(tasks)
            week_events = filter_events_for_current_week(events)
            summary = llm_api.summarize_period_context("semana atual", week_tasks, week_events, logger)
            await interaction.followup.send(build_bot_response(summary))
        except Exception as error:
            logger.exception("Error running /week command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="add_event", description="Add a calendar event using natural language")
    async def add_event_command(interaction: discord.Interaction, input_text: str):
        if not await _ensure_authorized_interaction(interaction, "add_event"):
            return
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

    @tree.command(name="bot", description="Talk to your personal assistant")
    async def bot_command(interaction: discord.Interaction, input_text: str):
        await _run_personal_assistant_command(interaction, "bot", input_text)

    @tree.command(name="pa", description="Talk to your personal assistant")
    async def pa_command(interaction: discord.Interaction, input_text: str):
        await _run_personal_assistant_command(interaction, "pa", input_text)

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

    @client.event
    async def on_message(message):
        if getattr(message.author, "bot", False):
            return
        if getattr(message, "guild", None) is not None:
            return
        if not _is_authorized_discord_user(getattr(message.author, "id", ""), allowed_user_id):
            await message.channel.send(ACCESS_DENIED_MESSAGE)
            return

        input_text = str(getattr(message, "content", "")).strip()
        audio_attachment = _select_audio_attachment(getattr(message, "attachments", []))
        if not input_text and audio_attachment:
            try:
                async with message.channel.typing():
                    audio_bytes = await audio_attachment.read(use_cached=True)
                    input_text = await asyncio.to_thread(
                        llm_api.transcribe_audio_input,
                        audio_bytes,
                        getattr(audio_attachment, "filename", "dm_audio"),
                        getattr(audio_attachment, "content_type", ""),
                        logger,
                    )
            except Exception as error:
                logger.exception("Error transcribing DM audio")
                await message.channel.send(build_error_response(error))
                return
        if not input_text:
            return

        try:
            async with message.channel.typing():
                answer = await _run_personal_assistant_chat(
                    user_id=message.author.id,
                    channel_id=message.channel.id,
                    guild_id=None,
                    input_text=input_text,
                )
            await message.channel.send(build_bot_response(answer))
        except Exception as error:
            logger.exception("Error running DM assistant flow")
            await message.channel.send(build_error_response(error))

    return client


def run_discord_bot():
    load_dotenv()
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        raise ValueError("Missing required environment variable: DISCORD_BOT_TOKEN")
    client = create_discord_client()
    client.run(bot_token)

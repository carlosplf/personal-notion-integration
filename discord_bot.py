import asyncio
import datetime
import os
import re
from zoneinfo import ZoneInfo

import discord
from dotenv import load_dotenv

from assistant_connector import app_health
from assistant_connector import create_assistant_service
from assistant_connector.scheduler import AssistantScheduledTaskRunner
from calendar_connector import calendar_connector
from gmail_connector import gmail_connector
from notion_connector import notion_connector
from openai_connector import llm_api
from task_summary_flow import collect_tasks_and_summary
from utils import create_logger
from utils.timezone_utils import today_in_configured_timezone

MAX_DISCORD_MESSAGE_LENGTH = 2000
DISCORD_CHUNK_TARGET = 1800
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


def _get_env_int(name, default, *, minimum=1):
    raw_value = str(os.getenv(name, "")).strip()
    if not raw_value:
        return default
    try:
        parsed = int(raw_value)
    except ValueError:
        return default
    return max(parsed, minimum)


def _is_scheduler_enabled():
    raw_value = str(os.getenv("ASSISTANT_SCHEDULER_ENABLED", "1")).strip().lower()
    return raw_value not in {"0", "false", "no", "off"}


def _split_discord_message_chunks(text, chunk_size=DISCORD_CHUNK_TARGET):
    clean_text = str(text or "")
    if len(clean_text) <= chunk_size:
        return [clean_text]

    chunks = []
    remaining = clean_text
    while len(remaining) > chunk_size:
        split_idx = remaining.rfind("\n\n", 0, chunk_size)
        if split_idx <= 0:
            split_idx = remaining.rfind("\n", 0, chunk_size)
        if split_idx <= 0:
            split_idx = remaining.rfind(" ", 0, chunk_size)
        if split_idx <= 0:
            split_idx = chunk_size
        chunk = remaining[:split_idx].strip()
        if not chunk:
            chunk = remaining[:chunk_size]
            split_idx = chunk_size
        chunks.append(chunk)
        remaining = remaining[split_idx:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _send_discord_text(send_callable, text, **send_kwargs):
    chunks = _split_discord_message_chunks(text)
    for chunk in chunks:
        await send_callable(chunk, **send_kwargs)


def build_tasks_response(tasks, summary):
    content = f"## Tarefas encontradas: {len(tasks)}\n\n{summary}"
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def build_scheduled_tasks_response(tasks):
    if not tasks:
        return "## Tarefas agendadas\n\n- Nenhuma tarefa agendada encontrada."
    lines = []
    for task in tasks:
        message_preview = str(task.get("message", "")).replace("\n", " ").strip()
        if len(message_preview) > 90:
            message_preview = f"{message_preview[:87]}..."
        lines.append(
            f"- **{task.get('task_id')}** | `{task.get('status')}` | "
            f"`{_format_task_timestamp_for_user(task, 'next_attempt_at')}`\n"
            f"  - **Mensagem:** {message_preview}\n"
            f"  - **Recorrência:** {_format_recurrence_label(task.get('recurrence_pattern'))}"
        )
        if str(task.get("notify_email_to", "")).strip():
            lines[-1] = f"{lines[-1]}\n  - **Email complementar:** {task.get('notify_email_to')}"
    content = f"## Tarefas agendadas ({len(tasks)})\n\n{chr(10).join(lines)}"
    return _truncate_text(content, MAX_DISCORD_MESSAGE_LENGTH)


def build_create_task_success_response(task):
    content = (
        "✅ Tarefa agendada criada.\n"
        f"- **ID:** {task.get('task_id')}\n"
        f"- **Status:** {task.get('status')}\n"
        f"- **Agendada para:** {_format_task_timestamp_for_user(task, 'scheduled_for')}\n"
        f"- **Recorrência:** {_format_recurrence_label(task.get('recurrence_pattern'))}\n"
        f"- **Tentativas máximas:** {task.get('max_attempts')}"
    )
    email_to = str(task.get("notify_email_to", "")).strip()
    if email_to:
        content += f"\n- **Email complementar:** {email_to}"
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


def _resolve_timezone_name(timezone_value):
    requested = str(timezone_value or "").strip() or str(os.getenv("TIMEZONE", "UTC")).strip() or "UTC"
    gmt_match = re.fullmatch(r"(?:GMT|UTC)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", requested, re.IGNORECASE)
    if gmt_match:
        signal = 1 if gmt_match.group(1) == "+" else -1
        hours = int(gmt_match.group(2))
        minutes = int(gmt_match.group(3) or 0)
        if hours > 23 or minutes > 59:
            raise ValueError("Invalid GMT/UTC offset timezone")
        offset = signal * datetime.timedelta(hours=hours, minutes=minutes)
        label = f"UTC{gmt_match.group(1)}{hours:02d}:{minutes:02d}"
        return label, datetime.timezone(offset, name=label)
    try:
        return requested, ZoneInfo(requested)
    except Exception as error:
        raise ValueError(f"Invalid timezone: {requested}") from error


def _format_timestamp_for_timezone(value, timezone_name):
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    normalized = f"{raw_value[:-1]}+00:00" if raw_value.endswith("Z") else raw_value
    parsed = datetime.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    _, tz_info = _resolve_timezone_name(timezone_name)
    localized = parsed.astimezone(tz_info)
    return localized.strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_task_timestamp_for_user(task, field_name):
    timezone_name = str(task.get("scheduled_timezone") or os.getenv("TIMEZONE", "UTC"))
    try:
        return _format_timestamp_for_timezone(task.get(field_name), timezone_name)
    except ValueError:
        return _format_timestamp_for_timezone(task.get(field_name), "UTC")


def _normalize_scheduler_timestamp(value, timezone_hint=None):
    raw_value = str(value or "").strip()
    if not raw_value:
        raise ValueError("scheduled_for is required")
    normalized = f"{raw_value[:-1]}+00:00" if raw_value.endswith("Z") else raw_value
    parsed = datetime.datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        timezone_name = str(parsed.tzinfo)
        utc_parsed = parsed.astimezone(datetime.timezone.utc)
    else:
        timezone_name, tz_info = _resolve_timezone_name(timezone_hint)
        utc_parsed = parsed.replace(tzinfo=tz_info).astimezone(datetime.timezone.utc)
    utc_value = utc_parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return utc_value, timezone_name


def _format_recurrence_label(value):
    labels = {
        "none": "não recorrente",
        "daily": "diária",
        "weekly": "semanal",
        "monthly": "mensal",
    }
    normalized = str(value or "none").strip().lower() or "none"
    return labels.get(normalized, normalized)


def _format_time_label(value):
    raw_value = str(value or "").strip()
    if "T" not in raw_value:
        return "Dia inteiro"
    return raw_value.split("T", 1)[1][:5]


def filter_tasks_for_today(tasks):
    today = today_in_configured_timezone().isoformat()
    return [task for task in tasks if _extract_iso_date(task.get("deadline")) == today]


def filter_events_for_today(events):
    today = today_in_configured_timezone().isoformat()
    return [event for event in events if _extract_iso_date(event.get("start")) == today]


def _current_week_bounds():
    today = today_in_configured_timezone()
    days_since_sunday = (today.weekday() + 1) % 7
    week_start = today - datetime.timedelta(days=days_since_sunday)
    week_end = week_start + datetime.timedelta(days=6)
    return week_start, week_end


def filter_tasks_for_tomorrow(tasks):
    tomorrow = (today_in_configured_timezone() + datetime.timedelta(days=1)).isoformat()
    return [task for task in tasks if _extract_iso_date(task.get("deadline")) == tomorrow]


def filter_events_for_tomorrow(events):
    tomorrow = (today_in_configured_timezone() + datetime.timedelta(days=1)).isoformat()
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
    return content

def build_new_chat_response():
    return "## Nova conversa iniciada\n\nPronto. Limpei o histórico deste chat e vou responder sem contexto anterior."


def _is_dm_reset_shortcut(text):
    normalized = str(text or "").strip().lower()
    return normalized in {"/reset", "/new_chat"}


def create_discord_client(project_logger=None):
    logger = project_logger or create_logger.create_logger()
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = discord.app_commands.CommandTree(client)
    n_days = int(os.getenv("API_DAYS_TO_CONSIDER", "0"))
    allowed_user_id = str(os.getenv("DISCORD_ALLOWED_USER_ID", "")).strip()
    assistant_service = None
    scheduler_runner = None

    def get_assistant_service():
        nonlocal assistant_service
        if assistant_service is None:
            assistant_service = create_assistant_service(project_logger=logger)
        return assistant_service

    def get_scheduler_runner():
        nonlocal scheduler_runner
        if scheduler_runner is not None:
            return scheduler_runner
        if not _is_scheduler_enabled():
            app_health.set_task_checker_status("disabled")
            return None
        scheduler_runner = AssistantScheduledTaskRunner(
            assistant_service_factory=get_assistant_service,
            project_logger=logger,
            poll_interval_seconds=_get_env_int("ASSISTANT_SCHEDULER_POLL_SECONDS", 5, minimum=1),
            stale_running_after_seconds=_get_env_int(
                "ASSISTANT_SCHEDULER_STALE_SECONDS",
                300,
                minimum=1,
            ),
            retry_base_seconds=_get_env_int("ASSISTANT_SCHEDULER_RETRY_BASE_SECONDS", 30, minimum=1),
            retry_max_seconds=_get_env_int("ASSISTANT_SCHEDULER_RETRY_MAX_SECONDS", 900, minimum=1),
            on_task_succeeded=_handle_scheduled_task_success,
        )
        return scheduler_runner

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

    async def _list_scheduled_tasks(user_id):
        service = get_assistant_service()
        return await asyncio.to_thread(
            service.list_scheduled_tasks,
            user_id=str(user_id),
            limit=20,
        )

    async def _create_scheduled_task(
        user_id,
        channel_id,
        guild_id,
        message,
        scheduled_for,
        max_attempts,
        timezone,
        email_to,
        recurrence,
    ):
        service = get_assistant_service()
        normalized_scheduled_for, effective_timezone = _normalize_scheduler_timestamp(scheduled_for, timezone)
        task_id = await asyncio.to_thread(
            service.schedule_chat,
            user_id=str(user_id),
            channel_id=str(channel_id),
            guild_id=str(guild_id) if guild_id else None,
            message=message,
            scheduled_for=normalized_scheduled_for,
            scheduled_timezone=effective_timezone,
            notify_email_to=str(email_to or "").strip(),
            recurrence_pattern=str(recurrence or "none").strip().lower() or "none",
            max_attempts=max_attempts,
        )
        task = await asyncio.to_thread(service.get_scheduled_task, task_id=task_id)
        return task or {
            "task_id": task_id,
            "status": "pending",
            "scheduled_for": normalized_scheduled_for,
            "scheduled_timezone": effective_timezone,
            "notify_email_to": str(email_to or "").strip(),
            "recurrence_pattern": str(recurrence or "none").strip().lower() or "none",
        }

    async def _dispatch_scheduled_task_delivery(outcome):
        task = outcome.get("task") or {}
        response_text = str(outcome.get("response_text", "")).strip()
        if not response_text:
            return
        user_id = str(task.get("user_id", "")).strip()
        if not user_id:
            return
        user = await client.fetch_user(int(user_id))
        await _send_discord_text(
            user.send,
            f"## Resultado de tarefa agendada\n\n{build_bot_response(response_text)}",
        )

        email_to = str(task.get("notify_email_to", "")).strip()
        if not email_to:
            return
        task_message = str(task.get("message", "")).strip() or "Tarefa agendada"
        await asyncio.to_thread(
            gmail_connector.send_custom_email,
            project_logger=logger,
            subject=f"[Agendado] {task_message[:80]}",
            body_text=build_bot_response(response_text),
            email_to=email_to,
            body_subtype="plain",
        )

    def _handle_scheduled_task_success(outcome):
        future = asyncio.run_coroutine_threadsafe(_dispatch_scheduled_task_delivery(outcome), client.loop)

        def _on_done(done_future):
            try:
                done_future.result()
            except Exception as error:
                logger.exception("Error delivering scheduled task output: %s", error)

        future.add_done_callback(_on_done)

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
            await _send_discord_text(interaction.followup.send, build_bot_response(answer))
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

    @tree.command(name="tasks", description="List scheduled tasks")
    async def tasks_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "tasks"):
            return
        await interaction.response.defer(thinking=True)
        try:
            tasks = await _list_scheduled_tasks(interaction.user.id)
            await interaction.followup.send(build_scheduled_tasks_response(tasks))
        except Exception as error:
            logger.exception("Error running /tasks command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="create_task", description="Create a scheduled task")
    async def create_task_command(
        interaction: discord.Interaction,
        message: str,
        scheduled_for: str,
        max_attempts: int = 3,
        timezone: str | None = None,
        email_to: str | None = None,
        recurrence: str = "none",
    ):
        if not await _ensure_authorized_interaction(interaction, "create_task"):
            return
        await interaction.response.defer(thinking=True)
        try:
            created_task = await _create_scheduled_task(
                user_id=interaction.user.id,
                channel_id=interaction.channel_id,
                guild_id=interaction.guild_id,
                message=message,
                scheduled_for=scheduled_for,
                max_attempts=max_attempts,
                timezone=timezone,
                email_to=email_to,
                recurrence=recurrence,
            )
            await interaction.followup.send(build_create_task_success_response(created_task))
        except Exception as error:
            logger.exception("Error running /create_task command")
            await interaction.followup.send(build_error_response(error))

    @tree.command(name="notion_tasks", description="Fetch tasks from Notion and summarize with GPT")
    async def notion_tasks_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "notion_tasks"):
            return
        await interaction.response.defer(thinking=True)
        try:
            tasks, summary = collect_tasks_and_summary(logger, n_days=n_days)
            await interaction.followup.send(build_tasks_response(tasks, summary))
        except Exception as error:
            logger.exception("Error running /notion_tasks command")
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
            await _send_discord_text(interaction.followup.send, build_bot_response(summary))
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
            await _send_discord_text(interaction.followup.send, build_bot_response(summary))
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
            days_until_week_end = max((week_end - today_in_configured_timezone()).days, 0)
            tasks = notion_connector.collect_tasks_from_control_panel(
                n_days=days_until_week_end,
                project_logger=logger,
            )
            events = calendar_connector.list_current_week_events(project_logger=logger)
            week_tasks = filter_tasks_for_current_week(tasks)
            week_events = filter_events_for_current_week(events)
            summary = llm_api.summarize_period_context("semana atual", week_tasks, week_events, logger)
            await _send_discord_text(interaction.followup.send, build_bot_response(summary))
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

    @tree.command(name="new_chat", description="Start a new conversation (clear assistant history for this chat)")
    async def new_chat_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "new_chat"):
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            service = get_assistant_service()
            await asyncio.to_thread(
                service.reset_chat,
                user_id=str(interaction.user.id),
                channel_id=str(interaction.channel_id),
                guild_id=str(interaction.guild_id) if interaction.guild_id else None,
            )
            await interaction.followup.send(build_new_chat_response(), ephemeral=True)
        except Exception as error:
            logger.exception("Error running /new_chat command")
            await interaction.followup.send(build_error_response(error), ephemeral=True)

    @tree.command(name="reset", description="Reset conversation context (clear assistant history for this chat)")
    async def reset_command(interaction: discord.Interaction):
        if not await _ensure_authorized_interaction(interaction, "reset"):
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            service = get_assistant_service()
            await asyncio.to_thread(
                service.reset_chat,
                user_id=str(interaction.user.id),
                channel_id=str(interaction.channel_id),
                guild_id=str(interaction.guild_id) if interaction.guild_id else None,
            )
            await interaction.followup.send(build_new_chat_response(), ephemeral=True)
        except Exception as error:
            logger.exception("Error running /reset command")
            await interaction.followup.send(build_error_response(error), ephemeral=True)

    @client.event
    async def on_ready():
        runner = get_scheduler_runner()
        if runner is not None:
            runner.start()
            app_health.set_task_checker_status("running" if runner.is_running() else "stopped")
        else:
            app_health.set_task_checker_status("disabled")
        app_health.set_bot_status("online")
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
        if _is_dm_reset_shortcut(input_text):
            try:
                service = get_assistant_service()
                await asyncio.to_thread(
                    service.reset_chat,
                    user_id=str(message.author.id),
                    channel_id=str(message.channel.id),
                    guild_id=None,
                )
                await message.channel.send(build_new_chat_response())
            except Exception as error:
                logger.exception("Error running DM reset shortcut")
                await message.channel.send(build_error_response(error))
            return

        try:
            async with message.channel.typing():
                answer = await _run_personal_assistant_chat(
                    user_id=message.author.id,
                    channel_id=message.channel.id,
                    guild_id=None,
                    input_text=input_text,
                )
            await _send_discord_text(message.channel.send, build_bot_response(answer))
        except Exception as error:
            logger.exception("Error running DM assistant flow")
            await message.channel.send(build_error_response(error))

    client.assistant_scheduler_runner_getter = get_scheduler_runner
    return client


def run_discord_bot():
    load_dotenv()
    app_health.mark_app_started()
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    if not bot_token:
        raise ValueError("Missing required environment variable: DISCORD_BOT_TOKEN")
    client = create_discord_client()
    try:
        client.run(bot_token)
    finally:
        runner_getter = getattr(client, "assistant_scheduler_runner_getter", None)
        if callable(runner_getter):
            runner = runner_getter()
            if runner is not None:
                runner.stop()
                app_health.set_task_checker_status("stopped")
        app_health.set_bot_status("stopped")

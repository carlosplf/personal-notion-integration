import os
import datetime
import json

import openai
from dotenv import load_dotenv


PROMPT_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "openai_prompt.txt")
)
PROMPT_TEMPLATE_FILE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "openai_prompt_template.txt")
)
DEFAULT_PROMPT = (
    "Você é um assistente de produtividade e deve responder em português para mensagem do Discord."
    "\nObjetivo: priorizar tarefas, explicar rapidamente os motivos e sugerir próximo passo."
    "\n\nFormato obrigatório da resposta (Markdown):"
    "\n## Prioridades de hoje"
    "\n- **[Alta] Nome da tarefa** — motivo curto + tempo estimado"
    "\n- **[Média] Nome da tarefa** — motivo curto + tempo estimado"
    "\n- **[Baixa] Nome da tarefa** — motivo curto + tempo estimado"
    "\n\n## Próximo passo recomendado"
    "\nUma frase objetiva com a melhor ação agora."
    "\n\nRegras:"
    "\n- Não responder em JSON."
    "\n- Seja breve e direto."
    "\n- Se não houver tarefa, escreva exatamente: \"Sem tarefas para priorizar hoje.\""
    "\n- Considere o campo Tags (ex.: TAKES TIME, FAST, FUP) para ajustar a priorização por esforço/contexto."
    "\n- Use o campo projeto para equilibrar prioridades entre contextos (ex.: Pessoal, Draiven, Monks)."
    "\n- Na lista final, para cada tarefa, mostre explicitamente o projeto e uma label de prazo: [ATRASADA] ou [NO PRAZO]."
    "\n\nTarefas:"
)
TASK_PARSER_PROMPT = (
    "Você recebe uma frase para criar uma tarefa no Notion e deve retornar somente JSON válido."
    "\nExtraia os campos: task_name, project, due_date, tags."
    "\nRegras:"
    "\n- due_date deve estar em formato YYYY-MM-DD."
    "\n- tags deve ser uma lista de strings."
    "\n- tags deve representar tipo/complexidade/contexto da tarefa (ex.: FAST, TAKES TIME, FOLLOWUP, DEEP WORK, ADMIN)."
    "\n- tags NÃO deve representar data/período/horário (ex.: amanhã, hoje, manhã, tarde, noite, segunda, urgente amanhã)."
    "\n- Se data não for informada, use a data de hoje."
    "\n- Se projeto não for informado, use \"Pessoal\"."
    "\n- Não inclua texto fora do JSON."
    "\nExemplo de formato:"
    "\n{\"task_name\":\"...\",\"project\":\"Pessoal\",\"due_date\":\"2026-03-01\",\"tags\":[\"FAST\"]}"
)
EVENT_PARSER_PROMPT = (
    "Você recebe uma frase para criar um evento no Google Calendar e deve retornar somente JSON válido."
    "\nExtraia os campos: summary, start_datetime, end_datetime, description, timezone."
    "\nRegras:"
    "\n- Corrija erros gramaticais e normalize o texto do usuário antes de preencher summary/description."
    "\n- O summary deve ser curto, claro e bem escrito."
    "\n- A description deve ser reescrita com gramática correta quando houver texto livre do usuário."
    "\n- start_datetime e end_datetime devem estar em formato YYYY-MM-DDTHH:MM."
    "\n- timezone deve ser um timezone IANA (ex.: America/Sao_Paulo)."
    "\n- Se descrição não for informada, use string vazia."
    "\n- Se timezone não for informado, use \"America/Sao_Paulo\"."
    "\n- Não inclua texto fora do JSON."
    "\nExemplo:"
    "\n{\"summary\":\"Reunião\",\"start_datetime\":\"2026-03-03T10:00\",\"end_datetime\":\"2026-03-03T11:00\",\"description\":\"Kickoff\",\"timezone\":\"America/Sao_Paulo\"}"
)
CALENDAR_SUMMARY_PROMPT = (
    "Você é um assistente e deve resumir eventos da agenda da semana para Discord em português."
    "\nFormato obrigatório em Markdown:"
    "\n## Agenda da semana"
    "\n- **DD/MM HH:MM** — Evento (contexto curto)"
    "\n## Destaques"
    "\n- Linha com conflitos, blocos longos ou janela livre."
    "\nRegras:"
    "\n- Seja breve e útil."
    "\n- Se não houver eventos, responda exatamente: \"Sem eventos na agenda para os próximos 7 dias.\""
)


def call_openai_assistant(tasks, project_logger):
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_KEY")
    if not openai_api_key:
        raise ValueError("Missing required environment variable: OPENAI_KEY")
    openai_client = openai.OpenAI(api_key=openai_api_key)

    project_logger.info("Calling ChatGPT. This can take a while...")

    completion = openai_client.responses.create(
        model="gpt-4.1-mini",
        input=build_message(tasks),
    )

    answer = completion.output_text

    return answer


def parse_add_task_input(user_input, project_logger):
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_KEY")
    if not openai_api_key:
        raise ValueError("Missing required environment variable: OPENAI_KEY")
    openai_client = openai.OpenAI(api_key=openai_api_key)

    project_logger.info("Calling LLM to parse add_task input...")
    completion = openai_client.responses.create(
        model="gpt-4.1-mini",
        input=f"{TASK_PARSER_PROMPT}\n\nInput do usuário:\n{user_input}",
    )
    return parse_add_task_output(completion.output_text)


def summarize_calendar_events(events, project_logger):
    if not events:
        return "Sem eventos na agenda para os próximos 7 dias."

    load_dotenv()
    openai_api_key = os.getenv("OPENAI_KEY")
    if not openai_api_key:
        raise ValueError("Missing required environment variable: OPENAI_KEY")
    openai_client = openai.OpenAI(api_key=openai_api_key)

    project_logger.info("Calling LLM to summarize calendar events...")
    completion = openai_client.responses.create(
        model="gpt-4.1-mini",
        input=build_calendar_events_prompt(events),
    )
    return completion.output_text


def parse_add_event_input(user_input, project_logger):
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_KEY")
    if not openai_api_key:
        raise ValueError("Missing required environment variable: OPENAI_KEY")
    openai_client = openai.OpenAI(api_key=openai_api_key)

    project_logger.info("Calling LLM to parse add_event input...")
    completion = openai_client.responses.create(
        model="gpt-4.1-mini",
        input=f"{EVENT_PARSER_PROMPT}\n\nInput do usuário:\n{user_input}",
    )
    return parse_add_event_output(completion.output_text)


def parse_add_task_output(output_text):
    payload = _extract_json_payload(output_text)
    task_name = str(payload.get("task_name", "")).strip()
    project = str(payload.get("project", "Pessoal")).strip() or "Pessoal"
    due_date = str(payload.get("due_date", "")).strip()
    tags = payload.get("tags", [])

    if not task_name:
        raise ValueError("LLM did not provide task_name")
    if not due_date:
        due_date = datetime.date.today().isoformat()
    try:
        datetime.date.fromisoformat(due_date)
    except ValueError as error:
        raise ValueError("LLM did not provide a valid due_date (YYYY-MM-DD)") from error
    if not isinstance(tags, list):
        raise ValueError("LLM did not provide tags as a list")

    clean_tags = _sanitize_task_tags(tags)
    return {
        "task_name": task_name,
        "project": project,
        "due_date": due_date,
        "tags": clean_tags,
    }


def parse_add_event_output(output_text):
    payload = _extract_json_payload(output_text)
    summary = str(payload.get("summary", "")).strip()
    start_datetime = str(payload.get("start_datetime", "")).strip()
    end_datetime = str(payload.get("end_datetime", "")).strip()
    description = str(payload.get("description", "")).strip()
    timezone = str(payload.get("timezone", "America/Sao_Paulo")).strip() or "America/Sao_Paulo"

    if not summary:
        raise ValueError("LLM did not provide summary")
    _validate_event_datetime(start_datetime, "start_datetime")
    _validate_event_datetime(end_datetime, "end_datetime")

    if end_datetime <= start_datetime:
        raise ValueError("LLM provided end_datetime before or equal to start_datetime")

    return {
        "summary": summary,
        "start_datetime": start_datetime,
        "end_datetime": end_datetime,
        "description": description,
        "timezone": timezone,
    }


def _format_task_for_prompt(task):
    tags = ", ".join(task.get("tags", [])) if task.get("tags") else "sem tag"
    project = task.get("project", "No project")
    deadline = task.get("deadline", "sem data")
    overdue_label = _build_overdue_label(deadline)
    return (
        f"\n - {task['name']} | projeto: {project} | prazo: {deadline}"
        f" | status_prazo: {overdue_label} | tags: {tags}"
    )


def _build_overdue_label(deadline):
    if not deadline:
        return "NO PRAZO"
    try:
        deadline_date = datetime.date.fromisoformat(str(deadline).split("T")[0])
        return "ATRASADA" if deadline_date < datetime.date.today() else "NO PRAZO"
    except ValueError:
        return "NO PRAZO"


def _extract_json_payload(output_text):
    text = str(output_text or "").strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("LLM did not return valid JSON")
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as error:
            raise ValueError("LLM did not return valid JSON") from error


def _sanitize_task_tags(tags):
    blocked_terms = {
        "amanha", "amanhã", "hoje", "ontem",
        "manha", "manhã", "tarde", "noite",
        "segunda", "terca", "terça", "quarta", "quinta", "sexta", "sabado", "sábado", "domingo",
    }
    clean = []
    for tag in tags:
        value = str(tag).strip()
        if not value:
            continue
        normalized = value.lower()
        if normalized in blocked_terms:
            continue
        clean.append(value)
    return clean


def _validate_event_datetime(value, field_name):
    try:
        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError as error:
        raise ValueError(f"LLM did not provide a valid {field_name} (YYYY-MM-DDTHH:MM)") from error


def build_calendar_events_prompt(events):
    event_lines = "".join(
        f"\n - {event.get('summary', 'Sem título')} | start: {event.get('start')} | end: {event.get('end')} | location: {event.get('location') or 'N/A'}"
        for event in events
    )
    return f"{CALENDAR_SUMMARY_PROMPT}\n\nEventos:{event_lines}"


def build_message(tasks):
    task_lines = "".join(_format_task_for_prompt(task) for task in tasks)

    for prompt_path in (PROMPT_FILE_PATH, PROMPT_TEMPLATE_FILE_PATH):
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as prompt_file:
                prompt = prompt_file.read().rstrip()
            return f"{prompt}{task_lines}"

    return f"{DEFAULT_PROMPT}{task_lines}"

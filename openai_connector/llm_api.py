import os
import datetime
import json

import openai
from dotenv import load_dotenv


DEFAULT_LLM_MODEL = "gpt-4.1-mini"
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
NOTE_PARSER_PROMPT = (
    "Você recebe uma frase para criar uma anotação no Notion e deve retornar somente JSON válido."
    "\nExtraia os campos: note_name, tag, observations, url."
    "\nRegras:"
    "\n- note_name deve ser curto e claro."
    "\n- tag deve ser coerente com o tema principal da anotação e conter uma única categoria."
    "\n- observations deve conter o conteúdo principal da anotação."
    "\n- url deve conter link válido (http/https) quando houver; caso contrário, string vazia."
    "\n- Não inclua texto fora do JSON."
    "\nExemplo:"
    "\n{\"note_name\":\"Ideia para onboarding\",\"tag\":\"IDEA\",\"observations\":\"Criar checklist inicial para novos clientes.\",\"url\":\"\"}"
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
DAY_SUMMARY_PROMPT = (
    "Você é um assistente pessoal e deve gerar um resumo do dia para Discord em português."
    "\nFormato obrigatório em Markdown:"
    "\n## Resumo do dia"
    "\n### Tarefas de hoje"
    "\n- **HH:MM ou Dia inteiro** — Tarefa (Projeto) [Tags]"
    "\n### Agenda de hoje"
    "\n- **HH:MM ou Dia inteiro** — Evento (local opcional)"
    "\n### Foco recomendado"
    "\n- 1 a 3 bullets curtos com prioridade e próximo passo."
    "\nRegras:"
    "\n- Seja objetivo, claro e organizado."
    "\n- Não responder em JSON."
    "\n- Se não houver tarefas e nem eventos hoje, responda exatamente:"
    "\n\"## Resumo do dia\\n\\nSem tarefas e sem eventos para hoje.\""
)


def call_openai_assistant(tasks, project_logger):
    openai_client = _create_openai_client()
    llm_model = _get_llm_model()

    project_logger.info("Calling ChatGPT. This can take a while...")

    completion = openai_client.responses.create(
        model=llm_model,
        input=build_message(tasks),
    )

    answer = completion.output_text

    return answer


def parse_add_task_input(user_input, project_logger):
    openai_client = _create_openai_client()
    llm_model = _get_llm_model()

    project_logger.info("Calling LLM to parse add_task input...")
    completion = openai_client.responses.create(
        model=llm_model,
        input=f"{TASK_PARSER_PROMPT}\n\nInput do usuário:\n{user_input}",
    )
    return parse_add_task_output(completion.output_text)


def summarize_calendar_events(events, project_logger):
    if not events:
        return "Sem eventos na agenda para os próximos 7 dias."

    openai_client = _create_openai_client()
    llm_model = _get_llm_model()

    project_logger.info("Calling LLM to summarize calendar events...")
    completion = openai_client.responses.create(
        model=llm_model,
        input=build_calendar_events_prompt(events),
    )
    return completion.output_text


def parse_add_event_input(user_input, project_logger):
    openai_client = _create_openai_client()
    llm_model = _get_llm_model()

    project_logger.info("Calling LLM to parse add_event input...")
    completion = openai_client.responses.create(
        model=llm_model,
        input=f"{EVENT_PARSER_PROMPT}\n\nInput do usuário:\n{user_input}",
    )
    return parse_add_event_output(completion.output_text)


def parse_add_note_input(user_input, project_logger):
    openai_client = _create_openai_client()
    llm_model = _get_llm_model()

    project_logger.info("Calling LLM to parse add_note input...")
    completion = openai_client.responses.create(
        model=llm_model,
        input=f"{NOTE_PARSER_PROMPT}\n\nInput do usuário:\n{user_input}",
    )
    return parse_add_note_output(completion.output_text)


def summarize_day_context(today_tasks, today_events, project_logger):
    return summarize_period_context("hoje", today_tasks, today_events, project_logger)


def summarize_period_context(period_label, tasks, events, project_logger):
    if not tasks and not events:
        return _build_empty_period_message(period_label)

    openai_client = _create_openai_client()
    llm_model = _get_llm_model()

    project_logger.info("Calling LLM to summarize %s context...", period_label)
    completion = openai_client.responses.create(
        model=llm_model,
        input=build_period_summary_prompt(period_label, tasks, events),
    )
    return completion.output_text


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


def parse_add_note_output(output_text):
    payload = _extract_json_payload(output_text)
    note_name = str(payload.get("note_name") or payload.get("name") or "").strip()
    tag = str(payload.get("tag", "")).strip()
    observations = str(payload.get("observations") or payload.get("notes") or "").strip()
    url = str(payload.get("url", "")).strip()

    if not note_name:
        raise ValueError("LLM did not provide note_name")
    if not tag:
        tag = _infer_note_tag(f"{note_name} {observations}")

    return {
        "note_name": note_name,
        "tag": tag,
        "observations": observations,
        "url": url,
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


def _infer_note_tag(content):
    text = str(content or "").lower()
    if any(keyword in text for keyword in ("reunião", "reuniao", "meeting", "call", "1:1")):
        return "MEETING"
    if any(keyword in text for keyword in ("ideia", "idea", "brainstorm", "insight")):
        return "IDEA"
    if any(keyword in text for keyword in ("bug", "erro", "falha", "issue")):
        return "BUG"
    if any(keyword in text for keyword in ("estudo", "study", "curso", "aprender", "learn")):
        return "STUDY"
    if any(keyword in text for keyword in ("saúde", "saude", "treino", "health")):
        return "HEALTH"
    return "GENERAL"


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


def build_day_summary_prompt(today_tasks, today_events):
    return build_period_summary_prompt("hoje", today_tasks, today_events)


def build_period_summary_prompt(period_label, tasks, events):
    period_key = str(period_label or "hoje").strip().lower()
    summary_title = _build_period_summary_title(period_key)
    empty_target = _build_period_empty_target(period_key)
    empty_message = _build_empty_period_message(period_key)
    section_tasks = _build_period_task_section_title(period_key)
    section_events = _build_period_event_section_title(period_key)

    if _is_week_period(period_key):
        prompt_header = (
            f"Você é um assistente pessoal e deve gerar um resumo {summary_title} para Discord em português."
            "\nFormato obrigatório em Markdown:"
            f"\n## Resumo {summary_title}"
            f"\n### {section_tasks}"
            "\n- 3 a 6 bullets curtos agrupando prioridades por contexto/projeto."
            f"\n### {section_events}"
            "\n- 3 a 6 bullets com blocos importantes, conflitos e janelas livres."
            "\n### Foco recomendado"
            "\n- 1 a 3 bullets curtos com prioridade e próximo passo."
            "\nRegras:"
            "\n- Seja objetivo, claro e organizado."
            "\n- Não responder em JSON."
            "\n- Não liste todas as tarefas ou eventos individualmente; sintetize os principais pontos."
            f"\n- Se não houver tarefas e nem eventos para {empty_target}, responda exatamente:"
            f"\n\"{empty_message.replace(chr(10), '\\\\n')}\""
        )
    else:
        prompt_header = (
            f"Você é um assistente pessoal e deve gerar um resumo {summary_title} para Discord em português."
            "\nFormato obrigatório em Markdown:"
            f"\n## Resumo {summary_title}"
            f"\n### {section_tasks}"
            "\n- **HH:MM ou Dia inteiro** — Tarefa (Projeto) [Tags]"
            f"\n### {section_events}"
            "\n- **HH:MM ou Dia inteiro** — Evento (local opcional)"
            "\n### Foco recomendado"
            "\n- 1 a 3 bullets curtos com prioridade e próximo passo."
            "\nRegras:"
            "\n- Seja objetivo, claro e organizado."
            "\n- Não responder em JSON."
            f"\n- Se não houver tarefas e nem eventos para {empty_target}, responda exatamente:"
            f"\n\"{empty_message.replace(chr(10), '\\\\n')}\""
        )

    task_lines = "".join(
        f"\n - {task.get('name', 'Sem nome')} | projeto: {task.get('project', 'Sem projeto')} | "
        f"deadline: {task.get('deadline', 'sem data')} | tags: {', '.join(task.get('tags', [])) if task.get('tags') else 'sem tags'}"
        for task in tasks
    ) or "\n - Sem tarefas"

    event_lines = "".join(
        f"\n - {event.get('summary', 'Sem título')} | start: {event.get('start', 'sem início')} | "
        f"end: {event.get('end', 'sem fim')} | location: {event.get('location') or 'N/A'}"
        for event in events
    ) or "\n - Sem eventos"

    return f"{prompt_header}\n\n{section_tasks}:{task_lines}\n\n{section_events}:{event_lines}"


def _build_empty_period_message(period_key):
    summary_title = _build_period_summary_title(period_key)
    empty_target = _build_period_empty_target(period_key)
    return f"## Resumo {summary_title}\n\nSem tarefas e sem eventos para {empty_target}."


def _build_period_summary_title(period_key):
    if period_key in ("amanha", "amanhã", "tomorrow"):
        return "de amanhã"
    if period_key in ("semana", "semana atual", "week"):
        return "da semana atual"
    return "de hoje"


def _build_period_empty_target(period_key):
    if period_key in ("amanha", "amanhã", "tomorrow"):
        return "amanhã"
    if period_key in ("semana", "semana atual", "week"):
        return "esta semana"
    return "hoje"


def _build_period_task_section_title(period_key):
    if period_key in ("amanha", "amanhã", "tomorrow"):
        return "Tarefas de amanhã"
    if period_key in ("semana", "semana atual", "week"):
        return "Tarefas da semana"
    return "Tarefas de hoje"


def _build_period_event_section_title(period_key):
    if period_key in ("amanha", "amanhã", "tomorrow"):
        return "Agenda de amanhã"
    if period_key in ("semana", "semana atual", "week"):
        return "Agenda da semana"
    return "Agenda de hoje"


def _is_week_period(period_key):
    return period_key in ("semana", "semana atual", "week")


def build_message(tasks):
    task_lines = "".join(_format_task_for_prompt(task) for task in tasks)

    for prompt_path in (PROMPT_FILE_PATH, PROMPT_TEMPLATE_FILE_PATH):
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as prompt_file:
                prompt = prompt_file.read().rstrip()
            return f"{prompt}{task_lines}"

    return f"{DEFAULT_PROMPT}{task_lines}"


def _create_openai_client():
    load_dotenv()
    openai_api_key = os.getenv("OPENAI_KEY")
    if not openai_api_key:
        raise ValueError("Missing required environment variable: OPENAI_KEY")
    return openai.OpenAI(api_key=openai_api_key)


def _get_llm_model():
    load_dotenv()
    llm_model = str(os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL)).strip()
    return llm_model or DEFAULT_LLM_MODEL

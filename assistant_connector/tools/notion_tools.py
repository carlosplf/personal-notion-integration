from __future__ import annotations

import datetime
import re

from notion_connector import notion_connector

_CATEGORY_KEYWORDS = {
    "Alimentação": ("mercado", "restaurante", "ifood", "lanche", "almoço", "jantar", "cafe"),
    "Transporte": ("uber", "99", "taxi", "ônibus", "onibus", "combustivel", "gasolina", "pedagio"),
    "Moradia": ("aluguel", "condominio", "energia", "luz", "agua", "internet", "gás", "gas"),
    "Saúde": ("farmacia", "remedio", "consulta", "exame", "plano de saude", "hospital"),
    "Lazer": ("cinema", "streaming", "show", "viagem", "bar"),
}
_CATEGORY_ALIASES = {
    "alimentacao": "Alimentação",
    "alimentação": "Alimentação",
    "mercado": "Alimentação",
    "transporte": "Transporte",
    "mobilidade": "Transporte",
    "moradia": "Moradia",
    "casa": "Moradia",
    "saude": "Saúde",
    "saúde": "Saúde",
    "lazer": "Lazer",
    "outros": "Outros",
}
_SUGGESTION_SUGAR_KEYWORDS = ("refrigerante", "suco", "bolo", "doce", "chocolate", "sorvete")
_SUGGESTION_VEGETABLE_KEYWORDS = ("salada", "alface", "brocolis", "brócolis", "legume", "verdura")
_ALLOWED_MEAL_CATEGORIES = ("ALMOÇO", "JANTAR", "LANCHE", "CAFÉ DA MANHÃ")
_MEAL_CATEGORY_ALIASES = {
    "almoco": "ALMOÇO",
    "almoço": "ALMOÇO",
    "jantar": "JANTAR",
    "lanche": "LANCHE",
    "cafe da manha": "CAFÉ DA MANHÃ",
    "café da manhã": "CAFÉ DA MANHÃ",
    "cafe da manhã": "CAFÉ DA MANHÃ",
    "café da manha": "CAFÉ DA MANHÃ",
    "cafe": "CAFÉ DA MANHÃ",
    "breakfast": "CAFÉ DA MANHÃ",
}


def _infer_expense_category(description):
    normalized = description.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return category
    return "Outros"


def _normalize_expense_category(raw_category, description):
    category = str(raw_category or "").strip()
    if not category:
        return _infer_expense_category(description)
    normalized = category.lower()
    return _CATEGORY_ALIASES.get(normalized, category.title())


def _month_bounds(target_date):
    month_start = target_date.replace(day=1)
    if month_start.month == 12:
        next_month = datetime.date(month_start.year + 1, 1, 1)
    else:
        next_month = datetime.date(month_start.year, month_start.month + 1, 1)
    return month_start, (next_month - datetime.timedelta(days=1))


def _normalize_meal_category(raw_value):
    meal_category = str(raw_value or "").strip()
    if not meal_category:
        raise ValueError("refeicao is required")

    normalized = meal_category.lower()
    normalized = (
        normalized.replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("ã", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    canonical = _MEAL_CATEGORY_ALIASES.get(normalized)
    if canonical:
        return canonical

    if meal_category in _ALLOWED_MEAL_CATEGORIES:
        return meal_category
    raise ValueError(f"refeicao must be one of: {', '.join(_ALLOWED_MEAL_CATEGORIES)}")


def list_notion_tasks(arguments, context):
    n_days = max(int(arguments.get("n_days", 0)), 0)
    limit = int(arguments.get("limit", 10))
    limit = min(max(limit, 1), 50)

    tasks = notion_connector.collect_tasks_from_control_panel(
        n_days=n_days,
        project_logger=context.project_logger,
    )
    return {
        "total": len(tasks),
        "returned": min(limit, len(tasks)),
        "tasks": tasks[:limit],
    }


def list_notion_notes(arguments, context):
    days_back = max(int(arguments.get("days_back", 5)), 0)
    days_forward = max(int(arguments.get("days_forward", 5)), 0)
    limit = int(arguments.get("limit", 20))
    limit = min(max(limit, 1), 100)

    notes = notion_connector.collect_notes_around_today(
        days_back=days_back,
        days_forward=days_forward,
        project_logger=context.project_logger,
    )
    return {
        "total": len(notes),
        "returned": min(limit, len(notes)),
        "notes": notes[:limit],
    }


def create_notion_task(arguments, context):
    task_name = str(arguments.get("task_name", "")).strip()
    if not task_name:
        raise ValueError("task_name is required")

    project = str(arguments.get("project", "Pessoal")).strip() or "Pessoal"
    due_date = str(arguments.get("due_date", datetime.date.today().isoformat())).strip()
    datetime.date.fromisoformat(due_date)

    tags = arguments.get("tags", [])
    if not isinstance(tags, list):
        raise ValueError("tags must be a list")

    clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]

    return notion_connector.create_task_in_control_panel(
        {
            "task_name": task_name,
            "project": project,
            "due_date": due_date,
            "tags": clean_tags,
        },
        project_logger=context.project_logger,
    )


def create_notion_note(arguments, context):
    note_name = str(arguments.get("note_name", "")).strip()
    if not note_name:
        raise ValueError("note_name is required")

    tag = str(arguments.get("tag", "GENERAL")).strip() or "GENERAL"
    observations = str(arguments.get("observations", ""))
    url = str(arguments.get("url", "")).strip()

    return notion_connector.create_note_in_notes_db(
        {
            "note_name": note_name,
            "tag": tag,
            "observations": observations,
            "url": url,
        },
        project_logger=context.project_logger,
    )


def edit_notion_item(arguments, context):
    item_type = str(arguments.get("item_type", "")).strip().lower()
    if item_type not in {"task", "card"}:
        raise ValueError("item_type must be 'task' or 'card'")

    page_id = str(arguments.get("page_id", "")).strip()
    if not page_id:
        raise ValueError("page_id is required")

    payload = {
        "item_type": item_type,
        "page_id": page_id,
    }
    content = None
    if "content" in arguments:
        raw_content = str(arguments.get("content", ""))
        if raw_content.strip():
            content = raw_content
            payload["content"] = raw_content
    if "content_mode" in arguments and content is not None:
        content_mode = str(arguments.get("content_mode", "")).strip().lower()
        if content_mode and content_mode not in {"append", "replace"}:
            raise ValueError("content_mode must be 'append' or 'replace'")
        if content_mode:
            payload["content_mode"] = content_mode

    if item_type == "task":
        if "task_name" in arguments:
            task_name = str(arguments.get("task_name", "")).strip()
            if task_name:
                payload["task_name"] = task_name
        if "due_date" in arguments:
            due_date = str(arguments.get("due_date", "")).strip()
            if due_date:
                datetime.date.fromisoformat(due_date)
                payload["due_date"] = due_date
        if "project" in arguments:
            project = str(arguments.get("project", "")).strip()
            if project:
                payload["project"] = project
        if "tags" in arguments:
            tags = arguments.get("tags", [])
            if not isinstance(tags, list):
                raise ValueError("tags must be a list")
            clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
            if clean_tags:
                payload["tags"] = clean_tags
        if "done" in arguments:
            payload["done"] = bool(arguments.get("done"))
        if set(payload.keys()) == {"item_type", "page_id"}:
            raise ValueError("At least one task field is required")
    else:
        if "note_name" in arguments:
            note_name = str(arguments.get("note_name", "")).strip()
            if note_name:
                payload["note_name"] = note_name
        if "tag" in arguments:
            tag = str(arguments.get("tag", "")).strip()
            if tag:
                payload["tag"] = tag
        if "observations" in arguments:
            observations = str(arguments.get("observations", ""))
            if observations.strip():
                payload["observations"] = observations
        if "url" in arguments:
            url = str(arguments.get("url", "")).strip()
            if url:
                payload["url"] = url
        if "date" in arguments:
            date_value = str(arguments.get("date", "")).strip()
            if date_value:
                datetime.date.fromisoformat(date_value)
                payload["date"] = date_value
        if set(payload.keys()) == {"item_type", "page_id"}:
            raise ValueError("At least one card field is required")

    return notion_connector.update_notion_page(payload, project_logger=context.project_logger)


def register_financial_expense(arguments, context):
    description = str(arguments.get("description", "")).strip()
    if not description:
        raise ValueError("description is required")

    raw_amount = str(arguments.get("amount", "")).strip().replace(",", ".")
    amount = float(raw_amount)
    if amount <= 0:
        raise ValueError("amount must be greater than zero")

    expense_date_raw = str(arguments.get("expense_date", datetime.date.today().isoformat())).strip()
    expense_date = datetime.date.fromisoformat(expense_date_raw)
    category = _normalize_expense_category(arguments.get("category"), description)
    create_result = notion_connector.create_expense_in_expenses_db(
        {
            "name": f"Despesa {expense_date.isoformat()}",
            "date": expense_date.isoformat(),
            "category": category,
            "description": description,
            "amount": amount,
        },
        project_logger=context.project_logger,
    )
    return {
        "status": "created",
        "expense_id": create_result.get("id"),
        "expense": {
            "date": expense_date.isoformat(),
            "amount": amount,
            "category": category,
            "description": description,
        },
    }


def register_notion_meal(arguments, context):
    food = str(arguments.get("alimento", arguments.get("food", ""))).strip()
    meal_type = _normalize_meal_category(arguments.get("refeicao", arguments.get("meal_type", "")))
    quantity = str(arguments.get("quantidade", arguments.get("quantity", ""))).strip()
    meal_date = str(arguments.get("data", arguments.get("date", datetime.date.today().isoformat()))).strip()
    estimated_calories = arguments.get("calorias_estimadas", arguments.get("estimated_calories"))
    if not food:
        raise ValueError("alimento is required")
    if not quantity:
        raise ValueError("quantidade is required")
    datetime.date.fromisoformat(meal_date)

    created_meal = notion_connector.create_meal_in_meals_db(
        {
            "food": food,
            "meal_type": meal_type,
            "quantity": quantity,
            "date": meal_date,
            "estimated_calories": estimated_calories,
        },
        project_logger=context.project_logger,
    )
    return {
        "status": "created",
        "meal": created_meal,
    }


def analyze_notion_meals(arguments, context):
    days_back = max(int(arguments.get("days_back", 7)), 0)
    days_forward = max(int(arguments.get("days_forward", 0)), 0)
    limit = int(arguments.get("limit", 100))
    limit = min(max(limit, 1), 300)

    today = datetime.date.today()
    start_date = today - datetime.timedelta(days=days_back)
    end_date = today + datetime.timedelta(days=days_forward)
    start_datetime = f"{start_date.isoformat()}T00:00:00Z"
    end_datetime = f"{end_date.isoformat()}T23:59:59Z"

    meals = notion_connector.collect_meals_from_database(
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        project_logger=context.project_logger,
    )
    selected_meals = meals[:limit]
    total_calories = round(sum(float(meal.get("calories") or 0.0) for meal in selected_meals), 2)

    by_meal_type = {}
    by_food = {}
    covered_days = set()
    for meal in selected_meals:
        meal_day = str(meal.get("date") or "")[:10]
        if meal_day:
            covered_days.add(meal_day)
        else:
            created_time = str(meal.get("created_time") or "")
            if created_time:
                covered_days.add(created_time[:10])
        meal_type = str(meal.get("meal_type") or "Não informado")
        by_meal_type.setdefault(meal_type, {"meal_type": meal_type, "entries": 0, "calories": 0.0})
        by_meal_type[meal_type]["entries"] += 1
        by_meal_type[meal_type]["calories"] += float(meal.get("calories") or 0.0)

        food_name = str(meal.get("food") or "").strip()
        if food_name:
            key = food_name.lower()
            by_food.setdefault(key, {"food": food_name, "entries": 0, "calories": 0.0})
            by_food[key]["entries"] += 1
            by_food[key]["calories"] += float(meal.get("calories") or 0.0)

    meal_breakdown = [
        {
            "meal_type": payload["meal_type"],
            "entries": payload["entries"],
            "calories": round(payload["calories"], 2),
        }
        for payload in sorted(by_meal_type.values(), key=lambda item: item["calories"], reverse=True)
    ]
    top_foods = [
        {
            "food": payload["food"],
            "entries": payload["entries"],
            "calories": round(payload["calories"], 2),
        }
        for payload in sorted(by_food.values(), key=lambda item: item["calories"], reverse=True)[:5]
    ]
    days_count = len(covered_days)
    average_calories_per_day = round(total_calories / days_count, 2) if days_count else 0.0
    insights = _build_meal_insights(selected_meals, meal_breakdown, average_calories_per_day)

    return {
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        "total_entries": len(meals),
        "returned_entries": len(selected_meals),
        "days_with_entries": days_count,
        "total_calories": total_calories,
        "average_calories_per_day": average_calories_per_day,
        "meal_breakdown": meal_breakdown,
        "top_foods": top_foods,
        "insights": insights,
        "meals": selected_meals,
    }


def _build_meal_insights(meals, meal_breakdown, average_calories_per_day):
    insights = []
    if not meals:
        return ["Nenhum registro encontrado no período. Registre refeições para receber sugestões."]

    if average_calories_per_day > 2500:
        insights.append(
            "Média calórica diária acima de 2500 kcal. Avalie reduzir porções muito calóricas e incluir mais vegetais."
        )
    elif average_calories_per_day < 1200:
        insights.append(
            "Média calórica diária abaixo de 1200 kcal. Verifique se o registro está completo e mantenha ingestão equilibrada."
        )

    dinner_aliases = {"jantar", "dinner", "ceia"}
    dinner_entry = next(
        (entry for entry in meal_breakdown if str(entry.get("meal_type", "")).strip().lower() in dinner_aliases),
        None,
    )
    total_calories = sum(float(meal.get("calories") or 0.0) for meal in meals)
    if dinner_entry and total_calories > 0 and (dinner_entry["calories"] / total_calories) >= 0.45:
        insights.append(
            "Mais de 45% das calorias estão concentradas no jantar/ceia. Distribuir melhor entre as refeições pode ajudar."
        )

    normalized_foods = " ".join(str(meal.get("food") or "").lower() for meal in meals)
    sugary_occurrences = sum(1 for keyword in _SUGGESTION_SUGAR_KEYWORDS if keyword in normalized_foods)
    if sugary_occurrences >= 2:
        insights.append(
            "Há vários itens açucarados nos registros. Considere reduzir doces e bebidas açucaradas ao longo da semana."
        )

    has_vegetables = any(keyword in normalized_foods for keyword in _SUGGESTION_VEGETABLE_KEYWORDS)
    if not has_vegetables:
        insights.append(
            "Não há indícios de verduras/legumes nas refeições registradas. Tente incluir vegetais em almoço e jantar."
        )

    if not insights:
        insights.append("Boa consistência nos registros. Continue monitorando porções e variedade nutricional.")
    return insights


def analyze_monthly_expenses(arguments, context):
    month_value = str(arguments.get("month", "")).strip()
    if month_value:
        if not re.fullmatch(r"\d{4}-\d{2}", month_value):
            raise ValueError("month must follow YYYY-MM")
        target_date = datetime.date.fromisoformat(f"{month_value}-01")
    else:
        target_date = datetime.date.today().replace(day=1)
    month_key = target_date.strftime("%Y-%m")
    month_start, month_end = _month_bounds(target_date)
    expenses = notion_connector.collect_expenses_from_expenses_db(
        start_date=month_start.isoformat(),
        end_date=month_end.isoformat(),
        project_logger=context.project_logger,
    )
    if not expenses:
        return {
            "month": month_key,
            "total_spent": 0.0,
            "expenses_count": 0,
            "breakdown_by_category": [],
            "top_expense": None,
        }

    total_spent = round(sum(expense["amount"] for expense in expenses), 2)
    by_category = {}
    for expense in expenses:
        category = expense["category"]
        by_category[category] = by_category.get(category, 0.0) + expense["amount"]
    breakdown = [
        {"category": category, "total": round(amount, 2)}
        for category, amount in sorted(by_category.items(), key=lambda item: item[1], reverse=True)
    ]
    top_expense = max(expenses, key=lambda expense: expense["amount"]) if expenses else None
    if top_expense:
        top_expense = {
            "date": top_expense["date"],
            "amount": round(top_expense["amount"], 2),
            "category": top_expense["category"],
            "description": top_expense["description"],
        }

    return {
        "month": month_key,
        "total_spent": total_spent,
        "expenses_count": len(expenses),
        "breakdown_by_category": breakdown,
        "top_expense": top_expense,
    }


def list_unpaid_monthly_bills(arguments, context):
    month_value = str(arguments.get("month", "")).strip()
    if month_value:
        if not re.fullmatch(r"\d{4}-\d{2}", month_value):
            raise ValueError("month must follow YYYY-MM")
        target_date = datetime.date.fromisoformat(f"{month_value}-01")
    else:
        target_date = datetime.date.today().replace(day=1)
    limit = int(arguments.get("limit", 30))
    limit = min(max(limit, 1), 100)

    month_start, month_end = _month_bounds(target_date)
    bills = notion_connector.collect_monthly_bills_from_database(
        start_date=month_start.isoformat(),
        end_date=month_end.isoformat(),
        unpaid_only=True,
        project_logger=context.project_logger,
    )
    return {
        "month": target_date.strftime("%Y-%m"),
        "total": len(bills),
        "returned": min(len(bills), limit),
        "bills": bills[:limit],
    }


def mark_monthly_bill_as_paid(arguments, context):
    page_id = str(arguments.get("page_id", "")).strip()
    if not page_id:
        raise ValueError("page_id is required")

    paid_amount = arguments.get("paid_amount")
    normalized_paid_amount = None
    if paid_amount is not None:
        normalized_paid_amount = float(str(paid_amount).replace(",", "."))
        if normalized_paid_amount < 0:
            raise ValueError("paid_amount must be >= 0")

    payment_date = str(arguments.get("payment_date", "")).strip() or None
    if payment_date:
        datetime.date.fromisoformat(payment_date)

    result = notion_connector.update_monthly_bill_payment(
        page_id=page_id,
        paid=True,
        paid_amount=normalized_paid_amount,
        payment_date=payment_date,
        project_logger=context.project_logger,
    )
    return {
        "status": "updated",
        "bill_id": result.get("id"),
        "paid": result.get("paid", True),
        "paid_amount": result.get("paid_amount"),
        "payment_date": result.get("payment_date"),
    }


def analyze_monthly_bills(arguments, context):
    month_value = str(arguments.get("month", "")).strip()
    if month_value:
        if not re.fullmatch(r"\d{4}-\d{2}", month_value):
            raise ValueError("month must follow YYYY-MM")
        target_date = datetime.date.fromisoformat(f"{month_value}-01")
    else:
        target_date = datetime.date.today().replace(day=1)

    month_start, month_end = _month_bounds(target_date)
    bills = notion_connector.collect_monthly_bills_from_database(
        start_date=month_start.isoformat(),
        end_date=month_end.isoformat(),
        unpaid_only=False,
        project_logger=context.project_logger,
    )
    if not bills:
        return {
            "month": target_date.strftime("%Y-%m"),
            "total_bills": 0,
            "paid_count": 0,
            "unpaid_count": 0,
            "total_budget": 0.0,
            "total_paid_amount": 0.0,
            "pending_budget": 0.0,
            "breakdown_by_category": [],
        }

    total_budget = round(sum(bill["budget"] for bill in bills), 2)
    total_paid_amount = round(sum(bill["paid_amount"] for bill in bills), 2)
    paid_count = sum(1 for bill in bills if bill["paid"])
    unpaid_count = len(bills) - paid_count
    pending_budget = round(sum(bill["budget"] for bill in bills if not bill["paid"]), 2)

    by_category = {}
    for bill in bills:
        category = bill["category"]
        category_values = by_category.setdefault(
            category,
            {"category": category, "total_budget": 0.0, "total_paid": 0.0, "unpaid_count": 0},
        )
        category_values["total_budget"] += bill["budget"]
        category_values["total_paid"] += bill["paid_amount"]
        if not bill["paid"]:
            category_values["unpaid_count"] += 1
    breakdown_by_category = [
        {
            "category": item["category"],
            "total_budget": round(item["total_budget"], 2),
            "total_paid": round(item["total_paid"], 2),
            "unpaid_count": item["unpaid_count"],
        }
        for item in sorted(by_category.values(), key=lambda value: value["total_budget"], reverse=True)
    ]

    return {
        "month": target_date.strftime("%Y-%m"),
        "total_bills": len(bills),
        "paid_count": paid_count,
        "unpaid_count": unpaid_count,
        "total_budget": total_budget,
        "total_paid_amount": total_paid_amount,
        "pending_budget": pending_budget,
        "breakdown_by_category": breakdown_by_category,
    }

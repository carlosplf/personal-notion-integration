import unittest
import datetime
import requests
from unittest.mock import patch

from notion_connector import notion_connector
from utils.timezone_utils import today_iso_in_configured_timezone


class _MockResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)
        return None


class _MockLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None

    def error(self, *_args, **_kwargs):
        return None


class TestNotionConnector(unittest.TestCase):
    def test_build_notion_rich_text_chunks_preserves_markdown_annotations(self):
        rich_text = notion_connector._build_notion_rich_text_chunks(
            "Texto **negrito** *italico* `codigo` [link](https://example.com)"
        )
        self.assertTrue(any(item.get("annotations", {}).get("bold") for item in rich_text))
        self.assertTrue(any(item.get("annotations", {}).get("italic") for item in rich_text))
        self.assertTrue(any(item.get("annotations", {}).get("code") for item in rich_text))
        self.assertTrue(any(item.get("text", {}).get("link", {}).get("url") == "https://example.com" for item in rich_text))

    def test_build_note_children_maps_markdown_blocks(self):
        blocks = notion_connector._build_note_children(
            "# Titulo\n- Item 1\n1. Passo 1\nParagrafo final"
        )
        self.assertEqual(blocks[0]["type"], "heading_1")
        self.assertEqual(blocks[1]["type"], "bulleted_list_item")
        self.assertEqual(blocks[2]["type"], "numbered_list_item")
        self.assertEqual(blocks[3]["type"], "paragraph")

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_tasks_supports_when_property(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse(
            {
                "results": [
                    {
                        "id": "task-1",
                        "properties": {
                            "Task": {
                                "title": [{"plain_text": "Minha tarefa"}]
                            },
                            "When": {
                                "date": {"start": "2026-03-01T10:00:00.000Z"}
                            },
                            "Project": {"select": {"name": "Projeto X"}},
                            "Tags": {
                                "type": "multi_select",
                                "multi_select": [{"name": "FAST"}, {"name": "FUP"}],
                            },
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )

        tasks = notion_connector.collect_tasks_from_control_panel(
            n_days=0,
            project_logger=_MockLogger(),
        )

        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], "task-1")
        self.assertEqual(tasks[0]["name"], "Minha tarefa")
        self.assertEqual(tasks[0]["deadline"], "2026-03-01T10:00:00.000Z")
        self.assertEqual(tasks[0]["project"], "Projeto X")
        self.assertEqual(tasks[0]["tags"], ["FAST", "FUP"])

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_tasks_uses_cutoff_filter_for_overdue_and_upcoming(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"results": [], "has_more": False, "next_cursor": None})

        notion_connector.collect_tasks_from_control_panel(
            n_days=2,
            project_logger=_MockLogger(),
        )

        request_payload = mock_post.call_args.kwargs["json"]
        and_filters = request_payload["filter"]["and"]
        self.assertEqual(and_filters[0]["property"], "DONE")
        self.assertEqual(and_filters[0]["checkbox"]["equals"], False)
        self.assertEqual(and_filters[1]["property"], "When")
        self.assertIn("before", and_filters[1]["date"])

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_task_in_control_panel_posts_expected_fields(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "page-1", "url": "https://notion.so/page-1"})

        result = notion_connector.create_task_in_control_panel(
            {
                "task_name": "Enviar proposta",
                "project": "Draiven",
                "due_date": "2026-03-05",
                "tags": ["FAST", "FUP"],
            },
            project_logger=_MockLogger(),
        )

        self.assertEqual(result["id"], "page-1")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "db-id")
        self.assertIn("Task", payload["properties"])
        self.assertIn("When", payload["properties"])
        self.assertEqual(
            payload["properties"]["Project"]["select"]["name"],
            "Draiven",
        )

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_posts_expected_fields(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"})
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Date": {"type": "date"},
                    "Tags": {"type": "multi_select"},
                    "URL": {"type": "url"},
                    "Observações": {"type": "rich_text"},
                }
            }
        )

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            result = notion_connector.create_note_in_notes_db(
                {
                    "note_name": "Ideia de onboarding",
                    "tag": "IDEA",
                    "observations": "Criar checklist para novos clientes",
                    "url": "https://example.com",
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "note-1")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "notes-db-id")
        self.assertEqual(payload["properties"]["Name"]["title"][0]["text"]["content"], "Ideia de onboarding")
        self.assertEqual(payload["properties"]["Date"]["date"]["start"], today_iso_in_configured_timezone())
        self.assertIn("Tags", payload["properties"])

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_accepts_explicit_date(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"})
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Date": {"type": "date"},
                }
            }
        )

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            notion_connector.create_note_in_notes_db(
                {
                    "note_name": "Financeiro - 2026-04",
                    "tag": "FINANCE",
                    "date": "2026-04-01",
                    "observations": "EXPENSE|date=2026-04-02|amount=10.00|category=Outros|description=Teste",
                    "url": "",
                },
                project_logger=_MockLogger(),
            )

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["properties"]["Date"]["date"]["start"], "2026-04-01")

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_expense_in_expenses_db_posts_expected_fields(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Nome": {"type": "title"},
                    "Data": {"type": "date"},
                    "Categoria": {"type": "select"},
                    "Valor": {"type": "number"},
                    "Descrição": {"type": "rich_text"},
                }
            }
        )
        mock_post.return_value = _MockResponse({"id": "expense-1", "url": "https://notion.so/expense-1"})

        with patch.dict("os.environ", {"NOTION_EXPENSES_DB_ID": "expenses-db-id"}, clear=False):
            result = notion_connector.create_expense_in_expenses_db(
                {
                    "name": "Despesa 2026-04-02",
                    "date": "2026-04-02",
                    "category": "Transporte",
                    "description": "Uber ida",
                    "amount": 33.9,
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "expense-1")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "expenses-db-id")
        self.assertEqual(payload["properties"]["Nome"]["title"][0]["text"]["content"], "Despesa 2026-04-02")
        self.assertEqual(payload["properties"]["Data"]["date"]["start"], "2026-04-02")
        self.assertEqual(payload["properties"]["Categoria"]["select"]["name"], "Transporte")
        self.assertEqual(payload["properties"]["Valor"]["number"], 33.9)
        description_text = payload["properties"]["Descrição"]["rich_text"][0]["text"]["content"]
        self.assertEqual(description_text, "Uber ida")

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_expenses_from_expenses_db_parses_amount(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse(
            {
                "results": [
                    {
                        "id": "expense-1",
                        "url": "https://notion.so/expense-1",
                        "properties": {
                            "Nome": {"title": [{"plain_text": "Despesa 2026-04-02"}]},
                            "Data": {"date": {"start": "2026-04-02"}},
                            "Categoria": {"type": "select", "select": {"name": "Transporte"}},
                            "Valor": {"type": "number", "number": 33.9},
                            "Descrição": {"rich_text": [{"plain_text": "Uber ida"}]},
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )

        with patch.dict("os.environ", {"NOTION_EXPENSES_DB_ID": "expenses-db-id"}, clear=False):
            expenses = notion_connector.collect_expenses_from_expenses_db(
                start_date="2026-04-01",
                end_date="2026-04-30",
                project_logger=_MockLogger(),
            )

        self.assertEqual(len(expenses), 1)
        self.assertEqual(expenses[0]["amount"], 33.9)
        self.assertEqual(expenses[0]["category"], "Transporte")
        self.assertEqual(expenses[0]["description"], "Uber ida")

    def test_estimate_meal_calories_uses_known_reference(self):
        estimation = notion_connector._estimate_meal_calories("Arroz branco", "150 g")
        self.assertEqual(estimation["food_reference"], "arroz branco cozido")
        self.assertEqual(estimation["estimated_calories"], 195.0)

    def test_estimate_meal_calories_uses_local_fallback_for_unknown_food(self):
        estimation = notion_connector._estimate_meal_calories("Comida caseira", "100 g")
        self.assertGreater(estimation["estimated_calories"], 0)
        self.assertEqual(estimation["food_reference"], "generic_estimation")

    def test_estimate_meal_calories_supports_bacon_and_unsweetened_coffee(self):
        bacon = notion_connector._estimate_meal_calories("Bacon", "50 g")
        coffee = notion_connector._estimate_meal_calories("Café sem açúcar", "150 ml")
        self.assertEqual(bacon["estimated_calories"], 270.5)
        self.assertEqual(coffee["estimated_calories"], 3.0)

    def test_estimate_meal_calories_converts_unit_quantity_to_grams(self):
        estimation = notion_connector._estimate_meal_calories("Ovo mexido", "3 ovos")
        self.assertEqual(estimation["quantity_in_grams"], 150.0)
        self.assertEqual(estimation["quantity_in_grams_text"], "150 g")

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_meal_in_meals_db_calculates_and_persists_calories(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Alimento": {"type": "title"},
                    "Refeição": {"type": "select"},
                    "Data": {"type": "date"},
                    "Quantidade": {"type": "rich_text"},
                    "Calorias": {"type": "number"},
                }
            }
        )
        mock_post.return_value = _MockResponse({"id": "meal-1", "url": "https://notion.so/meal-1"})

        with patch.dict("os.environ", {"NOTION_MEALS_DB_ID": "meals-db-id"}, clear=False):
            result = notion_connector.create_meal_in_meals_db(
                {
                    "food": "Arroz branco",
                    "meal_type": "Almoço",
                    "quantity": "150 g",
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "meal-1")
        self.assertEqual(result["calories"], 195.0)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "meals-db-id")
        self.assertEqual(payload["properties"]["Alimento"]["title"][0]["text"]["content"], "Arroz branco")
        self.assertEqual(payload["properties"]["Refeição"]["select"]["name"], "Almoço")
        self.assertEqual(payload["properties"]["Data"]["date"]["start"], today_iso_in_configured_timezone())
        self.assertEqual(payload["properties"]["Quantidade"]["rich_text"][0]["text"]["content"], "150 g")
        self.assertEqual(payload["properties"]["Calorias"]["number"], 195.0)

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_meal_in_meals_db_accepts_llm_estimated_calories(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Alimento": {"type": "title"},
                    "Refeição": {"type": "select"},
                    "Data": {"type": "date"},
                    "Quantidade": {"type": "rich_text"},
                    "Calorias": {"type": "number"},
                }
            }
        )
        mock_post.return_value = _MockResponse({"id": "meal-2", "url": "https://notion.so/meal-2"})

        with patch.dict("os.environ", {"NOTION_MEALS_DB_ID": "meals-db-id"}, clear=False):
            result = notion_connector.create_meal_in_meals_db(
                {
                    "food": "Alimento livre",
                    "meal_type": "Lanche",
                    "quantity": "1 porção",
                    "date": "2026-04-12",
                    "estimated_calories": 230,
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "meal-2")
        self.assertEqual(result["calorie_estimation_method"], "llm_estimate")
        self.assertEqual(result["quantity"], "100 g")
        self.assertEqual(result["quantity_grams"], 100.0)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["properties"]["Quantidade"]["rich_text"][0]["text"]["content"], "100 g")
        self.assertEqual(payload["properties"]["Calorias"]["number"], 230.0)
        self.assertEqual(payload["properties"]["Data"]["date"]["start"], "2026-04-12")

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_meal_in_meals_db_stores_quantity_as_grams_when_property_is_number(
        self, mock_load_credentials, mock_post, mock_get
    ):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Alimento": {"type": "title"},
                    "Refeição": {"type": "select"},
                    "Data": {"type": "date"},
                    "Quantidade": {"type": "number"},
                    "Calorias": {"type": "number"},
                }
            }
        )
        mock_post.return_value = _MockResponse({"id": "meal-3", "url": "https://notion.so/meal-3"})

        with patch.dict("os.environ", {"NOTION_MEALS_DB_ID": "meals-db-id"}, clear=False):
            result = notion_connector.create_meal_in_meals_db(
                {
                    "food": "Ovo mexido",
                    "meal_type": "Café da manhã",
                    "quantity": "3 ovos",
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "meal-3")
        self.assertEqual(result["quantity"], "150 g")
        self.assertEqual(result["quantity_grams"], 150.0)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["properties"]["Quantidade"]["number"], 150.0)

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_meals_from_database_parses_expected_fields(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse(
            {
                "results": [
                    {
                        "id": "meal-1",
                        "url": "https://notion.so/meal-1",
                        "created_time": "2026-04-10T12:00:00.000Z",
                        "properties": {
                            "Alimento": {"title": [{"plain_text": "Frango grelhado"}]},
                            "Refeição": {"type": "select", "select": {"name": "Almoço"}},
                            "Data": {"type": "date", "date": {"start": "2026-04-10"}},
                            "Quantidade": {"type": "rich_text", "rich_text": [{"plain_text": "200 g"}]},
                            "Calorias": {"type": "number", "number": 330.0},
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )

        with patch.dict("os.environ", {"NOTION_MEALS_DB_ID": "meals-db-id"}, clear=False):
            meals = notion_connector.collect_meals_from_database(
                start_datetime="2026-04-01T00:00:00Z",
                end_datetime="2026-04-30T23:59:59Z",
                project_logger=_MockLogger(),
            )

        self.assertEqual(len(meals), 1)
        self.assertEqual(meals[0]["food"], "Frango grelhado")
        self.assertEqual(meals[0]["meal_type"], "Almoço")
        self.assertEqual(meals[0]["quantity"], "200 g")
        self.assertEqual(meals[0]["date"], "2026-04-10")
        self.assertEqual(meals[0]["calories"], 330.0)
        request_payload = mock_post.call_args.kwargs["json"]
        first_filter = request_payload["filter"]["and"][0]
        self.assertEqual(first_filter["property"], "Data")

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_exercise_in_exercises_db_posts_expected_fields(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Atividade": {"type": "title"},
                    "Data": {"type": "date"},
                    "Calorias": {"type": "number"},
                    "Observações": {"type": "rich_text"},
                    "Done": {"type": "checkbox"},
                }
            }
        )
        mock_post.return_value = _MockResponse({"id": "exercise-1", "url": "https://notion.so/exercise-1"})

        with patch.dict("os.environ", {"NOTION_EXERCISES_DB_ID": "exercise-db-id"}, clear=False):
            result = notion_connector.create_exercise_in_exercises_db(
                {
                    "activity": "Corrida leve",
                    "calories": 320,
                    "date": "2026-04-11",
                    "observations": "Treino no parque",
                    "done": False,
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "exercise-1")
        self.assertEqual(result["calories"], 320.0)
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "exercise-db-id")
        self.assertEqual(payload["properties"]["Atividade"]["title"][0]["text"]["content"], "Corrida leve")
        self.assertEqual(payload["properties"]["Data"]["date"]["start"], "2026-04-11")
        self.assertEqual(payload["properties"]["Calorias"]["number"], 320.0)
        self.assertFalse(payload["properties"]["Done"]["checkbox"])

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.patch")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_exercise_in_exercises_db_updates_selected_fields(
        self,
        mock_load_credentials,
        mock_patch,
        mock_get,
    ):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Atividade": {"type": "title"},
                    "Data": {"type": "date"},
                    "Calorias": {"type": "number"},
                    "Observações": {"type": "rich_text"},
                    "Done": {"type": "checkbox"},
                }
            }
        )
        mock_patch.return_value = _MockResponse({"id": "exercise-1", "url": "https://notion.so/exercise-1"})

        with patch.dict("os.environ", {"NOTION_EXERCISES_DB_ID": "exercise-db-id"}, clear=False):
            result = notion_connector.update_exercise_in_exercises_db(
                "https://www.notion.so/workspace/123456781234123412341234567890ab",
                activity="Musculação",
                calories=410,
                done=True,
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "exercise-1")
        self.assertEqual(result["updated_fields"], ["activity", "calories", "done"])
        self.assertIn("12345678-1234-1234-1234-1234567890ab", mock_patch.call_args.args[0])
        payload = mock_patch.call_args.kwargs["json"]
        self.assertEqual(payload["properties"]["Atividade"]["title"][0]["text"]["content"], "Musculação")
        self.assertEqual(payload["properties"]["Calorias"]["number"], 410.0)
        self.assertTrue(payload["properties"]["Done"]["checkbox"])

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_exercises_from_database_parses_expected_fields(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse(
            {
                "results": [
                    {
                        "id": "exercise-1",
                        "url": "https://notion.so/exercise-1",
                        "created_time": "2026-04-10T20:00:00.000Z",
                        "properties": {
                            "Atividade": {"type": "title", "title": [{"plain_text": "Caminhada"}]},
                            "Data": {"type": "date", "date": {"start": "2026-04-10"}},
                            "Calorias": {"type": "rich_text", "rich_text": [{"plain_text": "250"}]},
                            "Observações": {"type": "rich_text", "rich_text": [{"plain_text": "30 min"}]},
                            "Done": {"type": "checkbox", "checkbox": False},
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )

        with patch.dict("os.environ", {"NOTION_EXERCISES_DB_ID": "exercise-db-id"}, clear=False):
            exercises = notion_connector.collect_exercises_from_database(
                start_datetime="2026-04-01T00:00:00Z",
                end_datetime="2026-04-30T23:59:59Z",
                project_logger=_MockLogger(),
            )

        self.assertEqual(len(exercises), 1)
        self.assertEqual(exercises[0]["activity"], "Caminhada")
        self.assertEqual(exercises[0]["date"], "2026-04-10")
        self.assertEqual(exercises[0]["calories"], 250.0)
        self.assertEqual(exercises[0]["observations"], "30 min")
        self.assertFalse(exercises[0]["done"])
        request_payload = mock_post.call_args.kwargs["json"]
        first_filter = request_payload["filter"]["and"][0]
        self.assertEqual(first_filter["property"], "Data")

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_monthly_bills_from_database_parses_expected_fields(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse(
            {
                "results": [
                    {
                        "id": "bill-1",
                        "url": "https://notion.so/bill-1",
                        "properties": {
                            "Nome": {"title": [{"plain_text": "Internet"}]},
                            "Data": {"date": {"start": "2026-04-05"}},
                            "Pago": {"type": "checkbox", "checkbox": False},
                            "Categoria": {"type": "select", "select": {"name": "Casa"}},
                            "Budget": {"type": "number", "number": 120.0},
                            "Valor pago": {"type": "number", "number": 0.0},
                            "Descrição": {"type": "rich_text", "rich_text": [{"plain_text": "Fatura mensal"}]},
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )

        with patch.dict("os.environ", {"NOTION_MONTHLY_BILLS_DB_ID": "monthly-bills-id"}, clear=False):
            bills = notion_connector.collect_monthly_bills_from_database(
                start_date="2026-04-01",
                end_date="2026-04-30",
                unpaid_only=True,
                project_logger=_MockLogger(),
            )

        self.assertEqual(len(bills), 1)
        self.assertEqual(bills[0]["name"], "Internet")
        self.assertFalse(bills[0]["paid"])
        self.assertEqual(bills[0]["budget"], 120.0)
        self.assertEqual(bills[0]["description"], "Fatura mensal")
        request_payload = mock_post.call_args.kwargs["json"]
        paid_filter = request_payload["filter"]["and"][2]
        self.assertEqual(paid_filter["property"], "Pago")
        self.assertEqual(paid_filter["checkbox"]["equals"], False)

    @patch("notion_connector.notion_connector.requests.patch")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_monthly_bill_payment_updates_pago_and_valor_pago(self, mock_load_credentials, mock_patch):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_patch.return_value = _MockResponse({"id": "bill-1", "url": "https://notion.so/bill-1"})

        result = notion_connector.update_monthly_bill_payment(
            page_id="bill-1",
            paid=True,
            paid_amount=120.5,
            payment_date="2026-04-05",
            project_logger=_MockLogger(),
        )

        self.assertEqual(result["id"], "bill-1")
        payload = mock_patch.call_args.kwargs["json"]
        self.assertTrue(payload["properties"]["Pago"]["checkbox"])
        self.assertEqual(payload["properties"]["Valor pago"]["number"], 120.5)
        self.assertEqual(payload["properties"]["Data"]["date"]["start"], "2026-04-05")

    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_monthly_bills_requires_env_var(self, mock_load_credentials):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        with patch.dict("os.environ", {"NOTION_MONTHLY_BILLS_DB_ID": ""}, clear=False):
            with self.assertRaises(ValueError):
                notion_connector.collect_monthly_bills_from_database(
                    start_date="2026-04-01",
                    end_date="2026-04-30",
                    project_logger=_MockLogger(),
                )

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_fallbacks_on_not_found(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Date": {"type": "date"},
                    "Tags": {"type": "multi_select"},
                }
            }
        )
        mock_post.side_effect = [
            _MockResponse({"code": "object_not_found"}, status_code=404),
            _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"}, status_code=200),
        ]

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            result = notion_connector.create_note_in_notes_db(
                {"note_name": "Fallback note", "tag": "GENERAL", "observations": "abc", "url": ""},
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "note-1")
        self.assertEqual(mock_post.call_count, 2)

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_splits_long_observations(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"}, status_code=200)
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Date": {"type": "date"},
                    "Tags": {"type": "multi_select"},
                    "Observações": {"type": "rich_text"},
                }
            }
        )

        long_observations = "x" * 4200
        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            notion_connector.create_note_in_notes_db(
                {
                    "note_name": "Long note",
                    "tag": "GENERAL",
                    "observations": long_observations,
                    "url": "",
                },
                project_logger=_MockLogger(),
            )

        payload = mock_post.call_args.kwargs["json"]
        rich_text = payload["properties"]["Observações"]["rich_text"]
        self.assertGreater(len(rich_text), 1)
        self.assertTrue(all(len(item["text"]["content"]) <= 1800 for item in rich_text))
        self.assertNotIn("children", payload)

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_normalizes_database_id_from_url(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse({"id": "note-1", "url": "https://notion.so/note-1"}, status_code=200)
        mock_get.return_value = _MockResponse(
            {"properties": {"Name": {"type": "title"}, "Date": {"type": "date"}}}
        )
        notes_url = "https://www.notion.so/workspace/123456781234123412341234567890ab?v=abcd"

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": notes_url}, clear=False):
            notion_connector.create_note_in_notes_db(
                {"note_name": "Normalize id", "tag": "GENERAL", "observations": "x", "url": ""},
                project_logger=_MockLogger(),
            )

        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "12345678-1234-1234-1234-1234567890ab")

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_create_note_in_notes_db_supports_type_created_schema(self, mock_load_credentials, mock_post, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "properties": {
                    "Name": {"type": "title"},
                    "Created": {"type": "created_time"},
                    "Tags": {"type": "multi_select"},
                    "Type": {"type": "select"},
                }
            }
        )

        def _side_effect(*_args, **kwargs):
            properties = kwargs["json"]["properties"]
            if "Name" in properties and "title" in properties["Name"] and "Tags" in properties:
                return _MockResponse({"id": "note-2", "url": "https://notion.so/note-2"}, status_code=200)
            return _MockResponse({"code": "validation_error"}, status_code=400)

        mock_post.side_effect = _side_effect

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            result = notion_connector.create_note_in_notes_db(
                {
                    "note_name": "Schema fallback",
                    "tag": "GENERAL",
                    "observations": "Long body without dedicated observations property",
                    "url": "",
                },
                project_logger=_MockLogger(),
            )

        self.assertEqual(result["id"], "note-2")
        success_payload = mock_post.call_args.kwargs["json"]
        self.assertIn("children", success_payload)

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_notes_around_today_filters_and_parses(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_post.return_value = _MockResponse(
            {
                "results": [
                    {
                        "id": "note-1",
                        "url": "https://notion.so/note-1",
                        "properties": {
                            "Name": {"title": [{"plain_text": "Daily insight"}]},
                            "Date": {"date": {"start": "2026-03-01"}},
                            "Tags": {"type": "multi_select", "multi_select": [{"name": "IDEA"}]},
                            "Observações": {"rich_text": [{"plain_text": "Review weekly goals"}]},
                            "URL": {"url": "https://example.com"},
                        },
                    }
                ],
                "has_more": False,
                "next_cursor": None,
            }
        )

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            notes = notion_connector.collect_notes_around_today(
                days_back=5,
                days_forward=5,
                project_logger=_MockLogger(),
            )

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["id"], "note-1")
        self.assertEqual(notes[0]["name"], "Daily insight")
        self.assertEqual(notes[0]["tags"], ["IDEA"])
        self.assertEqual(notes[0]["observations"], "Review weekly goals")
        payload = mock_post.call_args.kwargs["json"]
        and_filters = payload["filter"]["and"]
        self.assertEqual(and_filters[0]["property"], "Date")
        self.assertEqual(and_filters[1]["property"], "Date")
        self.assertIn("on_or_after", and_filters[0]["date"])
        self.assertIn("on_or_before", and_filters[1]["date"])

    @patch("notion_connector.notion_connector.requests.post")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_collect_notes_around_today_supports_created_and_type_properties(self, mock_load_credentials, mock_post):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}

        def _side_effect(*_args, **kwargs):
            payload = kwargs["json"]
            first_filter = payload["filter"]["and"][0]
            if first_filter.get("property") == "Date":
                return _MockResponse({"code": "validation_error"}, status_code=400)
            if first_filter.get("property") == "Created":
                return _MockResponse({"code": "validation_error"}, status_code=400)
            return _MockResponse(
                {
                    "results": [
                        {
                            "id": "note-2",
                            "url": "https://notion.so/note-2",
                            "created_time": "2026-03-02T09:00:00.000Z",
                            "properties": {
                                "Type": {"title": [{"plain_text": "Type-based note"}]},
                                "Tags": {"type": "select", "select": {"name": "GENERAL"}},
                                "Status": {"type": "status", "status": {"name": "Open"}},
                            },
                        }
                    ],
                    "has_more": False,
                    "next_cursor": None,
                },
                status_code=200,
            )

        mock_post.side_effect = _side_effect

        with patch.dict("os.environ", {"NOTION_NOTES_DB_ID": "notes-db-id"}, clear=False):
            notes = notion_connector.collect_notes_around_today(
                days_back=5,
                days_forward=5,
                project_logger=_MockLogger(),
            )

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["name"], "Type-based note")
        self.assertTrue(notes[0]["date"].startswith("2026-03-02"))
        self.assertEqual(notes[0]["tags"], ["GENERAL"])

    @patch("notion_connector.notion_connector.requests.patch")
    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_notion_page_updates_task_fields(self, mock_load_credentials, mock_get, mock_patch):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "id": "task-page",
                "url": "https://notion.so/task-page",
                "properties": {
                    "Task": {"type": "title"},
                    "When": {"type": "date"},
                    "Project": {"type": "select"},
                    "Tags": {"type": "multi_select"},
                    "DONE": {"type": "checkbox"},
                },
            }
        )
        mock_patch.return_value = _MockResponse({"id": "task-page", "url": "https://notion.so/task-page"})

        result = notion_connector.update_notion_page(
            {
                "item_type": "task",
                "page_id": "123456781234123412341234567890ab",
                "task_name": "Atualizar backlog",
                "due_date": "2026-03-11",
                "project": "Pessoal",
                "tags": ["FAST"],
                "done": True,
            },
            project_logger=_MockLogger(),
        )

        self.assertEqual(result["id"], "task-page")
        payload = mock_patch.call_args.kwargs["json"]["properties"]
        self.assertEqual(payload["Task"]["title"][0]["text"]["content"], "Atualizar backlog")
        self.assertEqual(payload["When"]["date"]["start"], "2026-03-11")
        self.assertEqual(payload["Project"]["select"]["name"], "Pessoal")
        self.assertEqual(payload["Tags"]["multi_select"][0]["name"], "FAST")
        self.assertTrue(payload["DONE"]["checkbox"])

    @patch("notion_connector.notion_connector.requests.patch")
    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_notion_page_updates_card_fields(self, mock_load_credentials, mock_get, mock_patch):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "id": "card-page",
                "url": "https://notion.so/card-page",
                "properties": {
                    "Name": {"type": "title"},
                    "Tags": {"type": "select"},
                    "Date": {"type": "date"},
                    "Observações": {"type": "rich_text"},
                    "URL": {"type": "url"},
                },
            }
        )
        mock_patch.return_value = _MockResponse({"id": "card-page", "url": "https://notion.so/card-page"})

        result = notion_connector.update_notion_page(
            {
                "item_type": "card",
                "page_id": "12345678-1234-1234-1234-1234567890ac",
                "note_name": "Novo card",
                "tag": "IDEA",
                "date": "2026-03-12",
                "observations": "Texto do card",
                "url": "https://example.com",
            },
            project_logger=_MockLogger(),
        )

        self.assertEqual(result["id"], "card-page")
        payload = mock_patch.call_args.kwargs["json"]["properties"]
        self.assertEqual(payload["Name"]["title"][0]["text"]["content"], "Novo card")
        self.assertEqual(payload["Tags"]["select"]["name"], "IDEA")
        self.assertEqual(payload["Date"]["date"]["start"], "2026-03-12")
        self.assertEqual(payload["URL"]["url"], "https://example.com")
        self.assertTrue(payload["Observações"]["rich_text"])

    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_notion_page_rejects_invalid_page_id(self, mock_load_credentials, mock_get):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}

        with self.assertRaises(ValueError):
            notion_connector.update_notion_page(
                {
                    "item_type": "task",
                    "page_id": "Mandar mensagem para Latina",
                    "done": True,
                },
                project_logger=_MockLogger(),
            )

        mock_get.assert_not_called()

    @patch("notion_connector.notion_connector.requests.patch")
    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_notion_page_appends_content_blocks(self, mock_load_credentials, mock_get, mock_patch):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.return_value = _MockResponse(
            {
                "id": "task-page",
                "url": "https://notion.so/task-page",
                "properties": {"Task": {"type": "title"}},
            }
        )
        mock_patch.return_value = _MockResponse({"id": "task-page", "url": "https://notion.so/task-page"})

        result = notion_connector.update_notion_page(
            {
                "item_type": "task",
                "page_id": "12345678-1234-1234-1234-1234567890ab",
                "content": "# Atualização\n- item",
            },
            project_logger=_MockLogger(),
        )

        self.assertEqual(result["id"], "task-page")
        self.assertEqual(mock_patch.call_count, 1)
        self.assertIn("/blocks/12345678-1234-1234-1234-1234567890ab/children", mock_patch.call_args.args[0])
        children = mock_patch.call_args.kwargs["json"]["children"]
        self.assertTrue(children)

    @patch("notion_connector.notion_connector.requests.patch")
    @patch("notion_connector.notion_connector.requests.get")
    @patch("notion_connector.notion_connector.load_credentials.load_notion_credentials")
    def test_update_notion_page_replaces_existing_content_blocks(self, mock_load_credentials, mock_get, mock_patch):
        mock_load_credentials.return_value = {"database_id": "tasks-db-id", "api_key": "api-key"}
        mock_get.side_effect = [
            _MockResponse(
                {
                    "id": "task-page",
                    "url": "https://notion.so/task-page",
                    "properties": {"Task": {"type": "title"}},
                }
            ),
            _MockResponse(
                {
                    "results": [{"id": "block-1"}, {"id": "block-2"}],
                    "has_more": False,
                    "next_cursor": None,
                }
            ),
        ]
        mock_patch.return_value = _MockResponse({"id": "task-page", "url": "https://notion.so/task-page"})

        notion_connector.update_notion_page(
            {
                "item_type": "task",
                "page_id": "12345678-1234-1234-1234-1234567890ab",
                "content": "conteúdo novo",
                "content_mode": "replace",
            },
            project_logger=_MockLogger(),
        )

        self.assertEqual(mock_patch.call_count, 3)
        self.assertIn("/blocks/block-1", mock_patch.call_args_list[0].args[0])
        self.assertIn("/blocks/block-2", mock_patch.call_args_list[1].args[0])
        self.assertIn("/blocks/12345678-1234-1234-1234-1234567890ab/children", mock_patch.call_args_list[2].args[0])


if __name__ == "__main__":
    unittest.main()

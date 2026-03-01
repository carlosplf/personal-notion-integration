import json
import tempfile
import unittest
from unittest.mock import patch

from calendar_connector import calendar_connector


class _MockLogger:
    def warning(self, *_args, **_kwargs):
        return None


class _FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _FakeEventsService:
    def __init__(self):
        self.calls = []

    def list(self, **kwargs):
        self.calls.append(kwargs)
        calendar_id = kwargs["calendarId"]
        return _FakeExecute(
            {
                "items": [
                    {
                        "id": f"id-{calendar_id}",
                        "summary": f"Event {calendar_id}",
                        "start": {"dateTime": "2026-03-10T10:00:00Z"},
                        "end": {"dateTime": "2026-03-10T11:00:00Z"},
                    }
                ]
            }
        )


class _FakeService:
    def __init__(self):
        self._events = _FakeEventsService()

    def events(self):
        return self._events


class TestCalendarConnector(unittest.TestCase):
    def test_extract_first_json_object(self):
        payload = calendar_connector._extract_first_json_object('{"a":1}{"b":2}')
        self.assertEqual(payload["a"], 1)

    @patch("calendar_connector.calendar_connector.Credentials.from_authorized_user_info")
    @patch("calendar_connector.calendar_connector.Credentials.from_authorized_user_file")
    def test_load_credentials_recovers_token_with_trailing_json(
        self,
        mock_from_file,
        mock_from_info,
    ):
        mock_from_file.side_effect = json.JSONDecodeError("Extra data", "{}", 2)
        mock_from_info.return_value = object()

        with tempfile.NamedTemporaryFile(mode="w+", delete=True, encoding="utf-8") as temp_token:
            temp_token.write('{"refresh_token":"abc","client_id":"id","client_secret":"secret","token_uri":"uri"}{"extra":true}')
            temp_token.flush()

            creds = calendar_connector._load_credentials_from_token(
                temp_token.name,
                ["scope"],
                _MockLogger(),
            )

            self.assertIsNotNone(creds)
            with open(temp_token.name, "r", encoding="utf-8") as token_file:
                saved = json.load(token_file)
            self.assertEqual(saved["refresh_token"], "abc")

    def test_normalize_event_datetime_supports_short_format(self):
        iso_value, parsed = calendar_connector._normalize_event_datetime(
            "2026-03-06T10:00",
            "America/Sao_Paulo",
        )
        self.assertIn("2026-03-06T10:00:00", iso_value)
        self.assertIsNotNone(parsed.tzinfo)

    def test_normalize_event_datetime_rejects_invalid_timezone(self):
        with self.assertRaises(ValueError):
            calendar_connector._normalize_event_datetime(
                "2026-03-06T10:00",
                "UTC-3",
            )

    @patch("calendar_connector.calendar_connector.calendar_connect")
    def test_list_week_events_uses_primary_calendar(self, mock_connect):
        fake_service = _FakeService()
        mock_connect.return_value = fake_service

        events = calendar_connector.list_week_events(
            project_logger=_MockLogger(),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["summary"], "Event primary")

    @patch("calendar_connector.calendar_connector.calendar_connect")
    def test_list_current_week_events_uses_primary_calendar(self, mock_connect):
        fake_service = _FakeService()
        mock_connect.return_value = fake_service

        events = calendar_connector.list_current_week_events(
            project_logger=_MockLogger(),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["summary"], "Event primary")
        call_kwargs = fake_service.events().calls[0]
        self.assertEqual(call_kwargs["calendarId"], "primary")
        self.assertIn("timeMin", call_kwargs)
        self.assertIn("timeMax", call_kwargs)

    @patch("calendar_connector.calendar_connector.calendar_connect")
    def test_list_current_week_events_on_sunday_uses_next_six_days(self, mock_connect):
        class _SundayDateTime(calendar_connector.datetime.datetime):
            @classmethod
            def utcnow(cls):
                return cls(2026, 3, 1, 12, 0, 0)

        fake_service = _FakeService()
        mock_connect.return_value = fake_service

        with patch("calendar_connector.calendar_connector.datetime.datetime", _SundayDateTime):
            calendar_connector.list_current_week_events(project_logger=_MockLogger())

        call_kwargs = fake_service.events().calls[0]
        self.assertTrue(call_kwargs["timeMin"].startswith("2026-03-01T00:00:00"))
        self.assertTrue(call_kwargs["timeMax"].startswith("2026-03-08T00:00:00"))


if __name__ == "__main__":
    unittest.main()

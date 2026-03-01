import unittest
import os
import json
import tempfile
from unittest.mock import patch

from gmail_connector import gmail_connector


class _MockLogger:
    def error(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class _FakeSendExecute:
    def execute(self):
        return {"id": "gmail-msg-1", "threadId": "thread-1"}


class _FakeMessagesService:
    def send(self, **_kwargs):
        return _FakeSendExecute()


class _FakeUsersService:
    def messages(self):
        return _FakeMessagesService()


class _FakeGmailService:
    def users(self):
        return _FakeUsersService()


class TestGmailConnector(unittest.TestCase):
    def test_send_custom_email_fake_send(self):
        with patch.dict(
            os.environ,
            {
                "EMAIL_FROM": "from@example.com",
                "EMAIL_TO": "to@example.com",
            },
            clear=False,
        ):
            result = gmail_connector.send_custom_email(
                project_logger=_MockLogger(),
                subject="Assunto",
                body_text="Conteúdo",
                fake_send=True,
            )

        self.assertEqual(result["to"], "to@example.com")
        self.assertEqual(result["from"], "from@example.com")
        self.assertEqual(result["subject"], "Assunto")
        self.assertIn("raw", result)

    @patch("gmail_connector.gmail_connector.build")
    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_file")
    def test_send_custom_email_sends_message(
        self,
        mock_from_authorized_user_file,
        mock_build,
    ):
        mock_from_authorized_user_file.return_value = object()
        mock_build.return_value = _FakeGmailService()

        with patch.dict(os.environ, {"EMAIL_FROM": "from@example.com"}, clear=False):
            result = gmail_connector.send_custom_email(
                project_logger=_MockLogger(),
                subject="Assunto",
                body_text="Conteúdo",
                email_to="x@example.com",
            )

        self.assertEqual(result["id"], "gmail-msg-1")
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(result["to"], "x@example.com")

    def test_send_custom_email_requires_destination(self):
        with patch.dict(os.environ, {"EMAIL_FROM": "from@example.com", "EMAIL_TO": ""}, clear=False):
            with self.assertRaises(ValueError):
                gmail_connector.send_custom_email(
                    project_logger=_MockLogger(),
                    subject="Assunto",
                    body_text="Conteúdo",
                )

    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_info")
    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_file")
    def test_load_credentials_recovers_token_with_trailing_json(
        self,
        mock_from_file,
        mock_from_info,
    ):
        mock_from_file.side_effect = json.JSONDecodeError("Extra data", "{}", 2)
        mock_from_info.return_value = object()

        with tempfile.NamedTemporaryFile(mode="w+", delete=True, encoding="utf-8") as temp_token:
            temp_token.write(
                '{"refresh_token":"abc","client_id":"id","client_secret":"secret","token_uri":"uri"}{"extra":true}'
            )
            temp_token.flush()

            creds = gmail_connector._load_credentials_from_token(
                temp_token.name,
                ["scope"],
                _MockLogger(),
            )

            self.assertIsNotNone(creds)
            with open(temp_token.name, "r", encoding="utf-8") as token_file:
                saved = json.load(token_file)
            self.assertEqual(saved["refresh_token"], "abc")


if __name__ == "__main__":
    unittest.main()

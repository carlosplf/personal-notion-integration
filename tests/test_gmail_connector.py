import unittest
import os
import json
import base64
from email import message_from_bytes
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


class _FakeExecute:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeMessagesServiceWithReads:
    def __init__(self, payloads, attachment_payloads=None):
        self._payloads = payloads
        self._attachments = _FakeAttachmentsService(attachment_payloads or {})

    def list(self, **_kwargs):
        return _FakeExecute({"messages": [{"id": key} for key in self._payloads]})

    def get(self, **kwargs):
        message_id = kwargs["id"]
        return _FakeExecute(self._payloads[message_id])

    def send(self, **_kwargs):
        return _FakeSendExecute()

    def attachments(self):
        return self._attachments


class _FakeAttachmentsService:
    def __init__(self, attachment_payloads):
        self._attachment_payloads = attachment_payloads

    def get(self, **kwargs):
        return _FakeExecute(self._attachment_payloads[kwargs["id"]])


class _FakeMessagesService:
    def send(self, **_kwargs):
        return _FakeSendExecute()


class _FakeUsersService:
    def messages(self):
        return _FakeMessagesService()


class _FakeGmailService:
    def users(self):
        return _FakeUsersService()


class _FakeUsersServiceWithReads:
    def __init__(self, payloads, attachment_payloads=None):
        self._messages = _FakeMessagesServiceWithReads(payloads, attachment_payloads)

    def messages(self):
        return self._messages


class _FakeGmailServiceWithReads:
    def __init__(self, payloads, attachment_payloads=None):
        self._users = _FakeUsersServiceWithReads(payloads, attachment_payloads)

    def users(self):
        return self._users


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

    @patch("gmail_connector.gmail_connector.build")
    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_file")
    def test_send_custom_email_replies_in_same_thread(
        self,
        mock_from_authorized_user_file,
        mock_build,
    ):
        mock_from_authorized_user_file.return_value = object()
        service = unittest.mock.Mock()
        users = service.users.return_value
        messages = users.messages.return_value
        messages.get.return_value.execute.return_value = {
            "threadId": "thread-original",
            "payload": {
                "headers": [
                    {"name": "Message-Id", "value": "<original@example.com>"},
                    {"name": "References", "value": "<older@example.com>"},
                ]
            },
        }
        messages.send.return_value.execute.return_value = {
            "id": "gmail-msg-2",
            "threadId": "thread-original",
        }
        mock_build.return_value = service

        with patch.dict(os.environ, {"EMAIL_FROM": "from@example.com"}, clear=False):
            result = gmail_connector.send_custom_email(
                project_logger=_MockLogger(),
                subject="Assunto",
                body_text="Conteúdo",
                email_to="x@example.com",
                reply_to_message_id="orig-msg-id",
            )

        self.assertEqual(result["thread_id"], "thread-original")
        send_body = messages.send.call_args.kwargs["body"]
        self.assertEqual(send_body["threadId"], "thread-original")
        raw_payload = send_body["raw"]
        padding = "=" * ((4 - len(raw_payload) % 4) % 4)
        mime_message = message_from_bytes(base64.urlsafe_b64decode(f"{raw_payload}{padding}"))
        self.assertEqual(mime_message.get("In-Reply-To"), "<original@example.com>")
        self.assertIn("<original@example.com>", mime_message.get("References", ""))

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

    @patch("gmail_connector.gmail_connector.build")
    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_file")
    def test_search_emails_returns_normalized_metadata(
        self,
        mock_from_authorized_user_file,
        mock_build,
    ):
        payloads = {
            "m1": {
                "id": "m1",
                "threadId": "t1",
                "snippet": "hello",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "a@example.com"},
                        {"name": "To", "value": "b@example.com"},
                        {"name": "Subject", "value": "Assunto"},
                        {"name": "Date", "value": "Mon"},
                    ]
                },
            }
        }
        mock_from_authorized_user_file.return_value = object()
        mock_build.return_value = _FakeGmailServiceWithReads(payloads)

        result = gmail_connector.search_emails(
            project_logger=_MockLogger(),
            query="from:a@example.com",
            max_results=5,
        )

        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["emails"][0]["id"], "m1")
        self.assertEqual(result["emails"][0]["subject"], "Assunto")

    @patch("gmail_connector.gmail_connector.build")
    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_file")
    def test_read_email_includes_attachments(
        self,
        mock_from_authorized_user_file,
        mock_build,
    ):
        payloads = {
            "m2": {
                "id": "m2",
                "threadId": "t2",
                "snippet": "anexo",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Com anexo"},
                    ],
                    "parts": [
                        {
                            "filename": "invoice.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "att-1", "size": 321},
                        }
                    ],
                },
            }
        }
        mock_from_authorized_user_file.return_value = object()
        mock_build.return_value = _FakeGmailServiceWithReads(payloads)

        result = gmail_connector.read_email(
            project_logger=_MockLogger(),
            message_id="m2",
            include_body=False,
        )

        self.assertEqual(result["id"], "m2")
        self.assertEqual(result["attachments"][0]["filename"], "invoice.pdf")
        self.assertEqual(result["attachments"][0]["attachment_id"], "att-1")

    @patch("gmail_connector.gmail_connector.build")
    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_file")
    def test_search_email_attachments_filters_filename(
        self,
        mock_from_authorized_user_file,
        mock_build,
    ):
        payloads = {
            "m3": {
                "id": "m3",
                "threadId": "t3",
                "snippet": "docs",
                "payload": {
                    "headers": [{"name": "Subject", "value": "Docs"}],
                    "parts": [
                        {
                            "filename": "report.xlsx",
                            "mimeType": "application/vnd.ms-excel",
                            "body": {"attachmentId": "att-2", "size": 456},
                        },
                        {
                            "filename": "notes.txt",
                            "mimeType": "text/plain",
                            "body": {"attachmentId": "att-3", "size": 78},
                        },
                    ],
                },
            }
        }
        mock_from_authorized_user_file.return_value = object()
        mock_build.return_value = _FakeGmailServiceWithReads(payloads)

        result = gmail_connector.search_email_attachments(
            project_logger=_MockLogger(),
            query="subject:Docs",
            filename_contains=".xlsx",
            max_results=10,
        )

        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["attachments"][0]["filename"], "report.xlsx")

    @patch("gmail_connector.gmail_connector._extract_attachment_text")
    @patch("gmail_connector.gmail_connector.build")
    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_file")
    def test_analyze_email_attachment_downloads_and_extracts(
        self,
        mock_from_authorized_user_file,
        mock_build,
        mock_extract_attachment_text,
    ):
        payloads = {
            "m4": {
                "id": "m4",
                "threadId": "t4",
                "payload": {
                    "parts": [
                        {
                            "filename": "documento.pdf",
                            "mimeType": "application/pdf",
                            "body": {"attachmentId": "att-44", "size": 12},
                        }
                    ]
                },
            }
        }
        encoded_payload = base64.urlsafe_b64encode(b"fake-pdf").decode()
        mock_from_authorized_user_file.return_value = object()
        mock_build.return_value = _FakeGmailServiceWithReads(
            payloads,
            {"att-44": {"data": encoded_payload}},
        )
        mock_extract_attachment_text.return_value = "texto extraido"

        result = gmail_connector.analyze_email_attachment(
            project_logger=_MockLogger(),
            message_id="m4",
            attachment_id="att-44",
            max_chars=1000,
        )

        self.assertEqual(result["attachment_id"], "att-44")
        self.assertEqual(result["content_preview"], "texto extraido")
        self.assertFalse(result["truncated"])

    @patch("gmail_connector.gmail_connector._extract_docx_text")
    def test_extract_attachment_text_accepts_docx_mime_with_parameters(self, mock_extract_docx_text):
        mock_extract_docx_text.return_value = "conteudo docx"

        extracted = gmail_connector._extract_attachment_text(
            b"fake-docx-bytes",
            filename="",
            mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document; name="plano.docx"',
        )

        self.assertEqual(extracted, "conteudo docx")

    @patch("gmail_connector.gmail_connector._extract_attachment_text")
    @patch("gmail_connector.gmail_connector.build")
    @patch("gmail_connector.gmail_connector.Credentials.from_authorized_user_file")
    def test_analyze_email_attachment_reads_inline_attachment_data(
        self,
        mock_from_authorized_user_file,
        mock_build,
        mock_extract_attachment_text,
    ):
        inline_data = base64.urlsafe_b64encode(b"inline-docx").decode()
        payloads = {
            "m5": {
                "id": "m5",
                "threadId": "t5",
                "payload": {
                    "parts": [
                        {
                            "filename": "Plano Analise.docx",
                            "mimeType": "application/octet-stream",
                            "body": {"data": inline_data, "size": 22},
                        }
                    ]
                },
            }
        }
        mock_from_authorized_user_file.return_value = object()
        mock_build.return_value = _FakeGmailServiceWithReads(payloads, {})
        mock_extract_attachment_text.return_value = "resumo inline"

        result = gmail_connector.analyze_email_attachment(
            project_logger=_MockLogger(),
            message_id="m5",
            filename="plano",
            max_chars=1000,
        )

        self.assertEqual(result["filename"], "Plano Analise.docx")
        self.assertEqual(result["content_preview"], "resumo inline")


if __name__ == "__main__":
    unittest.main()

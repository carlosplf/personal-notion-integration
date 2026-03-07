import asyncio
import os
import sys
import types
import unittest
import unittest.mock

# Stub telegram packages before importing telegram_bot so no real network
# dependencies are needed during unit tests.
_telegram_stub = types.ModuleType("telegram")
_telegram_ext_stub = types.ModuleType("telegram.ext")
_telegram_constants_stub = types.ModuleType("telegram.constants")
_telegram_stub.Update = object
_telegram_ext_stub.Application = object
_telegram_ext_stub.CommandHandler = object
_telegram_ext_stub.MessageHandler = object
_telegram_ext_stub.ContextTypes = object
_telegram_ext_stub.filters = types.SimpleNamespace(
    TEXT=object(),
    COMMAND=object(),
    VOICE=object(),
    AUDIO=object(),
)
_telegram_constants_stub.ChatAction = types.SimpleNamespace(TYPING="typing")
_telegram_constants_stub.ParseMode = types.SimpleNamespace(HTML="HTML")
sys.modules.setdefault("telegram", _telegram_stub)
sys.modules.setdefault("telegram.ext", _telegram_ext_stub)
sys.modules.setdefault("telegram.constants", _telegram_constants_stub)
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda: None))

import telegram_bot


class TestTelegramBot(unittest.TestCase):
    # --- Authorization ---

    def test_is_authorized_denies_empty_set(self):
        self.assertFalse(telegram_bot._is_authorized_telegram_user(123, set()))

    def test_is_authorized_user_in_set(self):
        self.assertTrue(telegram_bot._is_authorized_telegram_user(123, {123, 456}))

    def test_is_authorized_user_not_in_set(self):
        self.assertFalse(telegram_bot._is_authorized_telegram_user(999, {123, 456}))

    def test_is_authorized_single_user(self):
        self.assertTrue(telegram_bot._is_authorized_telegram_user(42, {42}))
        self.assertFalse(telegram_bot._is_authorized_telegram_user(43, {42}))

    def test_access_denied_message_is_defined(self):
        self.assertIn("Access denied", telegram_bot.ACCESS_DENIED_MESSAGE)

    # --- Message constants ---

    def test_message_length_constant_is_telegram_limit(self):
        self.assertEqual(telegram_bot.MAX_TELEGRAM_MESSAGE_LENGTH, 4096)

    def test_chunk_target_is_below_message_limit(self):
        self.assertLess(telegram_bot.TELEGRAM_CHUNK_TARGET, telegram_bot.MAX_TELEGRAM_MESSAGE_LENGTH)

    # --- Response builders ---

    def test_build_bot_response_wraps_plain_text_in_markdown(self):
        message = telegram_bot.build_bot_response("Resposta simples")
        self.assertTrue(message.startswith("## Assistente pessoal"))
        self.assertIn("Resposta simples", message)

    def test_build_bot_response_preserves_markdown(self):
        markdown_answer = "## Resumo\n\n- Item 1"
        message = telegram_bot.build_bot_response(markdown_answer)
        self.assertEqual(message, markdown_answer)

    def test_build_bot_response_preserves_long_text_for_chunking(self):
        message = telegram_bot.build_bot_response("b" * 8000)
        self.assertGreater(len(message), telegram_bot.MAX_TELEGRAM_MESSAGE_LENGTH)

    def test_build_bot_response_empty_input_returns_fallback(self):
        message = telegram_bot.build_bot_response("")
        self.assertIn("não consegui responder", message)

    def test_build_new_chat_response(self):
        message = telegram_bot.build_new_chat_response()
        self.assertIn("Nova conversa iniciada", message)
        self.assertIn("🔄", message)
        self.assertIn("Limpei o histórico", message)

    def test_build_error_response_is_generic(self):
        message = telegram_bot.build_error_response(Exception("detalhe secreto"))
        self.assertNotIn("detalhe secreto", message)
        self.assertIn("erro", message.lower())

    def test_build_error_response_does_not_expose_details(self):
        message = telegram_bot.build_error_response("caminho/interno/secreto")
        self.assertNotIn("caminho", message)
        self.assertLessEqual(len(message), telegram_bot.MAX_TELEGRAM_MESSAGE_LENGTH)

    # --- /setup message builder ---

    def _make_fake_store(self, integrations=None, configured_keys=None):
        store = unittest.mock.MagicMock()
        store.check_integrations.return_value = integrations or {"Notion": False, "Email": False}
        store.list_configured_keys.return_value = configured_keys or []
        return store

    def test_build_setup_trigger_contains_integration_headers(self):
        store = self._make_fake_store()
        msg = telegram_bot._build_setup_trigger_message("123", store)
        self.assertIn("Notion", msg)
        self.assertIn("Email", msg)
        self.assertIn("[SETUP]", msg)

    def test_build_setup_trigger_shows_inactive_when_not_configured(self):
        store = self._make_fake_store(integrations={"Notion": False, "Email": False})
        msg = telegram_bot._build_setup_trigger_message("123", store)
        self.assertIn("❌", msg)
        self.assertIn("inativa", msg)

    def test_build_setup_trigger_shows_active_when_configured(self):
        store = self._make_fake_store(
            integrations={"Notion": True, "Email": False},
            configured_keys=["notion_api_key", "notion_database_id"],
        )
        msg = telegram_bot._build_setup_trigger_message("123", store)
        self.assertIn("✅", msg)
        self.assertIn("ativa", msg)

    def test_build_setup_trigger_includes_missing_keys(self):
        store = self._make_fake_store(integrations={"Notion": False, "Email": False})
        msg = telegram_bot._build_setup_trigger_message("123", store)
        self.assertIn("notion_api_key", msg)

    def test_build_setup_trigger_ends_with_guide_request(self):
        store = self._make_fake_store()
        msg = telegram_bot._build_setup_trigger_message("123", store)
        self.assertIn("Por favor", msg)
        self.assertIn("configuração", msg)

    # --- Message chunking ---

    def test_split_chunks_returns_single_for_short_text(self):
        chunks = telegram_bot._split_telegram_message_chunks("Texto curto")
        self.assertEqual(chunks, ["Texto curto"])

    def test_split_chunks_respects_chunk_size(self):
        text = ("paragrafo " * 800).strip()
        chunks = telegram_bot._split_telegram_message_chunks(text, chunk_size=200)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 200 for chunk in chunks))

    def test_split_chunks_reconstructs_full_text(self):
        text = "word " * 1000
        chunks = telegram_bot._split_telegram_message_chunks(text, chunk_size=100)
        joined = " ".join(chunks)
        # all original words should still be present
        for word in text.split():
            self.assertIn(word, joined)

    def test_send_telegram_text_sends_multiple_messages(self):
        sent_chunks = []

        async def _fake_send(content, **_kwargs):
            sent_chunks.append(content)

        asyncio.run(telegram_bot._send_telegram_text(_fake_send, "x" * 8000))
        self.assertGreater(len(sent_chunks), 1)
        self.assertTrue(all(len(chunk) <= telegram_bot.TELEGRAM_CHUNK_TARGET for chunk in sent_chunks))

    def test_send_telegram_text_single_message_for_short_text(self):
        sent_chunks = []

        async def _fake_send(content, **_kwargs):
            sent_chunks.append(content)

        asyncio.run(telegram_bot._send_telegram_text(_fake_send, "Curto"))
        self.assertEqual(len(sent_chunks), 1)
        self.assertEqual(sent_chunks[0], "Curto")

    # --- Scheduler ---

    def test_scheduler_enabled_by_default(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ASSISTANT_SCHEDULER_ENABLED", None)
            self.assertTrue(telegram_bot._is_scheduler_enabled())

    def test_scheduler_disabled_when_zero(self):
        with unittest.mock.patch.dict(os.environ, {"ASSISTANT_SCHEDULER_ENABLED": "0"}, clear=False):
            self.assertFalse(telegram_bot._is_scheduler_enabled())

    def test_scheduler_enabled_parsing_variants(self):
        for disabled_val in ("0", "false", "no", "off"):
            with unittest.mock.patch.dict(
                os.environ, {"ASSISTANT_SCHEDULER_ENABLED": disabled_val}, clear=False
            ):
                self.assertFalse(telegram_bot._is_scheduler_enabled(), f"Expected False for '{disabled_val}'")
        for enabled_val in ("1", "true", "yes", "on"):
            with unittest.mock.patch.dict(
                os.environ, {"ASSISTANT_SCHEDULER_ENABLED": enabled_val}, clear=False
            ):
                self.assertTrue(telegram_bot._is_scheduler_enabled(), f"Expected True for '{enabled_val}'")

    # --- Entry point ---

    def test_run_telegram_bot_calls_run_polling(self):
        fake_app = unittest.mock.Mock()
        with unittest.mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token"}, clear=False):
            with unittest.mock.patch.object(
                telegram_bot, "create_telegram_application", return_value=fake_app
            ):
                with unittest.mock.patch.object(
                    telegram_bot.app_health, "mark_app_started"
                ) as mark_started:
                    telegram_bot.run_telegram_bot()

        fake_app.run_polling.assert_called_once_with(drop_pending_updates=True)
        mark_started.assert_called_once()

    def test_run_telegram_bot_raises_without_token(self):
        with unittest.mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}, clear=False):
            with self.assertRaises(ValueError):
                telegram_bot.run_telegram_bot()


    # --- Markdown → HTML converter ---

    def test_html_converts_h2_to_bold(self):
        html = telegram_bot._markdown_to_telegram_html("## Resumo de hoje")
        self.assertEqual(html, "<b>Resumo de hoje</b>")

    def test_html_converts_bold(self):
        html = telegram_bot._markdown_to_telegram_html("texto **negrito** aqui")
        self.assertIn("<b>negrito</b>", html)

    def test_html_converts_italic_star(self):
        html = telegram_bot._markdown_to_telegram_html("texto *itálico* aqui")
        self.assertIn("<i>itálico</i>", html)

    def test_html_converts_italic_underscore(self):
        html = telegram_bot._markdown_to_telegram_html("texto _itálico_ aqui")
        self.assertIn("<i>itálico</i>", html)

    def test_html_converts_inline_code(self):
        html = telegram_bot._markdown_to_telegram_html("use `git status` agora")
        self.assertIn("<code>git status</code>", html)

    def test_html_converts_fenced_code_block(self):
        html = telegram_bot._markdown_to_telegram_html("```python\nprint('oi')\n```")
        self.assertIn("<pre><code>", html)
        self.assertIn("print(&#x27;oi&#x27;)", html)

    def test_html_converts_blockquote(self):
        html = telegram_bot._markdown_to_telegram_html("> Observação importante")
        self.assertEqual(html, "<blockquote>Observação importante</blockquote>")

    def test_html_converts_blockquote_with_inline_formatting(self):
        html = telegram_bot._markdown_to_telegram_html("> **Atenção:** prazo amanhã")
        self.assertIn("<blockquote>", html)
        self.assertIn("<b>Atenção:</b>", html)

        html = telegram_bot._markdown_to_telegram_html("~~riscado~~")
        self.assertIn("<s>riscado</s>", html)

    def test_html_converts_bullet_list(self):
        html = telegram_bot._markdown_to_telegram_html("- Item A\n- Item B")
        self.assertIn("• Item A", html)
        self.assertIn("• Item B", html)

    def test_html_converts_numbered_list(self):
        html = telegram_bot._markdown_to_telegram_html("1. Primeiro\n2. Segundo")
        self.assertIn("1. Primeiro", html)
        self.assertIn("2. Segundo", html)

    def test_html_escapes_special_chars(self):
        html = telegram_bot._markdown_to_telegram_html("a & b < c > d")
        self.assertIn("&amp;", html)
        self.assertIn("&lt;", html)
        self.assertIn("&gt;", html)
        self.assertNotIn("<c>", html)

    def test_html_does_not_escape_code_block_markers(self):
        html = telegram_bot._markdown_to_telegram_html("```\n<script>alert(1)</script>\n```")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_html_preserves_plain_text(self):
        html = telegram_bot._markdown_to_telegram_html("Texto simples sem formatação")
        self.assertEqual(html, "Texto simples sem formatação")

    def test_send_formatted_response_uses_html_parse_mode(self):
        sent = []

        async def _fake_send(content, **kwargs):
            sent.append((content, kwargs))

        asyncio.run(telegram_bot._send_formatted_response(_fake_send, "## Título\n\nTexto"))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1].get("parse_mode"), "HTML")
        self.assertIn("<b>Título</b>", sent[0][0])


if __name__ == "__main__":
    unittest.main()

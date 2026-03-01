import os
import sqlite3
import tempfile
import unittest

from assistant_connector.memory_store import ConversationMemoryStore


class TestConversationMemoryStore(unittest.TestCase):
    def test_append_and_read_recent_messages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "assistant_memory.sqlite3")
            memory_store = ConversationMemoryStore(db_path)

            memory_store.append_message("session-1", "user", "olá")
            memory_store.append_message("session-1", "assistant", "oi, tudo bem?")

            messages = memory_store.get_recent_messages("session-1", limit=10)
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["role"], "user")
            self.assertEqual(messages[1]["role"], "assistant")

    def test_log_tool_call_persists_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "assistant_memory.sqlite3")
            memory_store = ConversationMemoryStore(db_path)

            memory_store.log_tool_call(
                session_id="session-1",
                tool_name="list_available_tools",
                arguments={"foo": "bar"},
                result={"ok": True},
            )

            with sqlite3.connect(db_path) as connection:
                cursor = connection.execute(
                    "SELECT tool_name, arguments_json, result_json FROM tool_calls"
                )
                row = cursor.fetchone()

            self.assertEqual(row[0], "list_available_tools")
            self.assertIn('"foo": "bar"', row[1])
            self.assertIn('"ok": true', row[2].lower())

    def test_prunes_old_messages_per_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "assistant_memory.sqlite3")
            memory_store = ConversationMemoryStore(
                db_path,
                max_messages_per_session=2,
            )
            memory_store.append_message("session-1", "user", "m1")
            memory_store.append_message("session-1", "assistant", "m2")
            memory_store.append_message("session-1", "user", "m3")

            messages = memory_store.get_recent_messages("session-1", limit=10)
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0]["content"], "m2")
            self.assertEqual(messages[1]["content"], "m3")

    def test_prunes_old_tool_calls_per_session(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "assistant_memory.sqlite3")
            memory_store = ConversationMemoryStore(
                db_path,
                max_tool_calls_per_session=2,
            )
            memory_store.log_tool_call("session-1", "tool", {"n": 1}, {"ok": True})
            memory_store.log_tool_call("session-1", "tool", {"n": 2}, {"ok": True})
            memory_store.log_tool_call("session-1", "tool", {"n": 3}, {"ok": True})

            with sqlite3.connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT arguments_json FROM tool_calls WHERE session_id='session-1' ORDER BY id"
                ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertIn('"n": 2', rows[0][0])
            self.assertIn('"n": 3', rows[1][0])

    def test_truncates_long_message_and_tool_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "assistant_memory.sqlite3")
            memory_store = ConversationMemoryStore(
                db_path,
                max_message_chars=200,
                max_tool_payload_chars=500,
            )
            memory_store.append_message("session-1", "user", "x" * 500)
            memory_store.log_tool_call("session-1", "tool", {"text": "a" * 2000}, {"ok": "b" * 2000})

            messages = memory_store.get_recent_messages("session-1", limit=1)
            self.assertLessEqual(len(messages[0]["content"]), 200)

            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    "SELECT arguments_json, result_json FROM tool_calls ORDER BY id DESC LIMIT 1"
                ).fetchone()
            self.assertLessEqual(len(row[0]), 500)
            self.assertLessEqual(len(row[1]), 500)

    def test_clear_session_removes_messages_and_tool_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "assistant_memory.sqlite3")
            memory_store = ConversationMemoryStore(db_path)
            memory_store.append_message("session-1", "user", "oi")
            memory_store.log_tool_call("session-1", "tool", {"a": 1}, {"ok": True})

            memory_store.clear_session("session-1")

            self.assertEqual(memory_store.get_recent_messages("session-1", limit=10), [])
            with sqlite3.connect(db_path) as connection:
                row = connection.execute(
                    "SELECT COUNT(*) FROM tool_calls WHERE session_id='session-1'"
                ).fetchone()
            self.assertEqual(row[0], 0)


if __name__ == "__main__":
    unittest.main()

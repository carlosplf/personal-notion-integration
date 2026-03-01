from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any


class ConversationMemoryStore:
    def __init__(
        self,
        db_path: str,
        *,
        max_messages_per_session: int = 300,
        max_tool_calls_per_session: int = 300,
        max_message_chars: int = 4000,
        max_tool_payload_chars: int = 12000,
    ):
        self._db_path = os.path.abspath(db_path)
        self._lock = threading.Lock()
        self._max_messages_per_session = max(1, int(max_messages_per_session))
        self._max_tool_calls_per_session = max(1, int(max_tool_calls_per_session))
        self._max_message_chars = max(200, int(max_message_chars))
        self._max_tool_payload_chars = max(500, int(max_tool_payload_chars))
        directory = os.path.dirname(self._db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        self._ensure_schema()

    @property
    def db_path(self) -> str:
        return self._db_path

    def append_message(self, session_id: str, role: str, content: str) -> None:
        safe_content = self._truncate_text(str(content), self._max_message_chars)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_messages (session_id, role, content)
                VALUES (?, ?, ?)
                """,
                (session_id, role, safe_content),
            )
            self._prune_conversation_messages(connection, session_id)
            connection.commit()

    def get_recent_messages(self, session_id: str, limit: int) -> list[dict[str, str]]:
        safe_limit = max(1, int(limit))
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                SELECT role, content
                FROM conversation_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, safe_limit),
            )
            rows = cursor.fetchall()
        rows.reverse()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def log_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        arguments_json = self._truncate_text(
            json.dumps(arguments, ensure_ascii=False),
            self._max_tool_payload_chars,
        )
        result_json = self._truncate_text(
            json.dumps(result, ensure_ascii=False),
            self._max_tool_payload_chars,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_calls (session_id, tool_name, arguments_json, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    tool_name,
                    arguments_json,
                    result_json,
                ),
            )
            self._prune_tool_calls(connection, session_id)
            connection.commit()

    @staticmethod
    def _truncate_text(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        marker = "... [truncated]"
        if limit <= len(marker):
            return marker[:limit]
        return f"{text[: limit - len(marker)]}{marker}"

    def _prune_conversation_messages(self, connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            """
            DELETE FROM conversation_messages
            WHERE session_id = ?
              AND id NOT IN (
                SELECT id
                FROM conversation_messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
              )
            """,
            (
                session_id,
                session_id,
                self._max_messages_per_session,
            ),
        )

    def _prune_tool_calls(self, connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            """
            DELETE FROM tool_calls
            WHERE session_id = ?
              AND id NOT IN (
                SELECT id
                FROM tool_calls
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
              )
            """,
            (
                session_id,
                session_id,
                self._max_tool_calls_per_session,
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_conversation_messages_session
                    ON conversation_messages (session_id, id);

                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_tool_calls_session
                    ON tool_calls (session_id, id);
                """
            )
            connection.commit()

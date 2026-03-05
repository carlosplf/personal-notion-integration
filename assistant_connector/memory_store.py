from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

SUPPORTED_RECURRENCE_PATTERNS = {"none", "daily", "weekly", "monthly"}


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

    def clear_session(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM conversation_messages WHERE session_id = ?",
                (session_id,),
            )
            connection.execute(
                "DELETE FROM tool_calls WHERE session_id = ?",
                (session_id,),
            )
            connection.commit()

    def create_scheduled_task(
        self,
        *,
        user_id: str,
        channel_id: str,
        guild_id: str | None,
        message: str,
        scheduled_for: str,
        scheduled_timezone: str = "UTC",
        notify_email_to: str = "",
        recurrence_pattern: str = "none",
        max_attempts: int = 3,
    ) -> str:
        clean_message = str(message).strip()
        if not clean_message:
            raise ValueError("Scheduled task message cannot be empty")
        safe_max_attempts = max(1, int(max_attempts))
        safe_scheduled_timezone = str(scheduled_timezone or "UTC").strip() or "UTC"
        safe_notify_email_to = str(notify_email_to or "").strip()
        safe_recurrence_pattern = self._normalize_recurrence_pattern(recurrence_pattern)
        now_utc = self._normalize_utc_iso(self._utc_now_iso())
        scheduled_for_utc = self._normalize_utc_iso(scheduled_for)
        task_id = uuid.uuid4().hex
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scheduled_tasks (
                    task_id,
                    user_id,
                    channel_id,
                    guild_id,
                    message,
                    scheduled_timezone,
                    notify_email_to,
                    recurrence_pattern,
                    status,
                    attempt_count,
                    max_attempts,
                    scheduled_for,
                    next_attempt_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    str(user_id),
                    str(channel_id),
                    str(guild_id) if guild_id is not None else None,
                    self._truncate_text(clean_message, self._max_message_chars),
                    self._truncate_text(safe_scheduled_timezone, 64),
                    self._truncate_text(safe_notify_email_to, 320),
                    safe_recurrence_pattern,
                    safe_max_attempts,
                    scheduled_for_utc,
                    scheduled_for_utc,
                    now_utc,
                    now_utc,
                ),
            )
            connection.commit()
        return task_id

    def claim_next_scheduled_task(
        self,
        *,
        now_utc: str,
        stale_running_after_seconds: int,
    ) -> dict[str, Any] | None:
        safe_now_utc = self._normalize_utc_iso(now_utc)
        stale_before = self._shift_utc_iso(safe_now_utc, -max(1, int(stale_running_after_seconds)))
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE scheduled_tasks
                SET
                    status = 'retrying',
                    next_attempt_at = ?,
                    locked_at = NULL,
                    updated_at = ?,
                    last_error = CASE
                        WHEN last_error = '' THEN 'Recovered from stale running state'
                        ELSE last_error
                    END
                WHERE status = 'running'
                  AND locked_at IS NOT NULL
                  AND locked_at <= ?
                  AND attempt_count < max_attempts
                """,
                (safe_now_utc, safe_now_utc, stale_before),
            )
            connection.execute(
                """
                UPDATE scheduled_tasks
                SET
                    status = 'failed',
                    finished_at = ?,
                    locked_at = NULL,
                    updated_at = ?,
                    last_error = CASE
                        WHEN last_error = '' THEN 'Stale running task exceeded retry attempts'
                        ELSE last_error
                    END
                WHERE status = 'running'
                  AND locked_at IS NOT NULL
                  AND locked_at <= ?
                  AND attempt_count >= max_attempts
                """,
                (safe_now_utc, safe_now_utc, stale_before),
            )
            cursor = connection.execute(
                """
                SELECT *
                FROM scheduled_tasks
                WHERE status IN ('pending', 'retrying')
                  AND next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, created_at ASC
                LIMIT 1
                """,
                (safe_now_utc,),
            )
            row = cursor.fetchone()
            if row is None:
                connection.commit()
                return None
            task_id = row["task_id"]
            updated = connection.execute(
                """
                UPDATE scheduled_tasks
                SET
                    status = 'running',
                    attempt_count = attempt_count + 1,
                    started_at = COALESCE(started_at, ?),
                    locked_at = ?,
                    updated_at = ?
                WHERE task_id = ?
                  AND status IN ('pending', 'retrying')
                """,
                (safe_now_utc, safe_now_utc, safe_now_utc, task_id),
            )
            if updated.rowcount != 1:
                connection.commit()
                return None
            claimed_row = connection.execute(
                "SELECT * FROM scheduled_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            connection.commit()
        return dict(claimed_row) if claimed_row is not None else None

    def mark_scheduled_task_succeeded(
        self,
        *,
        task_id: str,
        finished_at: str,
        response_text: str,
    ) -> bool:
        safe_finished_at = self._normalize_utc_iso(finished_at)
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE scheduled_tasks
                SET
                    status = 'succeeded',
                    finished_at = ?,
                    locked_at = NULL,
                    updated_at = ?,
                    last_error = '',
                    last_response = ?
                WHERE task_id = ?
                  AND status = 'running'
                """,
                (
                    safe_finished_at,
                    safe_finished_at,
                    self._truncate_text(str(response_text), self._max_tool_payload_chars),
                    task_id,
                ),
            )
            connection.commit()
        return updated.rowcount == 1

    def mark_scheduled_task_retrying(
        self,
        *,
        task_id: str,
        retry_at: str,
        updated_at: str,
        error_text: str,
    ) -> bool:
        safe_retry_at = self._normalize_utc_iso(retry_at)
        safe_updated_at = self._normalize_utc_iso(updated_at)
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE scheduled_tasks
                SET
                    status = 'retrying',
                    next_attempt_at = ?,
                    locked_at = NULL,
                    updated_at = ?,
                    last_error = ?
                WHERE task_id = ?
                  AND status = 'running'
                """,
                (
                    safe_retry_at,
                    safe_updated_at,
                    self._truncate_text(str(error_text), self._max_message_chars),
                    task_id,
                ),
            )
            connection.commit()
        return updated.rowcount == 1

    def mark_scheduled_task_failed(
        self,
        *,
        task_id: str,
        finished_at: str,
        error_text: str,
    ) -> bool:
        safe_finished_at = self._normalize_utc_iso(finished_at)
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE scheduled_tasks
                SET
                    status = 'failed',
                    finished_at = ?,
                    locked_at = NULL,
                    updated_at = ?,
                    last_error = ?
                WHERE task_id = ?
                  AND status = 'running'
                """,
                (
                    safe_finished_at,
                    safe_finished_at,
                    self._truncate_text(str(error_text), self._max_message_chars),
                    task_id,
                ),
            )
            connection.commit()
        return updated.rowcount == 1

    def get_scheduled_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scheduled_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def list_scheduled_tasks(
        self,
        *,
        limit: int = 20,
        statuses: list[str] | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit), 1), 100)
        filters = []
        params: list[Any] = []
        if statuses:
            normalized = [str(status).strip().lower() for status in statuses if str(status).strip()]
            if normalized:
                placeholders = ",".join("?" for _ in normalized)
                filters.append(f"status IN ({placeholders})")
                params.extend(normalized)
        if user_id is not None and str(user_id).strip():
            filters.append("user_id = ?")
            params.append(str(user_id))

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        query = (
            "SELECT * FROM scheduled_tasks "
            f"{where_clause} "
            "ORDER BY "
            "CASE WHEN status IN ('pending', 'retrying', 'running') THEN 0 ELSE 1 END, "
            "next_attempt_at ASC, updated_at DESC "
            "LIMIT ?"
        )
        params.append(safe_limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

    def update_scheduled_task(
        self,
        *,
        task_id: str,
        updated_at: str,
        message: str | None = None,
        scheduled_for: str | None = None,
        scheduled_timezone: str | None = None,
        notify_email_to: str | None = None,
        recurrence_pattern: str | None = None,
        max_attempts: int | None = None,
    ) -> bool:
        set_clauses = ["updated_at = ?"]
        params: list[Any] = [self._normalize_utc_iso(updated_at)]
        if message is not None:
            clean_message = str(message).strip()
            if not clean_message:
                raise ValueError("Scheduled task message cannot be empty")
            set_clauses.append("message = ?")
            params.append(self._truncate_text(clean_message, self._max_message_chars))
        if scheduled_for is not None:
            normalized_scheduled_for = self._normalize_utc_iso(scheduled_for)
            set_clauses.append("scheduled_for = ?")
            set_clauses.append("next_attempt_at = ?")
            params.extend([normalized_scheduled_for, normalized_scheduled_for])
        if scheduled_timezone is not None:
            safe_scheduled_timezone = str(scheduled_timezone).strip()
            if not safe_scheduled_timezone:
                raise ValueError("scheduled_timezone cannot be empty")
            set_clauses.append("scheduled_timezone = ?")
            params.append(self._truncate_text(safe_scheduled_timezone, 64))
        if notify_email_to is not None:
            set_clauses.append("notify_email_to = ?")
            params.append(self._truncate_text(str(notify_email_to).strip(), 320))
        if recurrence_pattern is not None:
            set_clauses.append("recurrence_pattern = ?")
            params.append(self._normalize_recurrence_pattern(recurrence_pattern))
        if max_attempts is not None:
            safe_max_attempts = max(1, int(max_attempts))
            set_clauses.append("max_attempts = ?")
            params.append(safe_max_attempts)

        if len(set_clauses) == 1:
            return False

        params.append(task_id)
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                f"""
                UPDATE scheduled_tasks
                SET {", ".join(set_clauses)}
                WHERE task_id = ?
                  AND status IN ('pending', 'retrying')
                """,
                tuple(params),
            )
            connection.commit()
        return updated.rowcount == 1

    def reschedule_recurring_task(
        self,
        *,
        task_id: str,
        next_scheduled_for: str,
        updated_at: str,
    ) -> bool:
        normalized_next = self._normalize_utc_iso(next_scheduled_for)
        normalized_updated_at = self._normalize_utc_iso(updated_at)
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE scheduled_tasks
                SET
                    status = 'pending',
                    attempt_count = 0,
                    scheduled_for = ?,
                    next_attempt_at = ?,
                    locked_at = NULL,
                    started_at = NULL,
                    finished_at = NULL,
                    updated_at = ?,
                    last_error = ''
                WHERE task_id = ?
                  AND status = 'succeeded'
                """,
                (
                    normalized_next,
                    normalized_next,
                    normalized_updated_at,
                    task_id,
                ),
            )
            connection.commit()
        return updated.rowcount == 1

    def cancel_scheduled_task(
        self,
        *,
        task_id: str,
        cancelled_at: str,
        reason: str = "",
    ) -> bool:
        safe_cancelled_at = self._normalize_utc_iso(cancelled_at)
        with self._lock, self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE scheduled_tasks
                SET
                    status = 'cancelled',
                    finished_at = ?,
                    locked_at = NULL,
                    updated_at = ?,
                    last_error = ?
                WHERE task_id = ?
                  AND status IN ('pending', 'retrying', 'running')
                """,
                (
                    safe_cancelled_at,
                    safe_cancelled_at,
                    self._truncate_text(
                        str(reason or "Cancelled by user"),
                        self._max_message_chars,
                    ),
                    task_id,
                ),
            )
            connection.commit()
        return updated.rowcount == 1

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_utc_iso(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Expected UTC ISO timestamp")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _shift_utc_iso(base_timestamp: str, delta_seconds: int) -> str:
        normalized = ConversationMemoryStore._normalize_utc_iso(base_timestamp)
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        shifted = parsed + timedelta(seconds=int(delta_seconds))
        return shifted.replace(microsecond=0).isoformat().replace("+00:00", "Z")

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

                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    guild_id TEXT,
                    message TEXT NOT NULL,
                    scheduled_timezone TEXT NOT NULL DEFAULT 'UTC',
                    notify_email_to TEXT NOT NULL DEFAULT '',
                    recurrence_pattern TEXT NOT NULL DEFAULT 'none',
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    scheduled_for TEXT NOT NULL,
                    next_attempt_at TEXT NOT NULL,
                    locked_at TEXT,
                    started_at TEXT,
                    finished_at TEXT,
                    last_error TEXT NOT NULL DEFAULT '',
                    last_response TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status_next_attempt
                    ON scheduled_tasks (status, next_attempt_at);
                """
            )
            self._ensure_scheduled_tasks_migrations(connection)
            connection.commit()

    @staticmethod
    def _ensure_scheduled_tasks_migrations(connection: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(scheduled_tasks)").fetchall()
        }
        if "scheduled_timezone" not in columns:
            connection.execute(
                "ALTER TABLE scheduled_tasks ADD COLUMN scheduled_timezone TEXT NOT NULL DEFAULT 'UTC'"
            )
        if "notify_email_to" not in columns:
            connection.execute(
                "ALTER TABLE scheduled_tasks ADD COLUMN notify_email_to TEXT NOT NULL DEFAULT ''"
            )
        if "recurrence_pattern" not in columns:
            connection.execute(
                "ALTER TABLE scheduled_tasks ADD COLUMN recurrence_pattern TEXT NOT NULL DEFAULT 'none'"
            )

    @staticmethod
    def _normalize_recurrence_pattern(value: str | None) -> str:
        normalized = str(value or "none").strip().lower() or "none"
        if normalized not in SUPPORTED_RECURRENCE_PATTERNS:
            raise ValueError("Unsupported recurrence_pattern. Use none, daily, weekly or monthly.")
        return normalized

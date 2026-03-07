from __future__ import annotations

import csv
import os


CONTACTS_CSV_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "memories", "contacts.csv")
)
REQUIRED_COLUMNS = ("Nome", "email", "telefone", "relacionamento")


def _resolve_contacts_path(context) -> str:
    """Return per-user contacts.csv path if it exists, otherwise fall back to the global default."""
    memories_dir = str(getattr(context, "memories_dir", "") or "").strip()
    if memories_dir:
        user_contacts = os.path.join(memories_dir, "contacts.csv")
        if os.path.isfile(user_contacts):
            return user_contacts
    return CONTACTS_CSV_PATH


def search_contacts(arguments, context):
    query = str(arguments.get("query", "")).strip().lower()
    try:
        limit = int(arguments.get("limit", 20))
    except (ValueError, TypeError):
        raise ValueError("limit must be a valid integer")
    limit = min(max(limit, 1), 100)

    contacts_path = _resolve_contacts_path(context)
    contacts = _read_contacts_csv(contacts_path)
    if query:
        contacts = [
            contact
            for contact in contacts
            if query in contact["Nome"].lower()
            or query in contact["email"].lower()
            or query in contact["telefone"].lower()
            or query in contact["relacionamento"].lower()
        ]

    return {
        "total": len(contacts),
        "returned": min(limit, len(contacts)),
        "contacts": contacts[:limit],
    }


def _read_contacts_csv(contacts_path: str = CONTACTS_CSV_PATH):
    if not os.path.exists(contacts_path):
        raise FileNotFoundError(f"Contacts file not found: {contacts_path}")

    with open(contacts_path, "r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=",")
        header = [str(column).strip() for column in (reader.fieldnames or []) if column is not None]
        missing_columns = [column for column in REQUIRED_COLUMNS if column not in header]
        if missing_columns:
            raise ValueError(
                "Contacts CSV is missing required columns: " + ", ".join(missing_columns)
            )

        contacts = []
        for row in reader:
            clean_row = {str(key).strip(): value for key, value in row.items() if key is not None}
            contacts.append(
                {
                    "Nome": str(clean_row.get("Nome", "")).strip(),
                    "email": str(clean_row.get("email", "")).strip(),
                    "telefone": str(clean_row.get("telefone", "")).strip(),
                    "relacionamento": str(clean_row.get("relacionamento", "")).strip(),
                }
            )
        return contacts


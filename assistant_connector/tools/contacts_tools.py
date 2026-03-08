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


def _resolve_contacts_write_path(context) -> str:
    memories_dir = str(getattr(context, "memories_dir", "") or "").strip()
    if memories_dir:
        os.makedirs(memories_dir, exist_ok=True, mode=0o700)
        return os.path.join(memories_dir, "contacts.csv")

    default_dir = os.path.dirname(CONTACTS_CSV_PATH)
    os.makedirs(default_dir, exist_ok=True)
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


def register_contact_memory(arguments, context):
    name = str(arguments.get("name", "")).strip()
    email = str(arguments.get("email", "")).strip()
    phone = str(arguments.get("phone", "")).strip()
    relationship = str(arguments.get("relationship", "")).strip()

    if not name:
        raise ValueError("name is required")
    if not email and not phone:
        raise ValueError("email or phone is required")

    csv_path = _resolve_contacts_write_path(context)
    contact_row = {
        "Nome": name,
        "email": email,
        "telefone": phone,
        "relacionamento": relationship,
    }
    _append_contact_csv(csv_path, contact_row)

    return {
        "status": "ok",
        "contact": contact_row,
        "contacts_csv_path": csv_path,
    }


def _append_contact_csv(csv_path: str, contact_row: dict[str, str]) -> None:
    file_exists = os.path.isfile(csv_path)
    needs_header = (not file_exists) or os.path.getsize(csv_path) == 0
    with open(csv_path, "a", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=REQUIRED_COLUMNS, delimiter=",")
        if needs_header:
            writer.writeheader()
        writer.writerow(contact_row)

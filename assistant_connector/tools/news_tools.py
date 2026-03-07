from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import urlopen
import xml.etree.ElementTree as ET


DEFAULT_TIMEOUT_SECONDS = 8
SOURCES_CONFIG_PATH = Path(__file__).resolve().parents[2] / "news-sources" / "sources.json"
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL_TEMPLATE = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
SOURCE_REGISTRY = {
    "hackernews": {"kind": "hacker_news", "display_name": "Hacker News", "source_categories": ["technology"]},
    "techcrunch": {
        "kind": "rss",
        "display_name": "TechCrunch",
        "rss_url": "https://techcrunch.com/feed/",
        "source_categories": ["technology"],
    },
    "wsj": {
        "kind": "rss",
        "display_name": "WSJ",
        "rss_url": "https://feeds.a.dj.com/rss/RSSWSJD.xml",
        "source_categories": ["technology"],
    },
    "nytimes": {
        "kind": "rss",
        "display_name": "NYTimes",
        "rss_url": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
        "source_categories": ["technology"],
    },
}


def list_tech_news(arguments, _context):
    try:
        limit = int(arguments.get("limit", 8))
    except (ValueError, TypeError):
        raise ValueError("limit must be a valid integer")
    limit = min(max(limit, 1), 20)
    config = _load_sources_config()
    defaults = config.get("defaults", {})
    default_categories = _normalize_categories(defaults.get("categories"))
    cutoff_utc = _build_cutoff(defaults.get("date_filter", {}), now_utc=datetime.now(timezone.utc))
    requested_cutoff_utc = _build_requested_cutoff(arguments)
    if requested_cutoff_utc is not None and requested_cutoff_utc > cutoff_utc:
        cutoff_utc = requested_cutoff_utc
    topic = ", ".join(default_categories)

    all_items = []
    errors = []

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue
        source_name, source_kind, source_url, source_supported_categories = _resolve_source_strategy(source)
        source_categories = _normalize_categories(source.get("filters", {}).get("categories"), default_categories)
        source_cutoff = _build_cutoff(
            source.get("filters", {}).get("date_filter", {}),
            fallback=cutoff_utc,
            now_utc=datetime.now(timezone.utc),
        )
        try:
            if source_kind == "hacker_news":
                fetched_items = _fetch_hacker_news_items(cutoff_utc=source_cutoff)
            else:
                fetched_items = _fetch_rss_items(source_name, source_url, cutoff_utc=source_cutoff)
            all_items.extend(
                [
                    item
                    for item in fetched_items
                    if _matches_categories(
                        item,
                        source_categories,
                        source_supported_categories=source_supported_categories,
                    )
                ]
            )
        except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
            errors.append(f"{source_name}: {exc}")

    selected = all_items
    selected.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    selected = selected[:limit]

    return {
        "topic": topic,
        "total_collected": len(all_items),
        "returned": len(selected),
        "news": selected,
        "sources": sorted({item["source"] for item in all_items}),
        "errors": errors,
    }


def _load_sources_config():
    with SOURCES_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Invalid news sources configuration format.")
    if not isinstance(payload.get("sources"), list):
        raise ValueError("Invalid news sources configuration: 'sources' must be a list.")
    return payload


def _resolve_source_strategy(source: dict[str, object]):
    source_name = str(source.get("name", "")).strip()
    source_url = str(source.get("url", "")).strip()
    if not source_name:
        raise ValueError("Source entry missing 'name'.")
    if not source_url:
        raise ValueError(f"Source '{source_name}' missing 'url'.")

    normalized_name = source_name.lower()
    registry_entry = SOURCE_REGISTRY.get(normalized_name)
    if registry_entry:
        kind = str(registry_entry["kind"])
        resolved_url = str(registry_entry.get("rss_url", source_url))
        display_name = str(registry_entry.get("display_name", source_name))
        raw_supported_categories = registry_entry.get("source_categories", [])
        if isinstance(raw_supported_categories, list):
            supported_categories = [str(value).strip().lower() for value in raw_supported_categories if str(value).strip()]
        else:
            supported_categories = []
        return display_name, kind, resolved_url, supported_categories

    if "news.ycombinator.com" in source_url:
        return source_name, "hacker_news", source_url, []
    return source_name, "rss", source_url, []


def _normalize_categories(raw_categories, fallback=None):
    candidate = raw_categories if raw_categories is not None else fallback
    if candidate is None:
        raise ValueError("At least one category must be configured in news sources.")
    if not isinstance(candidate, list):
        raise ValueError("News categories must be provided as a list.")
    categories = [str(item).strip().lower() for item in candidate if str(item).strip()]
    if not categories:
        raise ValueError("At least one non-empty category must be configured in news sources.")
    return categories


def _build_cutoff(date_filter: dict[str, object], fallback: datetime | None = None, now_utc: datetime | None = None):
    reference_now_utc = now_utc or datetime.now(timezone.utc)
    if not date_filter:
        if fallback is not None:
            return fallback
        raise ValueError("Missing date_filter configuration.")
    mode = str(date_filter.get("mode", "")).strip().lower()
    if mode == "recent":
        try:
            lookback_days = int(date_filter.get("lookback_days", 0))
        except (ValueError, TypeError):
            raise ValueError("date_filter.lookback_days must be a valid integer.")
        if lookback_days <= 0:
            raise ValueError("date_filter.lookback_days must be a positive integer.")
        return reference_now_utc - timedelta(days=lookback_days)
    if mode == "today":
        return reference_now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValueError("Unsupported date_filter.mode. Use 'recent' or 'today'.")


def _matches_categories(item: dict[str, str], categories: list[str], *, source_supported_categories: list[str]):
    if source_supported_categories and any(category in source_supported_categories for category in categories):
        return True
    searchable_text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    normalized_aliases = {
        "technology": ["technology", "tech"],
    }
    for category in categories:
        candidate_terms = normalized_aliases.get(category, [category])
        if any(term in searchable_text for term in candidate_terms):
            return True
    return False


def _build_requested_cutoff(arguments):
    max_age_hours = arguments.get("max_age_hours")
    if max_age_hours is None:
        return None
    try:
        max_age_hours = int(max_age_hours)
    except (ValueError, TypeError):
        raise ValueError("max_age_hours must be a valid integer")
    max_age_hours = min(max(max_age_hours, 6), 168)
    return datetime.now(timezone.utc) - timedelta(hours=max_age_hours)


def _fetch_rss_items(source_name: str, rss_url: str, *, cutoff_utc: datetime):
    with urlopen(rss_url, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        payload = response.read()

    root = ET.fromstring(payload)
    items = []

    for item in root.findall("./channel/item"):
        parsed_item = _parse_rss_item(item, source_name=source_name)
        if parsed_item and _is_recent_enough(parsed_item.get("published_at"), cutoff_utc):
            items.append(parsed_item)

    for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
        parsed_item = _parse_atom_entry(entry, source_name=source_name)
        if parsed_item and _is_recent_enough(parsed_item.get("published_at"), cutoff_utc):
            items.append(parsed_item)

    return items


def _fetch_hacker_news_items(*, cutoff_utc: datetime):
    with urlopen(HN_TOP_STORIES_URL, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
        top_ids = json.loads(response.read().decode("utf-8"))

    items = []
    for item_id in top_ids[:30]:
        with urlopen(HN_ITEM_URL_TEMPLATE.format(item_id=item_id), timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))

        title = str(payload.get("title", "")).strip()
        url = str(payload.get("url", "")).strip()
        timestamp = payload.get("time")
        if not title or not url or not isinstance(timestamp, int):
            continue

        published_at = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        if not _is_recent_enough(published_at, cutoff_utc):
            continue

        items.append(
            {
                "title": title,
                "url": url,
                "source": "Hacker News",
                "published_at": published_at,
                "summary": "",
            }
        )
    return items


def _parse_rss_item(item: ET.Element, *, source_name: str):
    title = (item.findtext("title") or "").strip()
    url = (item.findtext("link") or "").strip()
    published = (item.findtext("pubDate") or item.findtext("published") or "").strip()
    summary = (item.findtext("description") or "").strip()
    if not title or not url:
        return None

    published_at = _normalize_datetime(published)
    return {
        "title": title,
        "url": url,
        "source": source_name,
        "published_at": published_at,
        "summary": summary,
    }


def _parse_atom_entry(entry: ET.Element, *, source_name: str):
    title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
    link_element = entry.find("{http://www.w3.org/2005/Atom}link")
    url = (link_element.get("href") if link_element is not None else "") or ""
    url = url.strip()
    published = (
        entry.findtext("{http://www.w3.org/2005/Atom}published")
        or entry.findtext("{http://www.w3.org/2005/Atom}updated")
        or ""
    ).strip()
    summary = (entry.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
    if not title or not url:
        return None

    published_at = _normalize_datetime(published)
    return {
        "title": title,
        "url": url,
        "source": source_name,
        "published_at": published_at,
        "summary": summary,
    }


def _normalize_datetime(raw_value: str) -> str:
    if not raw_value:
        return ""
    try:
        parsed = parsedate_to_datetime(raw_value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        parsed_iso = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if parsed_iso.tzinfo is None:
            parsed_iso = parsed_iso.replace(tzinfo=timezone.utc)
        return parsed_iso.astimezone(timezone.utc).isoformat()
    except ValueError:
        return ""


def _is_recent_enough(published_at: str, cutoff_utc: datetime) -> bool:
    if not published_at:
        return True
    try:
        published_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=timezone.utc)
    return published_dt >= cutoff_utc

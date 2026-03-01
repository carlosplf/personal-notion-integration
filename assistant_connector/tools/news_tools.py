from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.request import urlopen
import xml.etree.ElementTree as ET


DEFAULT_TIMEOUT_SECONDS = 8
RSS_SOURCES = {
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Verge": "https://www.theverge.com/rss/tech/index.xml",
    "Ars Technica": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "WIRED": "https://www.wired.com/feed/category/gear/latest/rss",
}
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL_TEMPLATE = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"


def list_tech_news(arguments, _context):
    limit = int(arguments.get("limit", 8))
    limit = min(max(limit, 1), 20)
    topic = str(arguments.get("topic", "technology")).strip() or "technology"
    include_hacker_news = bool(arguments.get("include_hacker_news", True))
    max_age_hours = int(arguments.get("max_age_hours", 36))
    max_age_hours = min(max(max_age_hours, 6), 168)

    all_items = []
    errors = []
    cutoff_utc = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    for source_name, rss_url in RSS_SOURCES.items():
        try:
            all_items.extend(_fetch_rss_items(source_name, rss_url, cutoff_utc=cutoff_utc))
        except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
            errors.append(f"{source_name}: {exc}")

    if include_hacker_news:
        try:
            all_items.extend(_fetch_hacker_news_items(cutoff_utc=cutoff_utc))
        except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
            errors.append(f"Hacker News: {exc}")

    normalized_topic = topic.lower()
    topic_filtered = [
        item
        for item in all_items
        if normalized_topic in item["title"].lower() or normalized_topic in item.get("summary", "").lower()
    ]
    selected = topic_filtered if topic_filtered else all_items
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

"""Main entry point for the Daily News Brief.

Run end-to-end:  python3 daily_brief.py
Dry run (no send): python3 daily_brief.py --no-send
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import pytz

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Load .env (no python-dotenv dependency to keep deps tight).
def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = val

_load_env_file(HERE / ".env")

from html_generator import render_html  # noqa: E402
from news_generator import fetch_daily_news  # noqa: E402
from weather_fetcher import WeatherFetcher  # noqa: E402


def _archive_paths(now_aest: datetime) -> tuple[Path, Path]:
    archive_dir = HERE / "archive"
    archive_dir.mkdir(exist_ok=True)
    date_slug = now_aest.strftime("%Y-%m-%d")
    return (
        archive_dir / f"daily-news-brief-{date_slug}.html",
        archive_dir / f"daily-news-brief-{date_slug}.json",
    )


def _short_text_preface(items: list[dict], now_aest: datetime) -> str:
    lines = [
        f"Daily News Brief — {now_aest.strftime('%A, %d %B %Y')}",
        "",
        "Today's top stories:",
    ]
    for it in items:
        title = (it.get("title") or "").strip()
        cat = it.get("category", "")
        lines.append(f"  • [{cat}] {title}")
    lines.append("")
    lines.append("Open the attached HTML file for the full brief.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-send", action="store_true",
                        help="Generate + archive but do not email.")
    parser.add_argument("--no-fetch", action="store_true",
                        help="Re-render today's archived JSON without re-querying news.")
    args = parser.parse_args()

    aest = pytz.timezone("Australia/Brisbane")
    now_aest = datetime.now(aest)
    html_path, json_path = _archive_paths(now_aest)

    if args.no_fetch and json_path.exists():
        print(f"[reuse] loading cached news from {json_path}", flush=True)
        items = json.loads(json_path.read_text())
    else:
        print("[news] querying Claude API with web_search…", flush=True)
        items = fetch_daily_news()
        json_path.write_text(json.dumps(items, indent=2, ensure_ascii=False))
        print(f"[news] cached → {json_path}", flush=True)

    print("[weather] fetching Brisbane weather…", flush=True)
    weather = WeatherFetcher().get_brisbane_weather()
    print(f"[weather] {weather}", flush=True)

    print("[html] rendering brief…", flush=True)
    html = render_html(weather, items)
    html_path.write_text(html, encoding="utf-8")
    print(f"[html] saved → {html_path}", flush=True)

    if args.no_send:
        print("[send] --no-send set; skipping email.", flush=True)
        return 0

    print("[send] sending via Gmail SMTP…", flush=True)
    from email_sender import send_brief  # imported late so --no-send works without creds
    edition = now_aest.strftime("%Y.%-m.%-d")
    subject = f"Daily News Brief — Edition {edition}"
    send_brief(
        html=html,
        subject=subject,
        attachment_filename=html_path.name,
        text_preface=_short_text_preface(items, now_aest),
    )
    print("[send] delivered.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)

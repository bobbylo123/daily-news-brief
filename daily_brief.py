"""Main entry point for the Daily News Brief.

Run end-to-end:  python3 daily_brief.py
Dry run (no send): python3 daily_brief.py --no-send
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import traceback
import urllib.error
import urllib.request
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


import re as _re
_IMG_EXT_RE = _re.compile(
    r'\.(jpg|jpeg|png|webp|gif|avif)(\?[^\s]*)?$', _re.IGNORECASE
)


def _url_has_image_extension(url: str) -> bool:
    """Return True only when the URL contains a recognised image file extension.

    URLs that end with bare digits, underscores, or letters (i.e. truncated
    or hallucinated URLs from the model) are rejected before we waste a
    network round-trip.
    """
    path = url.split("?")[0].split("#")[0]
    return bool(_IMG_EXT_RE.search(path))


def _embed_images(items: list[dict]) -> list[dict]:
    """Download each story's image and replace its URL with a base64 data URI.

    This makes images permanently visible in the HTML regardless of CDN
    hotlink-blocking — the image data lives inside the file itself.
    Images larger than 1.5 MB are skipped to keep the file size reasonable.
    """
    _HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    _MAX_BYTES = 1_500_000  # 1.5 MB

    for item in items:
        img_url = (item.get("image_url") or "").strip()
        if not img_url or img_url.startswith("data:"):
            continue

        # Reject URLs without a proper image extension — these are truncated /
        # hallucinated URLs that will always 404 and waste network time.
        if not _url_has_image_extension(img_url):
            print(
                f"[images] rejected (no image extension — likely truncated): "
                f"{img_url[:80]}",
                flush=True,
            )
            item["image_url"] = ""
            continue

        try:
            req = urllib.request.Request(img_url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=15) as resp:
                # Verify server actually returned an image content-type.
                srv_ctype = resp.headers.get_content_type() or ""
                if srv_ctype and not srv_ctype.startswith("image/"):
                    print(
                        f"[images] skipped (server returned {srv_ctype!r}): "
                        f"{img_url[:80]}",
                        flush=True,
                    )
                    item["image_url"] = ""
                    continue
                raw = resp.read(_MAX_BYTES + 1)
                if len(raw) > _MAX_BYTES:
                    print(f"[images] skipped (>1.5 MB): {img_url[:80]}", flush=True)
                    item["image_url"] = ""
                    continue
                ctype = srv_ctype or _guess_content_type(img_url)
            b64 = base64.b64encode(raw).decode("ascii")
            item["image_url"] = f"data:{ctype};base64,{b64}"
            print(f"[images] embedded {len(raw)//1024}KB: {img_url[:60]}…", flush=True)
        except Exception as exc:
            print(f"[images] failed ({type(exc).__name__}): {img_url[:80]}", flush=True)
            item["image_url"] = ""
    return items


def _guess_content_type(url: str) -> str:
    low = url.split("?")[0].lower()
    if low.endswith(".png"):
        return "image/png"
    if low.endswith(".gif"):
        return "image/gif"
    if low.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


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

    def _load_cached(p: Path):
        cached = json.loads(p.read_text())
        if isinstance(cached, list):
            return cached, {}
        return cached.get("items", cached), cached

    def _most_recent_archive() -> Path | None:
        archive_dir = HERE / "archive"
        if not archive_dir.exists():
            return None
        candidates = sorted(archive_dir.glob("daily-news-brief-*.json"), reverse=True)
        for c in candidates:
            if c != json_path:
                return c
        return None

    if args.no_fetch and json_path.exists():
        print(f"[reuse] loading cached news from {json_path}", flush=True)
        items, brief_meta = _load_cached(json_path)
    else:
        print("[news] querying Claude API with web_search…", flush=True)
        try:
            result = fetch_daily_news()
            items = result["items"]
            brief_meta = result
            json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
            print(f"[news] cached → {json_path}", flush=True)
        except Exception as fetch_err:
            print(f"[news] FETCH FAILED after retries: {fetch_err}", flush=True)
            fallback = _most_recent_archive()
            if fallback is None:
                print("[news] no fallback archive available; aborting.", flush=True)
                raise
            print(f"[news] FALLBACK: re-using most recent archive {fallback.name}", flush=True)
            items, brief_meta = _load_cached(fallback)
            brief_meta = dict(brief_meta or {})
            brief_meta["daily_note"] = (
                f"News fetch unavailable today; this brief re-uses {fallback.stem.split('-')[-3]}-"
                f"{fallback.stem.split('-')[-2]}-{fallback.stem.split('-')[-1]} content."
            )

    print("[images] downloading and embedding story images…", flush=True)
    items = _embed_images(items)

    print("[weather] fetching Brisbane weather…", flush=True)
    weather = WeatherFetcher().get_brisbane_weather()
    print(f"[weather] {weather}", flush=True)

    print("[html] rendering brief…", flush=True)
    html = render_html(weather, items, brief_meta)
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

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
from news_generator import fetch_daily_news, fetch_top_stocks  # noqa: E402
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
import urllib.parse as _urlparse_mod

_IMG_EXT_RE = _re.compile(
    r'\.(jpg|jpeg|png|webp|gif|avif)(\?[^\s]*)?$', _re.IGNORECASE
)


def _url_has_image_extension(url: str) -> bool:
    """Return True only when the URL contains a recognised image file extension.

    Handles:
    - Direct image URLs:  https://cdn.site.com/photo.jpg
    - Query-nested URLs:  https://dims.apnews.com/.../?url=https%3A%2F%2F...photo.jpg
    - URLs with image ext before query string params like /format/webp

    URLs that end with bare digits, underscores, or letters (i.e. truncated
    or hallucinated URLs from the model) are rejected before we waste a
    network round-trip.
    """
    path = url.split("#")[0]
    # Check path before query string
    path_only = path.split("?")[0]
    if _IMG_EXT_RE.search(path_only):
        return True
    # Check for nested URL in query params (AP dims, Cloudflare image proxies, etc.)
    try:
        qs = _urlparse_mod.urlparse(url).query
        params = _urlparse_mod.parse_qs(qs)
        for key in ("url", "src", "image", "img"):
            nested_urls = params.get(key, [])
            for nested in nested_urls:
                if _IMG_EXT_RE.search(nested.split("?")[0]):
                    return True
    except Exception:
        pass
    return False


def _fetch_og_image(article_url: str) -> str:
    """Scrape the article page and extract the og:image / twitter:image URL.

    News sites always set og:image for social sharing, so this is a reliable
    fallback when the Claude-provided image URL is stale or returns 404/403.

    Returns the image URL string, or "" if nothing could be found.
    """
    if not article_url or not article_url.startswith("http"):
        return ""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            # No Accept-Encoding so we get plain text without decompression headaches
            "DNT": "1",
        }
        req = urllib.request.Request(article_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            # Read content_encoding INSIDE the with block before connection closes
            content_encoding = (resp.headers.get("Content-Encoding") or "").lower()
            # Only read the first 64 KB — og:image is always in <head>
            raw_bytes = resp.read(65536)

        # Decompress if the server sent compressed content despite our request
        if content_encoding in ("gzip", "x-gzip"):
            import gzip as _gzip
            try:
                raw_bytes = _gzip.decompress(raw_bytes)
            except Exception:
                pass
        elif content_encoding == "br":
            try:
                import brotli as _brotli
                raw_bytes = _brotli.decompress(raw_bytes)
            except ImportError:
                pass

        html_snippet = raw_bytes.decode("utf-8", errors="replace")
        # Search for og:image or twitter:image meta tags (attribute order varies by site)
        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']',
            # Some sites use double-encoded or unquoted content attributes
            r'property=["\']og:image["\'][^>]+content=([^\s>]+)',
        ]
        for pat in patterns:
            m = _re.search(pat, html_snippet, _re.IGNORECASE)
            if m:
                img_url = m.group(1).strip().strip('"\'')
                if img_url.startswith("http"):
                    return img_url
        return ""
    except Exception as exc:
        print(f"[og:image] fetch failed for {article_url[:60]}: {type(exc).__name__}", flush=True)
        return ""


def _embed_images(items: list[dict]) -> list[dict]:
    """Download each story's image and replace its URL with a base64 data URI.

    This makes images permanently visible in the HTML regardless of CDN
    hotlink-blocking — the image data lives inside the file itself.
    Images larger than 1.5 MB are skipped to keep the file size reasonable.

    Strategy (in order):
    1. Try the Claude-provided image_url directly (fast path).
    2. If that fails for any reason, scrape the article page for og:image /
       twitter:image meta tags — news sites always set these for social sharing.
    3. Try to download the og:image URL.
    Only give up and set image_url="" if both attempts fail.

    Key technique: we set the HTTP Referer header to the image's own domain.
    Most CDN hotlink-protection checks only that the Referer comes from their
    own site — spoofing it in this way bypasses 403s from Al Jazeera, AP,
    Reuters, etc. without any third-party dependency.
    """
    _BASE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
        "DNT": "1",
    }
    _MAX_BYTES = 1_500_000  # 1.5 MB

    def _try_download(url: str, skip_ext_check: bool = False) -> tuple[bytes, str] | None:
        """Attempt to download a single image URL.

        Returns (raw_bytes, content_type) on success, or None on failure.
        Handles Referer spoofing and content-type validation internally.

        skip_ext_check=True bypasses the file-extension filter — use this for
        og:image URLs from trusted article pages (Reuters, Bloomberg etc. use
        opaque CDN URLs without file extensions).
        """
        if not skip_ext_check and not _url_has_image_extension(url):
            print(
                f"[images] rejected (no image extension — likely truncated): "
                f"{url[:80]}",
                flush=True,
            )
            return None
        try:
            parsed  = _urlparse_mod.urlparse(url)
            referer = f"{parsed.scheme}://{parsed.hostname}/"
            headers = {**_BASE_HEADERS, "Referer": referer}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                srv_ctype = resp.headers.get_content_type() or ""
                if srv_ctype and not srv_ctype.startswith("image/"):
                    print(f"[images] skipped (server returned {srv_ctype!r}): {url[:80]}", flush=True)
                    return None
                raw = resp.read(_MAX_BYTES + 1)
                if len(raw) > _MAX_BYTES:
                    print(f"[images] skipped (>1.5 MB): {url[:80]}", flush=True)
                    return None
                ctype = srv_ctype or _guess_content_type(url)
            return raw, ctype
        except Exception as exc:
            print(f"[images] failed ({type(exc).__name__}): {url[:80]}", flush=True)
            return None

    for item in items:
        img_url = (item.get("image_url") or "").strip()
        if img_url.startswith("data:"):
            continue  # already embedded, skip

        result = None

        # --- Pass 1: try the Claude-provided URL ---
        if img_url:
            result = _try_download(img_url)

        # --- Pass 2: og:image scraping fallback ---
        if result is None:
            article_url = ""
            # Try to find the article URL from lead_source or url fields
            ls = item.get("lead_source") or {}
            article_url = (
                ls.get("url") or
                item.get("article_url") or
                item.get("url") or
                ""
            ).strip()
            if article_url:
                if img_url:
                    print(f"[og:image] primary failed; scraping {article_url[:70]}…", flush=True)
                else:
                    print(f"[og:image] no image URL; scraping {article_url[:70]}…", flush=True)
                og_url = _fetch_og_image(article_url)
                if og_url:
                    print(f"[og:image] found → {og_url[:80]}", flush=True)
                    result = _try_download(og_url, skip_ext_check=True)
                    if result is None:
                        print(f"[og:image] download failed for scraped URL", flush=True)
                else:
                    print(f"[og:image] no og:image tag found on page", flush=True)

        if result is not None:
            raw, ctype = result
            b64 = base64.b64encode(raw).decode("ascii")
            item["image_url"] = f"data:{ctype};base64,{b64}"
            print(f"[images] embedded {len(raw)//1024}KB ✓", flush=True)
        else:
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
            # Try today's own JSON first (in case this is a re-run of a partial failure).
            fallback = json_path if json_path.exists() else _most_recent_archive()
            if fallback is None:
                print("[news] no fallback archive available; aborting.", flush=True)
                raise
            print(f"[news] FALLBACK: re-using archive {fallback.name}", flush=True)
            items, brief_meta = _load_cached(fallback)
            brief_meta = dict(brief_meta or {})
            brief_meta["daily_note"] = (
                f"News fetch unavailable today; this brief re-uses {fallback.stem.split('-')[-3]}-"
                f"{fallback.stem.split('-')[-2]}-{fallback.stem.split('-')[-1]} content."
            )

    print("[stocks] fetching top-5 US intraday picks via Claude + web_search…", flush=True)
    try:
        top_stocks_data = fetch_top_stocks()
        brief_meta["top_stocks_data"] = top_stocks_data
        print(
            f"[stocks] got {len(top_stocks_data.get('stocks', []))} picks "
            f"for session {top_stocks_data.get('session_aest', '')}",
            flush=True,
        )
    except Exception as stocks_err:
        print(f"[stocks] FAILED (non-fatal): {stocks_err}", flush=True)
        brief_meta["top_stocks_data"] = None

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

    # Heartbeat: tell healthchecks.io we successfully delivered. If this URL
    # isn't pinged within the daily window configured at healthchecks.io,
    # the user gets an email alert. Optional — only fires if env var set.
    hc_url = os.environ.get("HEALTHCHECKS_PING_URL", "").strip()
    if hc_url:
        try:
            urllib.request.urlopen(hc_url, timeout=10).read()
            print("[heartbeat] healthchecks.io pinged ✓", flush=True)
        except Exception as exc:
            print(f"[heartbeat] healthchecks ping failed (non-fatal): {exc}", flush=True)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)

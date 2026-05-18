"""News content generator backed by Google Gemini 2.0 Flash + Google Search.

Same public interface as the previous Anthropic version — fetch_daily_news()
and fetch_top_stocks() return identical structures so no other file needs
changing.

Cost: $0/month on Gemini free tier (1,500 requests/day; we use 2/day).
Requires: GEMINI_API_KEY env var (get free key at https://ai.google.dev)
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from google import genai
from google.genai import types

CATEGORIES = ["Global", "Business & Markets", "Hong Kong"]

# ---------------------------------------------------------------------------
# Prompts — news brief
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the senior editor of an elite daily news brief.
Your reader is in Brisbane and needs a fact-checked, balanced,
multi-perspective digest each morning. Tone: direct, formal, precise, logical.

Sourcing rules (strict):
* Cite ONLY top-tier mainstream news outlets: Reuters, AP, Bloomberg, BBC, FT,
  NYT, WSJ, The Guardian, Al Jazeera, NHK, ABC News (Australia), SCMP, RTHK,
  HKFP, Nikkei Asia, CNN, CNBC, etc.
* Wikipedia, Wikimedia, Fandom, or any wiki are FORBIDDEN as a source or image.
* Every URL must be a real, currently-resolvable article URL.
* Verify each fact across at least two outlets before stating it.

Use Google Search aggressively to research today's top stories.
When done, output ONLY a single valid JSON object — no markdown, no explanation."""

USER_PROMPT_TEMPLATE = """Today is {date_str} (Brisbane / AEST).

Find TODAY'S single most newsworthy story for EACH of these three categories:

  1. Global              — world-affairs, geopolitics, conflict, climate, science
  2. Business & Markets  — macro, equities, FX, central banks, major corporates
  3. Hong Kong           — HK politics, economy, society, regulation, finance

For each story gather:
  * The official headline from the lead source.
  * A direct article URL from the lead outlet.
  * A topical photograph URL — STRICT RULES (leave empty if any rule fails):
      1. You MUST have seen this EXACT URL in a search result or on a page.
         DO NOT construct, guess, or truncate a URL.
      2. URL MUST end with a recognised image extension: .jpg .jpeg .png .webp .gif
      3. Strongly prefer these embeddable CDNs:
           BBC:      https://ichef.bbci.co.uk/news/1024/cpsprodpb/XXXX/live/XXXX.jpg
           Reuters:  https://cloudfront-us-east-2.images.arcpublishing.com/reuters/XXXX.jpg
           AP:       https://dims.apnews.com/dims4/default/XXXX/strip/true/XXXX.jpg
           AJ:       https://www.aljazeera.com/wp-content/uploads/YYYY/MM/XXXX.jpg
      4. Avoid CBS News, CNBC, SCMP CDNs — they block hotlinking.
  * A video URL — STRICT RULES (leave empty if any rule fails):
      1. Must contain "watch?v=" — channel/playlist pages forbidden.
      2. You MUST have confirmed this URL in a search result.
      3. Preferred: BBC News, Reuters, Bloomberg, AP Archive, Al Jazeera.
      4. Fill video_channel with plain channel name e.g. "BBC News".
  * 6-8 attributed summary bullets (each cites outlet + URL).
  * 4 reporting angles each from a DIFFERENT outlet.
  * 3-4 stakeholder perspectives. Stance field: 1-3 words ONLY (e.g. "Hawkish").
  * One visual aid as inline HTML (timeline table, comparison table, or mindmap).
    Use only inline styles. No <script>, no external CSS. Max ~1500 characters.

Top-level fields also required:
  * quote_of_day: most striking verbatim quote from today's three stories.
  * market_numbers: 4-6 key figures (S&P 500, NASDAQ, ASX 200, USD/AUD, Gold, Bitcoin).
    label: short name only. value: number only. change: percentage with sign only.
  * daily_note: one sharp analytical sentence (20-30 words) on today's overarching theme.
  * key_events_to_watch: 3-4 specific upcoming events tied to today's stories.
    Each needs a short date and one sentence (max 15 words).

Output ONLY this JSON object — no markdown fences, no extra text:

{{
  "daily_note": "<20-30 word analytical sentence>",
  "quote_of_day": {{"quote": "...", "speaker": "<full name and title>", "source": "<outlet>"}},
  "market_numbers": [
    {{"label": "S&P 500", "value": "5,432", "change": "+1.2%"}},
    {{"label": "NASDAQ", "value": "17,890", "change": "-0.8%"}},
    {{"label": "ASX 200", "value": "7,234", "change": "+0.5%"}},
    {{"label": "USD/AUD", "value": "0.6412", "change": "-0.3%"}}
  ],
  "key_events_to_watch": [
    {{"date": "May 21", "event": "<one concise sentence max 15 words>"}}
  ],
  "items": [
    {{
      "category": "Global",
      "title": "<verbatim headline>",
      "lead_source": {{"name": "<outlet>", "url": "<article URL>"}},
      "image_url": "<full CDN URL with image extension, or empty string>",
      "video_url": "<YouTube watch?v= URL, or empty string>",
      "video_channel": "<channel name, or empty string>",
      "summary_bullets": [
        {{"text": "<fact>", "source": "<outlet>", "url": "<URL>"}}
      ],
      "reporting_angles": [
        {{"angle": "<angle label>", "outlet": "<outlet>", "summary": "<2-3 sentences>", "url": "<URL>"}}
      ],
      "perspectives": [
        {{"stakeholder": "<who>", "stance": "<1-3 words>", "quote_or_paraphrase": "<text>", "source": "<outlet>", "url": "<URL>"}}
      ],
      "visual_aid": {{"type": "table", "title": "<title>", "html": "<inline HTML only>"}}
    }},
    {{ "category": "Business & Markets", ... }},
    {{ "category": "Hong Kong", ... }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Prompts — stock picks
# ---------------------------------------------------------------------------

STOCK_SYSTEM_PROMPT = """You are an aggressive US equity momentum analyst hunting for
explosive intraday movers on NYSE and NASDAQ. Your sole task is to find the 4 US stocks
with the HIGHEST potential intraday gain during TODAY's regular session (9:30 am – 4:00 pm EDT).

Target profile — ONLY include stocks that fit at least one of these high-upside setups:
  A. FDA BINARY EVENT  : PDUFA dates, CRL decisions, fast-track/breakthrough designations.
  B. EARNINGS SURPRISE : Small/mid-cap beating EPS by >15% or revenue by >10%.
  C. SHORT SQUEEZE     : Stock with >20% short float + fresh positive catalyst + rising volume.
  D. PRE-MARKET GAPPER : Already up >15% pre-market on news.
  E. M&A / TAKEOVER    : Acquisition announcement at a significant premium.
  F. MAJOR ANALYST UPGRADE: Strong buy initiation or target-price doubling by a tier-1 firm.

Use Google Search to research all six setup types. Then output ONLY a single valid JSON object."""

STOCK_USER_PROMPT_TEMPLATE = """Today is {date_str} (Brisbane/AEST).
The US regular trading session is {us_date_str}: 9:30 am – 4:00 pm EDT
(= {aest_open_str} – {aest_close_str} AEST on {aest_dates_str}).

Execute this research checklist using Google Search:
1. Search "FDA PDUFA dates {us_date_str}" and "FDA drug approval decision today".
2. Search "pre-market top gainers today {us_date_str}".
3. Search "earnings surprise {us_date_str} small cap beat".
4. Search "short squeeze stocks {us_date_str}".
5. Search "unusual options activity {us_date_str}".
6. Search "acquisition merger announcement today {us_date_str}".
7. For each shortlisted candidate search "[TICKER] news {us_date_str}".
8. Select top 4 by expected intraday gain. Minimum expected gain: +30%.

Output ONLY this JSON object — no markdown, no extra text:

{{
  "session_date_us": "{us_date_str}",
  "session_aest": "{aest_open_str} – {aest_close_str} AEST {aest_dates_str}",
  "stocks": [
    {{
      "rank": 1,
      "ticker": "XXXX",
      "company": "<full name>",
      "sector": "<sector>",
      "last_price": "$0.00",
      "setup_type": "FDA Decision",
      "expected_gain_pct": "+40-80%",
      "key_factors": "<1-2 plain English sentences for a beginner>",
      "entry_price": "$0.00–$0.00",
      "stop_loss": "$0.00 (-12%)",
      "take_profit": "$0.00–$0.00 (+60-95%)",
      "risk_reward_ratio": "1:5",
      "technical_summary": "<2-3 key signals: short float %, RSI, volume vs avg>",
      "risk_level": "High",
      "confidence_level": "High"
    }}
  ]
}}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Get a free key at https://ai.google.dev"
        )
    return genai.Client(api_key=key)


def _debug_dir() -> Path:
    p = Path(__file__).resolve().parent / "logs"
    p.mkdir(exist_ok=True)
    return p


def _extract_json(text: str) -> dict:
    """Extract a JSON object from model response, handling markdown fences."""
    text = text.strip()
    # Strip markdown code fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    # Find outermost { ... }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(
            f"No JSON object in model response. First 500 chars:\n{text[:500]}"
        )
    return json.loads(text[start:end])


def _gemini_call(
    client: genai.Client,
    model: str,
    system: str,
    prompt: str,
    label: str,
) -> str:
    """Call Gemini with Google Search grounding, with retry on transient errors."""
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.3,
    )
    backoff = [30, 60, 90, 120, 180, 240]
    last_err: Exception | None = None
    for attempt in range(len(backoff) + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            return response.text
        except Exception as exc:
            last_err = exc
            if attempt >= len(backoff):
                break
            wait = backoff[attempt]
            print(
                f"[{label}] API error ({type(exc).__name__}); "
                f"retrying in {wait}s (attempt {attempt + 2}/{len(backoff) + 1})…",
                flush=True,
            )
            time.sleep(wait)
    raise last_err or RuntimeError(f"[{label}] no response after retries")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_daily_news(model: str = "gemini-2.0-flash") -> dict[str, Any]:
    """Fetch today's top 3 stories using Gemini + Google Search.

    Returns the same dict structure as the previous Anthropic version:
    {"items": [...], "quote_of_day": {...}, "market_numbers": [...],
     "daily_note": "...", "key_events_to_watch": [...]}
    """
    client = _client()
    aest = pytz.timezone("Australia/Brisbane")
    now = datetime.now(aest)
    date_str = now.strftime("%A, %d %B %Y")

    print(f"[news] querying Gemini {model} with Google Search…", flush=True)
    prompt = USER_PROMPT_TEMPLATE.format(date_str=date_str)
    raw_text = _gemini_call(client, model, SYSTEM_PROMPT, prompt, "news")

    # Persist raw response for debugging
    debug_path = _debug_dir() / f"news-raw-{now.strftime('%Y-%m-%d')}.json"
    debug_path.write_text(raw_text)

    try:
        submission = _extract_json(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Gemini returned unparseable JSON. Error: {exc}\n"
            f"Raw (first 1000 chars):\n{raw_text[:1000]}"
        ) from exc

    items = submission.get("items", [])
    if isinstance(items, str):
        items = json.loads(items)
    if not isinstance(items, list) or len(items) != 3:
        raise ValueError(f"Expected 3 items, got: {len(items) if isinstance(items, list) else type(items)}")

    by_cat = {it.get("category"): it for it in items}
    ordered = []
    for cat in CATEGORIES:
        if cat not in by_cat:
            raise ValueError(f"Missing category '{cat}' in Gemini output")
        ordered.append(_normalise(by_cat[cat]))

    return {
        "items": ordered,
        "quote_of_day": submission.get("quote_of_day") or {},
        "market_numbers": submission.get("market_numbers") or [],
        "key_events_to_watch": submission.get("key_events_to_watch") or [],
        "daily_note": submission.get("daily_note") or "",
    }


def fetch_top_stocks(model: str = "gemini-2.0-flash") -> dict[str, Any]:
    """Fetch top 4 US intraday stock picks using Gemini + Google Search."""
    from datetime import timedelta, time as _time

    client = _client()
    aest = pytz.timezone("Australia/Brisbane")
    edt = pytz.timezone("America/New_York")
    now_aest = datetime.now(aest)

    target_us_date = _next_us_trading_date(now_aest, aest, edt)
    us_open = edt.localize(datetime.combine(target_us_date, _time(9, 30)))
    us_close = edt.localize(datetime.combine(target_us_date, _time(16, 0)))
    aest_open = us_open.astimezone(aest)
    aest_close = us_close.astimezone(aest)

    date_str = now_aest.strftime("%A, %d %B %Y")
    us_date_str = us_open.strftime("%A, %d %B %Y")
    aest_open_str = aest_open.strftime("%-I:%M %p")
    aest_close_str = aest_close.strftime("%-I:%M %p")
    if aest_open.date() == aest_close.date():
        aest_dates_str = aest_open.strftime("%a %-d %b")
    else:
        aest_dates_str = (
            f"{aest_open.strftime('%a %-d %b')} – {aest_close.strftime('%a %-d %b')}"
        )

    is_weekend = now_aest.weekday() in (4, 5, 6)
    weekend_note = (
        f"\nNOTE: This brief is published on {now_aest.strftime('%A')} AEST. "
        f"The US market is CLOSED until Monday. Research weekend catalysts."
    ) if is_weekend else ""

    prompt = STOCK_USER_PROMPT_TEMPLATE.format(
        date_str=date_str,
        us_date_str=us_date_str,
        aest_open_str=aest_open_str,
        aest_close_str=aest_close_str,
        aest_dates_str=aest_dates_str,
    ) + weekend_note

    print(f"[stocks] querying Gemini {model} with Google Search…", flush=True)
    raw_text = _gemini_call(client, model, STOCK_SYSTEM_PROMPT, prompt, "stocks")

    try:
        submission = _extract_json(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Gemini returned unparseable JSON for stocks. Error: {exc}"
        ) from exc

    stocks = submission.get("stocks") or []
    stocks.sort(key=lambda s: s.get("rank", 99))
    return {
        "stocks": stocks,
        "session_date_us": submission.get("session_date_us", us_date_str),
        "session_aest": submission.get(
            "session_aest",
            f"{aest_open_str} – {aest_close_str} AEST {aest_dates_str}",
        ),
    }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _normalise(item: dict[str, Any]) -> dict[str, Any]:
    item.setdefault("image_url", "")
    item.setdefault("video_channel", "")
    item.setdefault("summary_bullets", [])
    item.setdefault("reporting_angles", [])
    item.setdefault("perspectives", [])
    item.setdefault("visual_aid", {"type": "table", "title": "", "html": ""})
    item.setdefault("lead_source", {"name": "", "url": ""})
    video = item.get("video_url") or ""
    item["video_url"] = video if "watch?v=" in video else ""
    return item


def _next_us_trading_date(now_aest: datetime, aest_tz, edt_tz):
    from datetime import timedelta, time as _time
    aest_weekday = now_aest.weekday()
    edt_date = now_aest.astimezone(edt_tz).date()
    if aest_weekday in (4, 5, 6):
        days_to_monday = (7 - edt_date.weekday()) % 7
        if days_to_monday == 0:
            days_to_monday = 7
        target = edt_date + timedelta(days=days_to_monday)
    else:
        target = edt_date + timedelta(days=1)
        while target.weekday() in (5, 6):
            target += timedelta(days=1)
    return target

"""News content generator backed by Claude API + web_search.

Returns a list of three structured news items (Global, Business & Markets,
Hong Kong), each with rich analytical content per the daily-brief spec.

Uses Anthropic tool-use with a strict JSON schema for the FINAL submission, so
the model is forced to return valid, parseable structured data. Web search is
provided as a separate server-side tool the model uses for research.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
import pytz

CATEGORIES = ["Global", "Business & Markets", "Hong Kong"]

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

Workflow:
1. Use web_search aggressively to find today's biggest story per category.
2. Read enough context to assemble multi-angle, multi-stakeholder coverage.
3. When complete, call the `submit_daily_brief` tool ONCE with the full
   structured payload. Do not write prose afterwards."""

USER_PROMPT_TEMPLATE = """Today is {date_str} (Brisbane / AEST).

Find TODAY'S single most newsworthy story for EACH of these three categories:

  1. Global              — world-affairs, geopolitics, conflict, climate, science
                           (NOT business/markets, NOT Hong Kong)
  2. Business & Markets  — macro, equities, FX, central banks, major corporates
  3. Hong Kong           — HK politics, economy, society, regulation, finance
                           (must be HK-centric, not just mainland China)

For each story, gather:
  * The official headline (verbatim from the lead source).
  * A direct article URL from the lead outlet.
  * A topical news photograph URL. STRICT RULES — failure to follow = leave empty:
      1. You MUST have seen this EXACT URL in a search result or on a web page.
         DO NOT construct, guess, or truncate a URL. A missing image is far better
         than a broken or partial link.
      2. The URL MUST end with a recognised image extension: .jpg .jpeg .png .webp
         or .gif — URLs that end with digits, underscores, or letters without an
         extension are FORBIDDEN and must be left empty.
      3. Strongly prefer these embeddable CDNs (in order):
           a. BBC:     https://ichef.bbci.co.uk/news/1024/cpsprodpb/XXXX/live/XXXX.jpg
           b. Reuters: https://cloudfront-us-east-2.images.arcpublishing.com/reuters/XXXX.jpg
           c. AP:      https://dims.apnews.com/dims4/default/XXXX/XXXX/strip/true/XXXX.jpg
           d. Al Jazeera: https://www.aljazeera.com/wp-content/uploads/YYYY/MM/XXXX.jpg
      4. To find the exact URL: use web_search to open the article page, then copy
         the full src= value of the lead image — do not shorten or paraphrase it.
      5. Avoid CBS News, CNBC, SCMP CDNs — they block hotlinking.
      6. If you cannot find a complete, verified URL with an image extension, leave empty.
  * A direct video-report URL. STRICT RULES — failure to follow = leave empty:
      1. Use web_search to find the video (e.g. search YouTube for the headline).
      2. The URL MUST contain "watch?v=" — channel pages and playlists are forbidden.
      3. You MUST have seen the video in a search result or web page before including it.
         DO NOT construct or guess a URL. If you cannot find a real, confirmed URL, leave
         video_url empty — a missing video is far better than a broken link.
      4. Preferred channels: BBC News, Reuters, Bloomberg Television, AP Archive,
         CNN, Al Jazeera English, RTHK, SCMP.
      5. Also fill in video_channel with the plain channel name (e.g. "BBC News",
         "Al Jazeera English"). If video_url is empty, leave video_channel empty too.
  * 6-8 attributed summary bullets (each cites an outlet + URL).
  * 4 different reporting angles, EACH from a different outlet.
  * 3-4 stakeholder perspectives. For each stance field: use 1-3 words ONLY
    (e.g. "Hawkish", "Cautiously Optimistic", "Opposed", "Sceptical").
    Do NOT write full sentences in the stance field.
  * One genuinely useful visual aid as inline HTML (a timeline table, a
    stakeholder comparison table, a mindmap as a nested list, a numbers
    table, etc.). Use only inline styles, no <script>, no external CSS,
    no <link> tags. Keep it under ~1500 characters.

Also provide these three top-level fields:
  * quote_of_day: The single most striking verbatim quote from any of today's
    three stories. Include the speaker's full name and title, and the outlet.
  * market_numbers: 4-6 key stock/financial figures relevant to today's
    Business & Markets story. Typical labels: S&P 500, NASDAQ, ASX 200,
    USD/AUD, Gold (oz), Bitcoin. For each:
      - label: short ticker/index name only (e.g. "S&P 500", "Gold (oz)")
      - value: clean number only (e.g. "5,432" or "$101") — NO narrative text
      - change: percentage with sign only (e.g. "+1.2%" or "-0.8%") — NO narrative
  * daily_note: One sharp, analytical sentence (20-30 words) capturing the
    overarching theme connecting today's three stories. Written as a senior
    editor's insight, not a summary. No clichés.

When the research is done, call the `submit_daily_brief` tool ONCE with all
three stories in the order: Global, Business & Markets, Hong Kong."""

# JSON schema describing the brief — passed as a tool's input_schema so the
# model is forced into validated structured output.
SUBMIT_TOOL = {
    "name": "submit_daily_brief",
    "description": (
        "Submit the final structured daily news brief. Call this exactly once "
        "after research is complete. Do not call any other tool afterwards."
    ),
    "input_schema": {
        "type": "object",
        "required": ["items", "quote_of_day", "market_numbers", "daily_note"],
        "properties": {
            "daily_note": {
                "type": "string",
                "description": "One sharp editorial sentence (20-30 words) on today's overarching theme",
            },
            "quote_of_day": {
                "type": "object",
                "required": ["quote", "speaker", "source"],
                "properties": {
                    "quote": {"type": "string", "description": "Verbatim striking quote from today's coverage"},
                    "speaker": {"type": "string", "description": "Full name and title of the speaker"},
                    "source": {"type": "string", "description": "News outlet name"},
                },
            },
            "market_numbers": {
                "type": "array",
                "minItems": 4,
                "maxItems": 6,
                "description": "Key stock market / financial figures from today's Business story",
                "items": {
                    "type": "object",
                    "required": ["label", "value", "change"],
                    "properties": {
                        "label": {"type": "string", "description": "Index or ticker name e.g. S&P 500, ASX 200, USD/AUD, Gold"},
                        "value": {"type": "string", "description": "Current level e.g. 5,432 or 0.6412"},
                        "change": {"type": "string", "description": "Change with sign e.g. +1.2% or -0.8%"},
                    },
                },
            },
            "items": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "required": [
                        "category", "title", "lead_source",
                        "summary_bullets", "reporting_angles",
                        "perspectives", "visual_aid",
                    ],
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["Global", "Business & Markets", "Hong Kong"],
                        },
                        "title": {"type": "string", "minLength": 8},
                        "lead_source": {
                            "type": "object",
                            "required": ["name", "url"],
                            "properties": {
                                "name": {"type": "string"},
                                "url": {"type": "string"},
                            },
                        },
                        "image_url": {"type": "string"},
                        "video_url": {"type": "string"},
                        "video_channel": {"type": "string", "description": "Plain channel name e.g. BBC News, Al Jazeera English"},
                        "summary_bullets": {
                            "type": "array",
                            "minItems": 5,
                            "maxItems": 10,
                            "items": {
                                "type": "object",
                                "required": ["text", "source", "url"],
                                "properties": {
                                    "text": {"type": "string"},
                                    "source": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "reporting_angles": {
                            "type": "array",
                            "minItems": 3,
                            "maxItems": 5,
                            "items": {
                                "type": "object",
                                "required": ["angle", "outlet", "summary", "url"],
                                "properties": {
                                    "angle": {"type": "string"},
                                    "outlet": {"type": "string"},
                                    "summary": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "perspectives": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 5,
                            "items": {
                                "type": "object",
                                "required": [
                                    "stakeholder", "stance",
                                    "quote_or_paraphrase", "source", "url",
                                ],
                                "properties": {
                                    "stakeholder": {"type": "string"},
                                    "stance": {"type": "string"},
                                    "quote_or_paraphrase": {"type": "string"},
                                    "source": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                            },
                        },
                        "visual_aid": {
                            "type": "object",
                            "required": ["type", "title", "html"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["timeline", "table", "comparison", "mindmap"],
                                },
                                "title": {"type": "string"},
                                "html": {"type": "string"},
                            },
                        },
                    },
                },
            }
        },
    },
}


def _client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Run setup.sh or export it before running."
        )
    return anthropic.Anthropic(api_key=key, max_retries=5)


def _debug_dir() -> Path:
    p = Path(__file__).resolve().parent / "logs"
    p.mkdir(exist_ok=True)
    return p


def fetch_daily_news(
    model: str = "claude-sonnet-4-6",
    max_searches: int = 8,
) -> list[dict[str, Any]]:
    """Run Claude with web_search + a strict-schema submission tool.

    Robust against transient 429 rate-limit errors via aggressive retry/backoff.
    """
    client = _client()
    aest = pytz.timezone("Australia/Brisbane")
    now = datetime.now(aest)
    date_str = now.strftime("%A, %d %B %Y")

    # Progressive backoff: total max wait ~17 minutes across 7 attempts.
    # Long enough that even a sustained 429 burst clears before we give up.
    backoff_schedule = [60, 90, 120, 180, 240, 300]
    last_err = None
    message = None
    for attempt in range(len(backoff_schedule) + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=12000,
                system=SYSTEM_PROMPT,
                tools=[
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": max_searches,
                    },
                    SUBMIT_TOOL,
                ],
                tool_choice={"type": "auto"},
                messages=[{
                    "role": "user",
                    "content": USER_PROMPT_TEMPLATE.format(date_str=date_str),
                }],
            )
            break
        except anthropic.RateLimitError as e:
            last_err = e
            if attempt >= len(backoff_schedule):
                raise
            wait = backoff_schedule[attempt]
            print(
                f"[news] rate-limited (429); sleeping {wait}s before retry "
                f"{attempt + 2}/{len(backoff_schedule) + 1}…",
                flush=True,
            )
            time.sleep(wait)
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            last_err = e
            if attempt >= len(backoff_schedule):
                raise
            wait = min(60, backoff_schedule[attempt])
            print(f"[news] transient API error: {type(e).__name__}; sleeping {wait}s…", flush=True)
            time.sleep(wait)
    if message is None:
        raise last_err or RuntimeError("Failed to obtain Claude response")

    # Persist the raw response for forensics on failure.
    debug_path = _debug_dir() / f"news-raw-{now.strftime('%Y-%m-%d')}.json"
    debug_path.write_text(message.model_dump_json(indent=2))

    submission = None
    text_fallback_parts = []
    for block in message.content:
        btype = getattr(block, "type", None)
        if btype == "tool_use" and getattr(block, "name", "") == "submit_daily_brief":
            submission = block.input
        elif btype == "text":
            text_fallback_parts.append(block.text)

    if submission is None:
        raise RuntimeError(
            "Model did not call submit_daily_brief. "
            f"stop_reason={message.stop_reason!r}. "
            f"Text content was:\n{''.join(text_fallback_parts)[:1000]}\n"
            f"Full raw response saved to {debug_path}"
        )

    items = submission.get("items", [])
    # Defensive: model sometimes serialises the array as a JSON string.
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except Exception:
            pass
    if not isinstance(items, list) or len(items) != 3:
        raise ValueError(f"Expected 3 items in submission, got: {items!r}")

    by_cat = {it.get("category"): it for it in items}
    ordered = []
    for cat in CATEGORIES:
        if cat not in by_cat:
            raise ValueError(f"Missing category {cat} in model output")
        ordered.append(_normalise(by_cat[cat]))

    return {
        "items": ordered,
        "quote_of_day": submission.get("quote_of_day") or {},
        "market_numbers": submission.get("market_numbers") or [],
    }


def _normalise(item: dict[str, Any]) -> dict[str, Any]:
    """Fill in any missing optional fields with safe defaults."""
    item.setdefault("image_url", "")
    item.setdefault("video_channel", "")
    item.setdefault("summary_bullets", [])
    item.setdefault("reporting_angles", [])
    item.setdefault("perspectives", [])
    item.setdefault("visual_aid", {"type": "table", "title": "", "html": ""})
    item.setdefault("lead_source", {"name": "", "url": ""})
    # Only keep video URLs that are confirmed specific YouTube watch links.
    video = item.get("video_url") or ""
    item["video_url"] = video if "watch?v=" in video else ""
    return item


# ---------------------------------------------------------------------------
# Top-5 US intraday stock picks
# ---------------------------------------------------------------------------

STOCK_SYSTEM_PROMPT = """You are an aggressive US equity momentum analyst hunting for
explosive intraday movers on NYSE and NASDAQ. Your sole task is to find the 5 US stocks
with the HIGHEST potential intraday gain during TODAY's regular session (9:30 am – 4:00 pm EDT).

Target profile — ONLY include stocks that fit at least one of these high-upside setups:
  A. FDA BINARY EVENT  : PDUFA dates, CRL decisions, fast-track/breakthrough designations.
     Biotech with binary catalyst can move +30% to +200% intraday on approval.
  B. EARNINGS SURPRISE : Small/mid-cap beating EPS by >15% or revenue by >10%. Post-earnings
     gap-and-run from a compressed base can add +30–80% on the day.
  C. SHORT SQUEEZE     : Stock with >20% short float + fresh positive catalyst + rising volume.
     Forced short covering drives exponential intraday spikes.
  D. PRE-MARKET GAPPER : Already up >15% pre-market on news. Stocks that gap >15% often
     continue intraday — confirm the catalyst is real and strong enough to sustain.
  E. M&A / TAKEOVER    : Acquisition announcement at a significant premium. Target stock
     price converges to offer price intraday — 20–50%+ gain is common.
  F. MAJOR ANALYST UPGRADE: Strong buy initiation or target-price doubling by a tier-1 firm
     on a heavily covered stock with technical momentum aligned.

Research methodology — follow every step:
1. FDA CALENDAR    : Search "FDA PDUFA dates" and "FDA drug decisions today".
2. PRE-MARKET      : Search "pre-market top gainers today" and investigate the specific
                     catalyst behind each gapper (confirm quality and sustainability).
3. EARNINGS        : Search "earnings surprise today small cap beat" and
                     "after hours earnings beats".
4. SHORT SQUEEZE   : Search "most shorted stocks today" and "short squeeze candidates".
5. UNUSUAL OPTIONS : Search "unusual options activity today" and
                     "0DTE call sweep today" — massive call sweeps = institutional conviction.
6. M&A / UPGRADES  : Search "acquisition announcement today" and
                     "analyst upgrade initiation today".

Selection rules (non-negotiable):
* US-listed NYSE or NASDAQ stocks ONLY. No OTC, no crypto, no ETFs.
* Minimum expected intraday gain: +30%. Ideal target range: +30% to +80%.
* The gain must materialise WITHIN today's single session — NOT over days/weeks.
* Rank the 5 picks by probability-weighted expected intraday gain (highest conviction #1).
* Every pick MUST have a concrete, verifiable catalyst found via web_search.
* REJECT large-cap blue chips (AAPL, MSFT, NVDA, etc.) — they rarely move >5% intraday.
  Focus on small-cap ($50M–$2B market cap) and mid-cap stocks with binary catalysts.
* This output is for informational/educational purposes ONLY. It is NOT investment advice."""

STOCK_USER_PROMPT_TEMPLATE = """Today is {date_str} (Brisbane/AEST).
The US regular trading session is {us_date_str}: 9:30 am – 4:00 pm EDT
(= {aest_open_str} – {aest_close_str} AEST on {aest_dates_str}).

Your goal: find 5 stocks that could gain +30% to +80%+ WITHIN this single session.
Focus ONLY on small/mid-caps with binary catalysts — not large-cap blue chips.

Execute this research checklist:
1. Search "FDA PDUFA dates {us_date_str}" and "FDA drug approval decision today {us_date_str}".
2. Search "pre-market top gainers today {us_date_str}" — check stocks already up >15% pre-market.
3. Search "earnings surprise {us_date_str} small cap beat" and "after hours earnings tonight".
4. Search "short squeeze stocks {us_date_str}" and "most shorted NYSE NASDAQ stocks".
5. Search "unusual options activity {us_date_str}" and "call sweep unusual options today".
6. Search "acquisition merger announcement today {us_date_str}".
7. For each shortlisted candidate: search "[TICKER] news {us_date_str}" to confirm catalyst.
8. Shortlist at least 8–10 candidates, then select the top 5 by expected intraday gain %.

For every final pick, confirm:
  • Ticker and exact company name
  • Specific catalyst (FDA, earnings beat, short squeeze, M&A, gapper, analyst upgrade)
  • Last close price or pre-market price
  • Expected intraday gain range (MUST be ≥ +30%)
  • Setup type: one of FDA Decision, Earnings Surprise, Short Squeeze, Pre-Market Gapper,
    M&A Announcement, Analyst Upgrade, Technical Breakout
  • 2–3 supporting technical indicators (RSI, volume vs avg, MA position, short float %)
  • Risk level: High for binary events (FDA), Medium for earnings/squeeze plays"""

TOP_STOCKS_TOOL = {
    "name": "submit_top_stocks",
    "description": (
        "Submit the final ranked list of the top 5 US intraday stock picks. "
        "Call this exactly once after all research is complete."
    ),
    "input_schema": {
        "type": "object",
        "required": ["session_date_us", "session_aest", "stocks"],
        "properties": {
            "session_date_us": {
                "type": "string",
                "description": "US session date string e.g. 'Monday, 4 May 2026'",
            },
            "session_aest": {
                "type": "string",
                "description": "AEST session window e.g. '11:30 pm Mon 4 May – 6:00 am Tue 5 May'",
            },
            "stocks": {
                "type": "array",
                "minItems": 5,
                "maxItems": 5,
                "description": "Top 5 picks, ranked #1 (highest conviction) to #5.",
                "items": {
                    "type": "object",
                    "required": [
                        "rank", "ticker", "company", "sector",
                        "last_price", "setup_type", "expected_gain_pct",
                        "catalyst", "technical_summary",
                        "risk_level", "confidence_level",
                    ],
                    "properties": {
                        "rank": {
                            "type": "integer", "minimum": 1, "maximum": 5,
                            "description": "1 = highest conviction",
                        },
                        "ticker": {"type": "string", "description": "e.g. NVDA"},
                        "company": {"type": "string", "description": "Full company name"},
                        "sector": {"type": "string", "description": "e.g. Technology, Healthcare"},
                        "last_price": {
                            "type": "string",
                            "description": "Last close or pre-market price e.g. $875.50",
                        },
                        "setup_type": {
                            "type": "string",
                            "enum": [
                                "FDA Decision",
                                "Earnings Surprise",
                                "Short Squeeze",
                                "Pre-Market Gapper",
                                "M&A Announcement",
                                "Analyst Upgrade",
                                "Technical Breakout",
                            ],
                            "description": "Primary setup type driving the explosive intraday move",
                        },
                        "expected_gain_pct": {
                            "type": "string",
                            "description": "Expected intraday gain range — MUST be ≥ +30%, e.g. +35–55% or +40–80%",
                        },
                        "catalyst": {
                            "type": "string",
                            "description": "Specific catalyst driving today's explosive move (40-80 words)",
                        },
                        "technical_summary": {
                            "type": "string",
                            "description": "2-3 key signals e.g. RSI 72, short float 38%, volume 420% avg, above 50-day MA",
                        },
                        "risk_level": {
                            "type": "string",
                            "enum": ["Low", "Medium", "High"],
                        },
                        "confidence_level": {
                            "type": "string",
                            "enum": ["Moderate", "High", "Very High"],
                        },
                    },
                },
            },
        },
    },
}


def _next_us_trading_date(now_aest: datetime, aest_tz, edt_tz) -> "date":
    """Return the correct US trading date to use for stock picks.

    Rules (all times AEST, weekday 0=Mon … 6=Sun):
    • Friday / Saturday / Sunday AEST  → picks for the upcoming MONDAY EDT session
    • Monday – Thursday AEST           → picks for the NEXT EDT day's session
      (At 9 am AEST the current EDT clock reads ~7 pm the day before, so the
       same-EDT-day session has already closed — always advance by 1 EDT day.)
    Weekends in the resulting EDT date are skipped forward to Monday.
    """
    from datetime import timedelta, time as _time
    aest_weekday = now_aest.weekday()          # 0=Mon … 6=Sun
    edt_date     = now_aest.astimezone(edt_tz).date()

    if aest_weekday in (4, 5, 6):              # Fri / Sat / Sun AEST → Monday EDT
        days_to_monday = (7 - edt_date.weekday()) % 7
        if days_to_monday == 0:
            days_to_monday = 7
        target = edt_date + timedelta(days=days_to_monday)
    else:                                       # Mon–Thu AEST → next EDT calendar day
        target = edt_date + timedelta(days=1)
        while target.weekday() in (5, 6):      # skip EDT weekend (safety)
            target += timedelta(days=1)

    return target


def fetch_top_stocks(
    model: str = "claude-sonnet-4-6",
    max_searches: int = 18,
) -> dict[str, Any]:
    """Identify the top 5 US intraday stock picks for the next US trading session.

    Session mapping (AEST brief day → target EDT session):
      Mon–Thu AEST  →  same-name EDT day (next EDT day after 9 am AEST)
      Fri/Sat/Sun AEST  →  upcoming Monday EDT session

    Returns a dict with keys: stocks (list), session_date_us, session_aest.
    Raises on unrecoverable failure so the caller can fall back gracefully.
    """
    from datetime import timedelta, time as _time
    client   = _client()
    aest     = pytz.timezone("Australia/Brisbane")
    edt      = pytz.timezone("America/New_York")
    now_aest = datetime.now(aest)

    # ── Determine target US trading date ──────────────────────────────────────
    target_us_date = _next_us_trading_date(now_aest, aest, edt)

    us_open  = edt.localize(datetime.combine(target_us_date, _time(9, 30)))
    us_close = edt.localize(datetime.combine(target_us_date, _time(16, 0)))
    aest_open  = us_open.astimezone(aest)
    aest_close = us_close.astimezone(aest)

    # ── Build human-readable strings ─────────────────────────────────────────
    date_str       = now_aest.strftime("%A, %d %B %Y")          # brief publication date
    us_date_str    = us_open.strftime("%A, %d %B %Y")           # target trading date (EDT)
    aest_open_str  = aest_open.strftime("%-I:%M %p")
    aest_close_str = aest_close.strftime("%-I:%M %p")
    if aest_open.date() == aest_close.date():
        aest_dates_str = aest_open.strftime("%a %-d %b")
    else:
        aest_dates_str = (
            f"{aest_open.strftime('%a %-d %b')} – {aest_close.strftime('%a %-d %b')}"
        )

    # Extra context for weekend / Friday briefs so Claude searches correctly
    is_weekend_brief = now_aest.weekday() in (4, 5, 6)
    if is_weekend_brief:
        weekend_note = (
            f"\nNOTE: This brief is published on {now_aest.strftime('%A')} AEST. "
            f"The US market is CLOSED until Monday. Research catalysts that will "
            f"drive Monday's opening — weekend news, pre-market futures, upcoming "
            f"earnings on Monday, analyst notes released over the weekend."
        )
    else:
        weekend_note = ""

    prompt = STOCK_USER_PROMPT_TEMPLATE.format(
        date_str=date_str,
        us_date_str=us_date_str,
        aest_open_str=aest_open_str,
        aest_close_str=aest_close_str,
        aest_dates_str=aest_dates_str,
    ) + weekend_note

    backoff_schedule = [60, 90, 120, 180, 240, 300]
    last_err: Exception | None = None
    message = None
    for attempt in range(len(backoff_schedule) + 1):
        try:
            message = client.messages.create(
                model=model,
                max_tokens=10000,
                system=STOCK_SYSTEM_PROMPT,
                tools=[
                    {
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": max_searches,
                    },
                    TOP_STOCKS_TOOL,
                ],
                tool_choice={"type": "auto"},
                messages=[{"role": "user", "content": prompt}],
            )
            break
        except anthropic.RateLimitError as e:
            last_err = e
            if attempt >= len(backoff_schedule):
                raise
            wait = backoff_schedule[attempt]
            print(f"[stocks] rate-limited; sleeping {wait}s…", flush=True)
            time.sleep(wait)
        except (anthropic.APIConnectionError, anthropic.APIStatusError) as e:
            last_err = e
            if attempt >= len(backoff_schedule):
                raise
            wait = min(60, backoff_schedule[attempt])
            print(f"[stocks] API error {type(e).__name__}; sleeping {wait}s…", flush=True)
            time.sleep(wait)

    if message is None:
        raise last_err or RuntimeError("fetch_top_stocks: no response from Claude")

    submission = None
    for block in message.content:
        if (
            getattr(block, "type", None) == "tool_use"
            and getattr(block, "name", "") == "submit_top_stocks"
        ):
            submission = block.input
            break

    if submission is None:
        raise RuntimeError("fetch_top_stocks: model did not call submit_top_stocks")

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


if __name__ == "__main__":
    items = fetch_daily_news()
    json.dump(items, sys.stdout, indent=2, ensure_ascii=False)
    print()

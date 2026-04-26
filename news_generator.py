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
  * A topical news photograph URL from a real news outlet (NOT a wiki, NOT
    generic stock). If genuinely none, leave empty.
  * A direct video-report URL from a major news outlet's video channel
    (BBC/Reuters/Bloomberg/AP/CNN/Al Jazeera/SCMP/etc. on YouTube or their own
    site). If genuinely none, leave empty.
  * 6-8 attributed summary bullets (each cites an outlet + URL).
  * 4 different reporting angles, EACH from a different outlet.
  * 3-4 stakeholder perspectives with stance + paraphrase + outlet citation.
  * One genuinely useful visual aid as inline HTML (a timeline table, a
    stakeholder comparison table, a mindmap as a nested list, a numbers
    table, etc.). Use only inline styles, no <script>, no external CSS,
    no <link> tags. Keep it under ~1500 characters.

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
        "required": ["items"],
        "properties": {
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
    return anthropic.Anthropic(api_key=key)


def _debug_dir() -> Path:
    p = Path(__file__).resolve().parent / "logs"
    p.mkdir(exist_ok=True)
    return p


def fetch_daily_news(
    model: str = "claude-sonnet-4-6",
    max_searches: int = 20,
) -> list[dict[str, Any]]:
    """Run Claude with web_search + a strict-schema submission tool."""
    client = _client()
    aest = pytz.timezone("Australia/Brisbane")
    now = datetime.now(aest)
    date_str = now.strftime("%A, %d %B %Y")

    message = client.messages.create(
        model=model,
        max_tokens=16000,
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
    if not isinstance(items, list) or len(items) != 3:
        raise ValueError(f"Expected 3 items in submission, got: {items!r}")

    by_cat = {it.get("category"): it for it in items}
    ordered = []
    for cat in CATEGORIES:
        if cat not in by_cat:
            raise ValueError(f"Missing category {cat} in model output")
        ordered.append(_normalise(by_cat[cat]))
    return ordered


def _normalise(item: dict[str, Any]) -> dict[str, Any]:
    """Fill in any missing optional fields with safe defaults."""
    item.setdefault("image_url", "")
    item.setdefault("video_url", "")
    item.setdefault("summary_bullets", [])
    item.setdefault("reporting_angles", [])
    item.setdefault("perspectives", [])
    item.setdefault("visual_aid", {"type": "table", "title": "", "html": ""})
    item.setdefault("lead_source", {"name": "", "url": ""})
    return item


if __name__ == "__main__":
    items = fetch_daily_news()
    json.dump(items, sys.stdout, indent=2, ensure_ascii=False)
    print()

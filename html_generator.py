"""HTML renderer for the Daily News Brief.

Consumes the structured news-item dicts produced by news_generator.fetch_daily_news
and the weather dict from weather_fetcher.WeatherFetcher.get_brisbane_weather.

Color palette: dark navy (#0b1d3a), gold (#c9a24a), black (#0a0a0a) on the
header/footer; main body is white. Designed to render well both as a standalone
HTML file and (best-effort) as inline email body.
"""
from __future__ import annotations

import html as html_lib
from datetime import datetime
from typing import Any

import pytz

NAVY = "#0b1d3a"
GOLD = "#c9a24a"
GOLD_SOFT = "#e6cf8a"
BLACK = "#0a0a0a"
INK = "#1c1c1c"
PAPER = "#ffffff"
MUTED = "#5b6577"
RULE = "#e8e2d0"

CATEGORY_ORDER = ["Global", "Business & Markets", "Hong Kong"]
CATEGORY_TAB_IDS = {
    "Global": "global",
    "Business & Markets": "business",
    "Hong Kong": "hongkong",
}

MOTTOS = [
    "Read widely, think clearly, act decisively.",
    "An informed mind is the first asset of a free life.",
    "Knowledge compounds when read with attention.",
    "What you understand today shapes what you choose tomorrow.",
    "Curiosity is the quiet engine of growth.",
    "Read for facts, weigh for fairness, decide with care.",
    "The world rewards those who read between the lines.",
    "Stay informed, stay curious, stay deliberate.",
    "Today's headlines are tomorrow's history -- read them well.",
    "Sharpen the mind each morning; the day will follow.",
]


_MKT_CHANGE_RE = __import__('re').compile(r'[+\-]?\d+\.?\d*%')


def _esc(s: Any) -> str:
    return html_lib.escape("" if s is None else str(s))


def _clean_mkt_value(s: str) -> str:
    s = (s or "").strip()
    return s.split()[0] if any(c.isalpha() for c in s) else s


def _clean_mkt_change(s: str) -> str:
    s = (s or "").strip()
    m = _MKT_CHANGE_RE.search(s)
    return m.group(0) if m else (s.split()[0] if s else s)


def _motto_for(date: datetime) -> str:
    return MOTTOS[date.timetuple().tm_yday % len(MOTTOS)]


def _short_title(s: str, n: int = 110) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "..."


def _render_summary(bullets: list[dict[str, Any]]) -> str:
    if not bullets:
        return "<li><em>No summary points returned.</em></li>"
    items = []
    for b in bullets:
        text = _esc(b.get("text", ""))
        outlet = _esc(b.get("source", ""))
        url = b.get("url", "") or ""
        cite = (
            f' <span style="color:{MUTED};font-size:13px;">'
            f'-- <a href="{_esc(url)}" style="color:{NAVY};text-decoration:none;border-bottom:1px dotted {NAVY};">{outlet}</a></span>'
            if outlet and url
            else f' <span style="color:{MUTED};font-size:13px;">-- {outlet}</span>' if outlet else ""
        )
        items.append(f"<li style=\"margin:0 0 10px 0;\">{text}{cite}</li>")
    return "\n".join(items)


def _render_angles(angles: list[dict[str, Any]]) -> str:
    if not angles:
        return '<p style="color:{MUTED};font-style:italic;margin:0;">No angles returned.</p>'
    th_style = (
        f'text-align:left;padding:8px 12px;font-size:11px;letter-spacing:2px;'
        f'text-transform:uppercase;color:{GOLD};font-weight:bold;'
        f'border-bottom:2px solid rgba(201,162,74,0.4);'
    )
    rows = [
        f'<colgroup>'
        f'<col style="width:22%;">'
        f'<col style="width:14%;">'
        f'<col style="width:64%;">'
        f'</colgroup>'
        f'<thead><tr>'
        f'<th style="{th_style}">Angle</th>'
        f'<th style="{th_style}">Outlet</th>'
        f'<th style="{th_style}">Perspective</th>'
        f'</tr></thead>'
    ]
    td_base = (
        f'padding:10px 12px;font-size:13.5px;line-height:1.55;'
        f'border-bottom:1px solid rgba(201,162,74,0.12);vertical-align:top;'
    )
    for i, a in enumerate(angles):
        label   = _esc(a.get("angle", ""))
        outlet  = _esc(a.get("outlet", ""))
        summary = _esc(a.get("summary", ""))
        url     = a.get("url", "") or ""
        outlet_cell = (
            f'<a href="{_esc(url)}" target="_blank" rel="noopener" '
            f'style="color:{NAVY};text-decoration:none;border-bottom:1px dotted {NAVY};">{outlet}</a>'
            if outlet and url else outlet
        )
        bg = "rgba(201,162,74,0.05)" if i % 2 == 1 else "transparent"
        rows.append(
            f'<tr style="background:{bg};">'
            f'<td style="{td_base}color:{NAVY};font-weight:bold;">{label}</td>'
            f'<td style="{td_base}color:{MUTED};font-size:13px;">{outlet_cell}</td>'
            f'<td style="{td_base}color:{INK};">{summary}</td>'
            f'</tr>'
        )
    return (
        f'<table style="width:100%;border-collapse:collapse;font-family:Georgia,serif;table-layout:fixed;">'
        + "".join(rows)
        + '</table>'
    )


def _render_perspectives(persp: list[dict[str, Any]]) -> str:
    if not persp:
        return '<p style="color:#5b6577;font-style:italic;margin:0;">No perspectives returned.</p>'
    th_style = (
        f'text-align:left;padding:8px 12px;font-size:11px;letter-spacing:2px;'
        f'text-transform:uppercase;color:{GOLD};font-weight:bold;'
        f'border-bottom:2px solid rgba(201,162,74,0.4);'
    )
    rows = [
        f'<colgroup><col style="width:20%;"><col style="width:18%;"><col style="width:62%;"></colgroup>'
        f'<thead><tr>'
        f'<th style="{th_style}">Who</th>'
        f'<th style="{th_style}">Stance</th>'
        f'<th style="{th_style}">What They Said</th>'
        f'</tr></thead>'
    ]
    td_base = (
        f'padding:10px 12px;font-size:13.5px;line-height:1.55;'
        f'border-bottom:1px solid rgba(201,162,74,0.12);vertical-align:top;'
    )
    for i, p in enumerate(persp):
        who    = _esc(p.get("stakeholder", ""))
        stance = _esc(p.get("stance", ""))
        quote  = _esc(p.get("quote_or_paraphrase", ""))
        outlet = _esc(p.get("source", ""))
        url    = p.get("url", "") or ""
        cite = (
            f' <a href="{_esc(url)}" target="_blank" rel="noopener" '
            f'style="color:{NAVY};text-decoration:none;border-bottom:1px dotted {NAVY};font-size:12px;font-style:normal;">{outlet}</a>'
            if outlet and url else (f' <span style="color:{MUTED};font-size:12px;font-style:normal;">{outlet}</span>' if outlet else "")
        )
        bg = "rgba(201,162,74,0.05)" if i % 2 == 1 else "transparent"
        rows.append(
            f'<tr style="background:{bg};">'
            f'<td style="{td_base}color:{NAVY};font-weight:bold;">{who}</td>'
            f'<td style="{td_base}">'
            f'<span style="font-size:12px;font-style:italic;font-weight:600;'
            f'color:{GOLD};letter-spacing:0.3px;font-family:Georgia,serif;">'
            f'{stance[:40] + ("…" if len(stance) > 40 else "")}</span></td>'
            f'<td style="{td_base}color:{INK};font-style:italic;">&ldquo;{quote}&rdquo;{cite}</td>'
            f'</tr>'
        )
    return (
        f'<table style="width:100%;border-collapse:collapse;font-family:Georgia,serif;table-layout:fixed;">'
        + "".join(rows)
        + '</table>'
    )


def _render_visual_aid(va: dict[str, Any]) -> str:
    if not va:
        return ""
    title = _esc(va.get("title", "Visual Analysis"))
    inner = va.get("html", "") or ""
    # Strip anything that could escape the sandbox: scripts, iframes, style tags, event attrs.
    for tag in ("<script", "</script", "<iframe", "</iframe", "<style", "</style", "<link"):
        inner = inner.replace(tag, f"&lt;{tag[1:]}")
    import re as _re
    inner = _re.sub(r'\bon\w+\s*=', '', inner, flags=_re.IGNORECASE)
    return (
        f'<div class="card-visual" style="background:#fbf7ec;border:1px solid {RULE};border-left:4px solid {GOLD};'
        f'padding:18px 20px;border-radius:6px;margin:18px 0;overflow:hidden;">'
        f'<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:10px;">'
        f"Visual Analysis -- {title}</div>"
        f'<div style="color:{INK};font-size:14px;line-height:1.55;overflow:hidden;">{inner}</div>'
        f"</div>"
    )


_CATEGORY_GRADIENTS = {
    "Global":             "linear-gradient(135deg,#0b1d3a 0%,#162d55 50%,#0b1d3a 100%)",
    "Business & Markets": "linear-gradient(135deg,#1a1000 0%,#3a2400 50%,#1a1000 100%)",
    "Hong Kong":          "linear-gradient(135deg,#001a1a 0%,#003535 50%,#001a1a 100%)",
}

_CATEGORY_ACCENT = {
    "Global":             "#1e6fa0",
    "Business & Markets": "#c9a24a",
    "Hong Kong":          "#1a8060",
}


def _read_time(item: dict[str, Any]) -> str:
    words = len((item.get("title") or "").split())
    for b in item.get("summary_bullets") or []:
        words += len((b.get("text") or "").split())
    for a in item.get("reporting_angles") or []:
        words += len((a.get("summary") or "").split())
    for p in item.get("perspectives") or []:
        words += len((p.get("quote_or_paraphrase") or "").split())
    return f"~{max(1, round(words / 200))} min read"


def _render_news_item(item: dict[str, Any], category: str = "") -> str:
    title = _esc(item.get("title", "Untitled"))
    img_url = item.get("image_url") or ""
    video = item.get("video_url") or ""
    lead = item.get("lead_source") or {}
    lead_name = _esc(lead.get("name", ""))
    lead_url = lead.get("url", "") or ""
    gradient = _CATEGORY_GRADIENTS.get(category, _CATEGORY_GRADIENTS["Global"])

    img_block = ""
    if img_url:
        fallback_style = (
            f"display:none;width:100%;min-height:160px;margin:6px 0 12px;"
            f"background:{gradient};border-radius:6px;border:1px solid {RULE};"
            f"display:none;align-items:center;justify-content:center;flex-direction:column;"
            f"box-sizing:border-box;padding:24px;"
        )
        img_block = (
            f'<img id="img-{abs(hash(img_url))}" src="{_esc(img_url)}" alt="{title}" '
            f'referrerpolicy="no-referrer" crossorigin="anonymous" '
            f'style="display:block;width:100%;max-height:520px;object-fit:cover;'
            f'border-radius:6px;margin:6px 0 12px;border:1px solid {RULE};" '
            f'onerror="this.style.display=\'none\';var fb=this.nextElementSibling;fb.style.display=\'flex\';">'
            f'<div class="img-fallback" style="{fallback_style}">'
            f'<div style="font-size:28px;margin-bottom:10px;opacity:0.5;">&#128247;</div>'
            f'<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.5);margin-bottom:8px;">Image Unavailable</div>'
            + (f'<a href="{_esc(lead_url)}" target="_blank" rel="noopener" '
               f'style="font-size:12px;color:{GOLD};text-decoration:none;border-bottom:1px solid rgba(201,162,74,0.4);">View story at {lead_name} &rarr;</a>'
               if lead_url else "")
            + f'</div>'
        )

    video_block = ""
    if video:
        channel = (item.get("video_channel") or "").strip()
        outlet = _esc(channel if channel else _outlet_from_url(video))
        video_block = (
            f'<a href="{_esc(video)}" target="_blank" rel="noopener" '
            f'style="display:inline-flex;align-items:center;gap:8px;'
            f'background:{NAVY};color:{GOLD_SOFT};'
            f'padding:10px 20px;border-radius:4px;text-decoration:none;font-size:13px;'
            f'letter-spacing:1px;text-transform:uppercase;font-weight:bold;margin:4px 0 22px;">'
            f'<span style="font-size:16px;line-height:1;">&#9654;</span>'
            f'Watch Video Report &mdash; {outlet}</a>'
        )

    lead_block = ""
    if lead_name:
        if lead_url:
            lead_block = (
                f'<div class="lead-source" style="font-size:13px;color:{MUTED};margin-bottom:14px;">Lead source: '
                f'<a href="{_esc(lead_url)}" style="color:{NAVY};text-decoration:none;border-bottom:1px dotted {NAVY};">{lead_name}</a></div>'
            )
        else:
            lead_block = f'<div class="lead-source" style="font-size:13px;color:{MUTED};margin-bottom:14px;">Lead source: {lead_name}</div>'

    return f"""
    <article class="news-article" style="margin:0 0 32px 0;padding:0 0 32px 0;border-bottom:1px solid {RULE};">
      <h2 style="font-family:'Georgia','Times New Roman',serif;font-size:30px;line-height:1.25;color:{NAVY};margin:0 0 10px 0;">{title}</h2>
      {lead_block}
      {img_block}
      {video_block}
      {_render_visual_aid(item.get("visual_aid") or {})}
      <div class="card-summary" style="background:#f6f8fc;border:1px solid {RULE};border-radius:6px;padding:18px 20px;margin:18px 0;">
        <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:10px;">News Summary</div>
        <ul style="margin:0;padding-left:20px;color:{INK};font-size:14.5px;line-height:1.6;">
          {_render_summary(item.get("summary_bullets") or [])}
        </ul>
      </div>
      <div class="card-angles" style="background:#fff8eb;border:1px solid {RULE};border-radius:6px;padding:18px 20px;margin:18px 0;overflow-x:auto;">
        <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:12px;">Different Reporting Angles</div>
        {_render_angles(item.get("reporting_angles") or [])}
      </div>
      <div class="card-persp" style="background:#f3f8f1;border:1px solid {RULE};border-radius:6px;padding:18px 20px;margin:18px 0;overflow-x:auto;">
        <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:12px;">Diverse Stakeholder Perspectives</div>
        {_render_perspectives(item.get("perspectives") or [])}
      </div>
    </article>
    """


def _outlet_from_url(url: str) -> str:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        host = host.replace("www.", "")
        return host.split("/")[0]
    except Exception:
        return "source"


_SETUP_TYPE_COLORS = {
    "FDA Decision":       ("#a78bfa", "rgba(167,139,250,0.12)"),  # violet
    "Earnings Surprise":  ("#38bdf8", "rgba(56,189,248,0.12)"),   # sky blue
    "Short Squeeze":      ("#fb923c", "rgba(251,146,60,0.12)"),   # orange
    "Pre-Market Gapper":  ("#f472b6", "rgba(244,114,182,0.12)"),  # pink
    "M&A Announcement":   ("#34d399", "rgba(52,211,153,0.12)"),   # emerald
    "Analyst Upgrade":    ("#c9a24a", "rgba(201,162,74,0.12)"),   # gold
    "Technical Breakout": ("#67e8f9", "rgba(103,232,249,0.12)"),  # cyan
}


def _render_stock_card(stock: dict, idx: int) -> str:
    """Compact beginner-friendly card: why it moves + entry / SL / TP / R:R."""
    rank        = _esc(str(stock.get("rank", idx + 1)))
    ticker      = _esc(stock.get("ticker", "—"))
    company     = _esc(stock.get("company", ""))
    price       = _esc(stock.get("last_price", ""))
    gain        = _esc(stock.get("expected_gain_pct", ""))
    setup_type  = stock.get("setup_type", "")
    key_factors = _esc(stock.get("key_factors") or stock.get("catalyst", ""))
    entry_price = _esc(stock.get("entry_price", ""))
    stop_loss   = _esc(stock.get("stop_loss", ""))
    take_profit = _esc(stock.get("take_profit", ""))
    rr_ratio    = _esc(stock.get("risk_reward_ratio", ""))
    technical   = _esc(stock.get("technical_summary", ""))
    risk        = stock.get("risk_level", "High")
    conf        = stock.get("confidence_level", "High")

    risk_colors = {
        "Low":    ("rgba(74,222,128,0.10)", "#4ade80"),
        "Medium": ("rgba(251,191,36,0.10)", "#fbbf24"),
        "High":   ("rgba(248,113,113,0.10)", "#f87171"),
    }
    conf_colors = {
        "Moderate":  ("rgba(148,163,184,0.10)", "#94a3b8"),
        "High":      ("rgba(201,162,74,0.12)",  "#c9a24a"),
        "Very High": ("rgba(74,222,128,0.12)",  "#4ade80"),
    }
    r_bg, r_fg = risk_colors.get(risk, risk_colors["High"])
    c_bg, c_fg = conf_colors.get(conf, conf_colors["High"])
    s_fg, s_bg = _SETUP_TYPE_COLORS.get(setup_type, ("#c9a24a", "rgba(201,162,74,0.12)"))

    sep = "border-top:1px solid rgba(201,162,74,0.13);padding-top:9px;margin-top:1px;" if idx > 0 else ""

    # Setup badge — slim pill with coloured border only (no solid fill)
    setup_html = (
        f'<span style="font-size:9px;padding:1px 7px;border-radius:10px;'
        f'border:1px solid {s_fg};color:{s_fg};font-weight:700;letter-spacing:0.3px;'
        f'background:{s_bg};">{_esc(setup_type)}</span>'
    ) if setup_type else ""

    # Entry / SL / TP trade row
    trade_parts = []
    if entry_price: trade_parts.append(f'<b style="color:#9ca3af;">Entry</b> {entry_price}')
    if stop_loss:   trade_parts.append(f'<b style="color:#f87171;">SL</b> {stop_loss}')
    if take_profit: trade_parts.append(f'<b style="color:#4ade80;">TP</b> {take_profit}')
    trade_html = (
        f'<div style="font-size:10px;color:#b8b0a0;line-height:1.7;margin:3px 0;">'
        + ' &nbsp;·&nbsp; '.join(trade_parts)
        + '</div>'
    ) if trade_parts else ""

    # R:R badge
    rr_html = (
        f'<span style="font-size:9px;padding:1px 7px;border-radius:10px;'
        f'border:1px solid rgba(74,222,128,0.45);color:#4ade80;font-weight:700;">'
        f'R:R {rr_ratio}</span>&nbsp;'
    ) if rr_ratio else ""

    return "".join([
        f'<div style="{sep}margin-bottom:10px;">',
        # Rank · ticker · gain%
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:1px;">',
        f'<span><span style="font-size:10px;color:#6a7280;margin-right:3px;">#{rank}</span>'
        f'<span style="font-size:15px;font-weight:700;color:{GOLD};">{ticker}</span></span>',
        f'<span style="font-size:14px;font-weight:700;color:#4ade80;">{gain}</span>',
        f'</div>',
        # Company · price
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px;">',
        f'<span style="font-size:10px;color:#6a7280;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:72%;">{company}</span>',
        f'<span style="font-size:10px;color:#9ca3af;">{price}</span>',
        f'</div>',
        # Setup badge
        (f'<div style="margin-bottom:4px;">{setup_html}</div>' if setup_html else ""),
        # Why it moves (plain English for beginners)
        (f'<div style="font-size:11px;color:#ddd5bc;line-height:1.5;margin-bottom:3px;">{key_factors}</div>' if key_factors else ""),
        # Entry / SL / TP
        trade_html,
        # Technicals (very compact)
        (f'<div style="font-size:9px;color:#6a7280;line-height:1.4;margin-bottom:3px;">{technical}</div>' if technical else ""),
        # R:R + risk + confidence
        f'<div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-top:2px;">',
        rr_html,
        f'<span style="font-size:9px;padding:1px 7px;border-radius:10px;'
        f'border:1px solid {r_fg};color:{r_fg};font-weight:700;background:{r_bg};">{_esc(risk)} Risk</span>',
        f'<span style="font-size:9px;padding:1px 7px;border-radius:10px;'
        f'border:1px solid {c_fg};color:{c_fg};font-weight:700;background:{c_bg};">{_esc(conf)}</span>',
        f'</div>',
        f'</div>',
    ])


def _render_left_panel(top_stocks_data: dict | None, brief_meta: dict | None = None) -> str:
    """Left header panel: Market Snapshot + Quote of the Day."""
    _SEP = "border-top:1px solid rgba(201,162,74,0.22);padding-top:8px;margin-top:8px;"
    _meta = brief_meta or {}

    # ── Market Snapshot ──────────────────────────────────────────────────
    market_nums  = _meta.get("market_numbers") or []
    market_block = ""
    if market_nums:
        cells = []
        for mn in market_nums[:6]:
            label     = _esc(mn.get("label", ""))
            value     = _esc(_clean_mkt_value(mn.get("value", "")))
            change    = _esc(_clean_mkt_change(mn.get("change", "")))
            chg_color = "#4ade80" if "+" in change else "#f87171" if "-" in change else "#94a3b8"
            cells.append(
                f'<div style="padding:4px 0;border-bottom:1px solid rgba(201,162,74,0.07);">'
                f'<div style="font-size:9px;color:#6a7280;letter-spacing:0.3px;">{label}</div>'
                f'<div style="display:flex;align-items:baseline;gap:5px;">'
                f'<span style="font-size:12px;font-weight:600;color:#ddd5bc;">{value}</span>'
                f'<span style="font-size:10px;color:{chg_color};">{change}</span>'
                f'</div></div>'
            )
        market_block = (
            f'<div style="font-size:10px;letter-spacing:2.5px;color:{GOLD};font-weight:700;'
            f'text-transform:uppercase;margin-bottom:8px;">Market Snapshot</div>'
            f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:0 14px;">'
            + "".join(cells)
            + f'</div>'
        )
    else:
        market_block = (
            f'<div style="font-size:10px;letter-spacing:2.5px;color:{GOLD};font-weight:700;'
            f'text-transform:uppercase;margin-bottom:8px;">Market Snapshot</div>'
            f'<div style="color:#6a7280;font-size:11px;font-style:italic;">Market data unavailable.</div>'
        )

    # ── Quote of the Day ─────────────────────────────────────────────────
    qod         = _meta.get("quote_of_day") or {}
    quote_block = ""
    if qod and qod.get("quote"):
        quote   = _esc(qod.get("quote", ""))
        speaker = _esc(qod.get("speaker", ""))
        source  = _esc(qod.get("source", ""))
        attr    = f"— {speaker}" + (f", {source}" if source else "")
        quote_block = (
            f'<div style="{_SEP}">'
            f'<div style="font-size:10px;letter-spacing:2.5px;color:{GOLD};font-weight:700;'
            f'text-transform:uppercase;margin-bottom:5px;">Quote of the Day</div>'
            f'<div style="font-size:12px;color:#f1ecdf;line-height:1.55;font-style:italic;">&ldquo;{quote}&rdquo;</div>'
            + (f'<div style="margin-top:4px;font-size:10px;color:#6a7280;">{_esc(attr)}</div>' if speaker else "")
            + f'</div>'
        )

    return market_block + quote_block


def _render_stocks_banner(top_stocks_data: dict | None) -> str:
    """Full-width dark banner between the header and news tabs.

    Displays Top 4 High-Upside Picks in a 4-column horizontal grid.
    """
    if not top_stocks_data:
        return ""
    stocks       = top_stocks_data.get("stocks") or []
    session_aest = _esc(top_stocks_data.get("session_aest", ""))
    if not stocks:
        return ""

    # Limit to 4 picks
    stocks = stocks[:4]

    session_line = (
        f'<span style="font-size:9px;color:#6a7280;letter-spacing:0.8px;">'
        f'US session (AEST): {session_aest}</span>'
    ) if session_aest else ""

    cards_html = "".join(
        f'<div style="background:rgba(2,10,28,0.55);border:1px solid rgba(201,162,74,0.28);'
        f'border-radius:8px;padding:14px 16px;min-width:0;">'
        + _render_stock_card(s, i)
        + f'</div>'
        for i, s in enumerate(stocks)
    )

    return (
        f'<div style="background:linear-gradient(180deg,#0b1d3a 0%,#07131f 100%);">'
        f'<div style="max-width:1080px;margin:0 auto;padding:18px 36px 20px;">'
        # Section header row
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
        f'margin-bottom:12px;border-bottom:1px solid rgba(201,162,74,0.2);padding-bottom:8px;">'
        f'<div>'
        f'<span style="font-size:10px;letter-spacing:2.5px;color:{GOLD};font-weight:700;'
        f'text-transform:uppercase;">Top 4 High-Upside Picks &middot; US</span>'
        f'&nbsp;&nbsp;<span style="font-size:9px;color:#4ade80;letter-spacing:0.5px;">'
        f'Target: +30% to +80%+ intraday</span>'
        f'</div>'
        + session_line +
        f'</div>'
        # 4-column card grid
        f'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">'
        + cards_html +
        f'</div>'
        # Disclaimer
        f'<div style="margin-top:10px;font-size:8px;color:#3d4d5c;font-style:italic;">'
        f'&#9888; Informational only &middot; Not financial advice &middot; '
        f'High-upside plays carry extreme risk &middot; Do your own research</div>'
        f'</div>'
        f'</div>'
    )


def _render_right_panel(items: list[dict[str, Any]], brief_meta: dict) -> str:
    """Right header panel — Daily News Brief.

    Layout (top → bottom):
      • At a Glance story index      ← main content
      • Key Events to Watch          ← upcoming dates from today's stories (if present)
    """
    _SEP = "border-top:1px solid rgba(201,162,74,0.22);padding-top:8px;margin-top:8px;"

    # ── 1. Edition index ──────────────────────────────────────────────────────
    SECTION_NUMS = ["01", "02", "03"]
    index_rows = []
    for i, it in enumerate(items):
        num         = SECTION_NUMS[i] if i < len(SECTION_NUMS) else f"0{i+1}"
        cat         = _esc((it.get("category") or "").upper())
        lead        = it.get("lead_source") or {}
        source_name = _esc(lead.get("name", ""))
        title       = _esc(it.get("title", ""))
        read_time   = _read_time(it)
        border      = "border-bottom:1px solid rgba(201,162,74,0.13);" if i < len(items) - 1 else ""
        index_rows.append(
            f'<div style="display:flex;gap:11px;padding:9px 0;{border}">'
            f'<div style="font-family:Georgia,serif;font-size:20px;font-weight:bold;'
            f'color:rgba(201,162,74,0.28);line-height:1;flex-shrink:0;padding-top:3px;">{num}</div>'
            f'<div style="min-width:0;">'
            f'<div style="font-size:10px;letter-spacing:2px;color:{GOLD};text-transform:uppercase;margin-bottom:2px;">{cat}</div>'
            f'<div style="font-size:12.5px;color:#eae4d4;line-height:1.4;">{title}</div>'
            + (f'<div style="font-size:10px;color:#6a7280;margin-top:3px;">{source_name} &middot; {read_time}</div>'
               if source_name else f'<div style="font-size:10px;color:#6a7280;margin-top:3px;">{read_time}</div>')
            + f'</div></div>'
        )

    story_block = (
        f'<div>'
        f'<div style="font-size:10px;letter-spacing:2.5px;color:{GOLD};font-weight:700;'
        f'text-transform:uppercase;margin-bottom:4px;border-bottom:1px solid rgba(201,162,74,0.26);'
        f'padding-bottom:7px;">Daily News Brief</div>'
        + "\n".join(index_rows)
        + f'</div>'
    )

    # ── 2. Key Events to Watch ───────────────────────────────────────────────
    watch_items = brief_meta.get("key_events_to_watch") or []
    watch_block = ""
    if watch_items:
        # Use a CSS grid with a fixed date column (100px) so date and event
        # are always on the same row — date never wraps into the event column.
        rows = []
        for i, ev in enumerate(watch_items[:4]):
            date  = _esc(ev.get("date", ""))
            event = _esc(ev.get("event", ""))
            border = "border-bottom:1px solid rgba(201,162,74,0.10);" if i < len(watch_items[:4]) - 1 else ""
            rows.append(
                # Date cell
                f'<div style="padding:5px 8px 5px 0;{border}font-size:9.5px;font-weight:700;'
                f'color:{GOLD};white-space:nowrap;line-height:1.4;">{date}</div>'
                # Event cell
                f'<div style="padding:5px 0;{border}font-size:11px;color:#ddd5bc;line-height:1.4;">{event}</div>'
            )
        watch_block = (
            f'<div style="{_SEP}">'
            f'<div style="font-size:10px;letter-spacing:2.5px;color:{GOLD};font-weight:700;'
            f'text-transform:uppercase;margin-bottom:8px;">Key Events to Watch</div>'
            f'<div style="display:grid;grid-template-columns:100px 1fr;align-items:start;">'
            + "".join(rows)
            + f'</div>'
            + "".join(rows)
            + f'</div>'
        )

    return (
        f'<div>'
        + story_block
        + watch_block
        + f'</div>'
    )


def _render_preview(items: list[dict[str, Any]]) -> str:
    rows = []
    for it in items:
        cat = _esc(it.get("category", ""))
        title = _esc(it.get("title", ""))
        rows.append(
            f'<div style="margin:0 0 10px 0;padding:0 0 10px 0;border-bottom:1px solid rgba(201,162,74,0.22);">'
            f'<div style="font-size:10px;letter-spacing:2px;color:{GOLD};text-transform:uppercase;margin-bottom:3px;">{cat}</div>'
            f'<div style="font-size:13px;color:#f1ecdf;line-height:1.5;">{title}</div>'
            f"</div>"
        )
    if rows:
        rows[-1] = rows[-1].replace("border-bottom:1px solid rgba(201,162,74,0.22);", "")
    return "\n".join(rows)


def render_html(weather: dict[str, Any], items: list[dict[str, Any]], brief_meta: dict | None = None) -> str:
    aest = pytz.timezone("Australia/Brisbane")
    hkt = pytz.timezone("Asia/Hong_Kong")
    now_aest = datetime.now(aest)
    now_hkt = datetime.now(hkt)

    edition = f"{now_aest.year}.{now_aest.month}.{now_aest.day}"
    long_date = f"{now_aest.day} {now_aest.strftime('%B %Y, %A, %H:%M')}"
    compiled_aut = now_aest.strftime("%H:%M")
    compiled_hkt = now_hkt.strftime("%H:%M")
    _meta = brief_meta or {}
    motto = _meta.get("daily_note") or _motto_for(now_aest)

    items_by_cat = {it.get("category"): it for it in items}
    ordered = [items_by_cat.get(c, {"category": c, "title": "(no story)"}) for c in CATEGORY_ORDER]

    sections = []
    for i, it in enumerate(ordered):
        cat = it.get("category", "")
        tab_id = CATEGORY_TAB_IDS.get(cat, f"section-{i}")
        active = " active" if i == 0 else ""
        read_time = _read_time(it)
        accent_color = _CATEGORY_ACCENT.get(cat, GOLD)
        sections.append(
            f'<section id="{tab_id}" class="news-section{active}" data-category="{_esc(cat)}">'
            f'<div style="height:3px;background:{accent_color};border-radius:0 0 2px 2px;margin-bottom:20px;"></div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">'
            f'<div style="font-size:12px;letter-spacing:3px;text-transform:uppercase;color:{GOLD};font-weight:bold;">{_esc(cat)}</div>'
            f'<div style="font-size:11px;color:{MUTED};letter-spacing:1px;text-transform:uppercase;">{read_time}</div>'
            f'</div>'
            f"{_render_news_item(it, cat)}"
            f"</section>"
        )

    # One-line weather pill (all on one line)
    weather_pill = (
        f'Brisbane &nbsp;·&nbsp; '
        f'<span style="color:{GOLD_SOFT};font-weight:600;">{_esc(weather.get("temperature","-"))}°C</span>'
        f' &nbsp;·&nbsp; Humidity <span style="color:{GOLD_SOFT};font-weight:600;">{_esc(weather.get("humidity","-"))}%</span>'
        f' &nbsp;·&nbsp; Wind <span style="color:{GOLD_SOFT};font-weight:600;">{_esc(weather.get("wind_speed","-"))} km/h</span>'
        f' &nbsp;·&nbsp; UV <span style="color:{GOLD_SOFT};font-weight:600;">{_esc(weather.get("uv_index","-"))}</span>'
        f' &nbsp;·&nbsp; Rain <span style="color:{GOLD_SOFT};font-weight:600;">{_esc(weather.get("rain_probability","-"))}%</span>'
        f' &nbsp;·&nbsp; <span style="color:{GOLD_SOFT};font-weight:600;">{_esc(weather.get("condition","-"))}</span>'
    )

    left_panel    = _render_left_panel(_meta.get("top_stocks_data") or None, _meta)
    right_panel   = _render_right_panel(ordered, _meta)
    stocks_banner = _render_stocks_banner(_meta.get("top_stocks_data") or None)

    # Big date: "27 April 2026, Monday"
    big_date = f"{now_aest.day} {now_aest.strftime('%B %Y, %A')}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Daily News Brief -- Edition {edition}</title>
<style>
  body {{ margin:0; padding:0; background:#f3efe7; color:{INK};
         font-family: 'Georgia','Times New Roman',serif; }}
  .wrap {{ max-width: 1080px; margin: 0 auto; background:{PAPER}; }}
  .hdr  {{ background: linear-gradient(160deg, {BLACK} 0%, {NAVY} 55%, #0d2444 100%);
          color:#f1ecdf; padding: 28px 36px 36px; position:relative; overflow:hidden; }}
  .hdr-strip {{ display:flex; justify-content:space-between; align-items:center;
               margin-bottom:30px; gap:12px; flex-wrap:wrap; }}
  .pill {{ background:rgba(255,255,255,0.07); border:1px solid rgba(201,162,74,0.28);
          border-radius:30px; padding:7px 18px; font-size:12px; color:#ddd6c0;
          letter-spacing:0.3px; white-space:nowrap; }}
  .pill-edition {{ background:rgba(255,255,255,0.07); border:1px solid rgba(201,162,74,0.28);
                  border-radius:30px; padding:7px 20px; font-size:12px; color:{GOLD};
                  letter-spacing:2.5px; font-weight:bold; text-transform:uppercase;
                  white-space:nowrap; }}
  .watermark {{ position:absolute; top:68%; left:50%; transform:translate(-50%,-50%);
               font-family:'Georgia','Times New Roman',serif; font-size:170px;
               font-style:italic; font-weight:bold; white-space:nowrap;
               pointer-events:none; user-select:none; z-index:0; letter-spacing:-4px;
               background:linear-gradient(135deg,
                 rgba(201,162,74,0.22) 0%,
                 rgba(240,210,140,0.28) 35%,
                 rgba(210,170,100,0.18) 65%,
                 rgba(180,130,80,0.22) 100%);
               -webkit-background-clip:text; -webkit-text-fill-color:transparent;
               background-clip:text; }}
  .hdr-center {{ text-align:center; position:relative; z-index:1; }}
  .brand {{ font-family:'Georgia','Times New Roman',serif; font-size:78px; letter-spacing:7px;
           color:{GOLD}; margin:0 0 10px 0; line-height:1;
           text-shadow: 0 2px 16px rgba(0,0,0,0.55), 0 1px 0 rgba(0,0,0,0.3); }}
  .motto {{ color:#ddd5bd; font-style:italic; font-size:15.5px; margin:0 0 20px 0; }}
  .big-date {{ font-family:'Georgia','Times New Roman',serif; font-size:26px;
              color:#f5f0e6; margin:0 0 6px 0; letter-spacing:1px; }}
  .compiled {{ font-size:13px; color:#a89f87; letter-spacing:2px;
              text-transform:uppercase; margin:0 0 26px 0; }}
  .hdr-bottom {{ display:grid; grid-template-columns:1fr 1fr; gap:20px;
                position:relative; z-index:1; }}
  .preview {{ background:rgba(2,10,28,0.62); border:1px solid rgba(201,162,74,0.5);
             border-left:4px solid {GOLD}; border-radius:0 6px 6px 0;
             padding:18px 24px; text-align:left; }}
  .edition-index {{ background:rgba(2,10,28,0.62); border:1px solid rgba(201,162,74,0.5);
                   border-right:4px solid {GOLD}; border-radius:6px 0 0 6px;
                   padding:18px 24px; text-align:left; }}
  .tabs {{ position: sticky; top:0; z-index:50; display:flex; background:#f7f3ea;
          border-top:2px solid {NAVY}; border-bottom:2px solid {NAVY}; }}
  .tab  {{ flex:1; padding:16px; text-align:center; font-family:'Georgia',serif;
          font-size:14px; letter-spacing:3px; text-transform:uppercase; color:{BLACK};
          background:#efe9d9; cursor:pointer; border:0; border-right:1px solid {RULE}; }}
  .tab:last-child {{ border-right: 0; }}
  .tab:hover {{ background:#e8e0c8; }}
  .tab.active {{ background:{PAPER}; color:{NAVY}; border-bottom:3px solid {GOLD}; }}
  .body {{ background:{PAPER}; padding:36px 40px; }}
  .news-section {{ display:none; }}
  .news-section.active {{ display:block; }}
  .ftr {{ background:{NAVY}; color:#e6dfc7; text-align:center; padding:24px 20px;
         font-size:13px; letter-spacing:1.5px; }}
  @media (max-width: 720px) {{
    .brand {{ font-size:46px; letter-spacing:3px; }}
    .big-date {{ font-size:18px; }}
    .watermark {{ font-size:100px; }}
    .body, .hdr {{ padding: 20px 16px; }}
    .hdr-strip {{ flex-direction:column; align-items:flex-start; gap:8px; }}
  }}
  /* ── Dark mode ──────────────────────────────────────────────── */
  body.dark {{ background:#08111c; }}
  body.dark .wrap {{ background:#0d1b2a; }}
  body.dark .tabs {{ background:#08111c; border-color:#1a2e44; }}
  body.dark .tab {{ background:#0d1b2a; color:#b8b0a0; border-right-color:#1a2e44; }}
  body.dark .tab:hover {{ background:#162436; }}
  body.dark .tab.active {{ background:#0d1b2a; color:{GOLD}; border-bottom-color:{GOLD}; }}
  body.dark .body {{ background:#0d1b2a; color:#d8d0c0; }}
  body.dark .news-article {{ border-bottom-color:#1a2e44 !important; color:#d8d0c0; }}
  body.dark .news-article h2 {{ color:#c9b590 !important; }}
  body.dark .lead-source {{ color:#8a9bb0 !important; }}
  body.dark .lead-source a {{ color:#7ab3d4 !important; border-bottom-color:#4a7a9a !important; }}
  body.dark .card-summary {{ background:#0a1e32 !important; border-color:#1a2e44 !important; color:#d0c8b5 !important; }}
  body.dark .card-angles  {{ background:#1a1400 !important; border-color:#302800 !important; color:#d0c8b5 !important; }}
  body.dark .card-angles table td, body.dark .card-angles table th {{ color:#d0c8b5 !important; border-bottom-color:rgba(201,162,74,0.15) !important; }}
  body.dark .card-angles table tr {{ background:transparent !important; }}
  body.dark .card-angles table a {{ color:#7ab3d4 !important; border-bottom-color:#4a7a9a !important; }}
  body.dark .card-persp   {{ background:#0a1a0f !important; border-color:#1a3020 !important; color:#d0c8b5 !important; }}
  body.dark .card-persp table td, body.dark .card-persp table th {{ color:#d0c8b5 !important; border-bottom-color:rgba(201,162,74,0.15) !important; }}
  body.dark .card-persp table tr {{ background:transparent !important; }}
  body.dark .card-persp table a {{ color:#7ab3d4 !important; border-bottom-color:#4a7a9a !important; }}
  body.dark .img-fallback {{ background:linear-gradient(135deg,#0b1d3a 0%,#162d55 50%,#0b1d3a 100%) !important; border-color:#1a2e44 !important; }}
  body.dark .card-persp   {{ background:#0a1a0f !important; border-color:#1a3020 !important; color:#d0c8b5 !important; }}
  body.dark .card-visual  {{ background:#141000 !important; border-color:#302800 !important; color:#d0c8b5 !important; }}
  body.dark .card-sources {{ border-top-color:#1a2e44 !important; color:#d0c8b5 !important; }}
  body.dark .card-summary > div:first-child,
  body.dark .card-angles  > div:first-child,
  body.dark .card-persp   > div:first-child,
  body.dark .card-visual  > div:first-child,
  body.dark .card-sources > div:first-child {{ color:#a89f87 !important; }}
  body.dark .card-summary li, body.dark .card-angles li, body.dark .card-persp li {{ color:#d0c8b5 !important; }}
  body.dark .card-summary div, body.dark .card-angles div, body.dark .card-persp div {{ color:#d0c8b5 !important; }}
  body.dark .card-summary strong, body.dark .card-angles strong, body.dark .card-persp strong {{ color:#c9b590 !important; }}
  body.dark .card-summary span, body.dark .card-angles span, body.dark .card-persp span {{ color:#8a9bb0 !important; }}
  body.dark .card-summary a, body.dark .card-angles a, body.dark .card-persp a,
  body.dark .card-sources a, body.dark .card-visual a {{ color:#7ab3d4 !important; border-bottom-color:#4a7a9a !important; }}
  body.dark .card-visual div {{ color:#d0c8b5 !important; }}
  body.dark .card-visual td, body.dark .card-visual th {{ color:#d0c8b5 !important; background:#1a1400 !important; border-color:#302800 !important; }}
  body.dark .img-fallback {{ background:#162030 !important; border-color:#1a2e44 !important; color:#8a9bb0 !important; }}
  body.dark .body .section-cat {{ color:#a89f87 !important; }}
  .dark-btn {{ background:rgba(255,255,255,0.08); border:1px solid rgba(201,162,74,0.3);
              border-radius:30px; padding:7px 16px; color:{GOLD}; font-size:12px;
              cursor:pointer; letter-spacing:1px; white-space:nowrap; font-family:inherit; }}
  .dark-btn:hover {{ background:rgba(255,255,255,0.14); }}
</style>
</head>
<body>
<script>if(localStorage.getItem('dnb-dark')==='1')document.body.classList.add('dark');</script>
<div class="wrap">
  <header class="hdr">

    <!-- Top strip: weather pill (left) + dark toggle + edition pill (right) -->
    <div class="hdr-strip">
      <div class="pill">{weather_pill}</div>
      <div style="display:flex;gap:10px;align-items:center;">
        <button class="dark-btn" id="dark-btn" onclick="toggleDark()">&#9790; Dark</button>
        <div class="pill-edition">Edition &nbsp;{edition}</div>
      </div>
    </div>

    <!-- Decorative watermark -->
    <div class="watermark">Daily.</div>

    <!-- Main centred content -->
    <div class="hdr-center">
      <h1 class="brand">Daily News Brief</h1>
      <p class="motto">{_esc(motto)}</p>
      <div class="big-date">{_esc(big_date)}</div>
      <div class="compiled">{compiled_aut} AEST&nbsp;·&nbsp; {compiled_hkt} HKT</div>
      <div class="hdr-bottom">
        <div class="preview">
          {left_panel}
        </div>
        <div class="edition-index">
          {right_panel}
        </div>
      </div>
    </div>

  </header>

  {stocks_banner}

  <nav class="tabs">
    <button class="tab active" data-target="global"   onclick="dnbSwitch(event,'global')">Global</button>
    <button class="tab"        data-target="business" onclick="dnbSwitch(event,'business')">Business &amp; Markets</button>
    <button class="tab"        data-target="hongkong" onclick="dnbSwitch(event,'hongkong')">Hong Kong</button>
  </nav>

  <main class="body">
    {''.join(sections)}
  </main>

  <footer class="ftr">
    Daily News Brief · {now_aest.strftime('%d %B %Y')} · Compiled {compiled_aut} AEST| {compiled_hkt} HKT · For private use only
  </footer>
</div>
<script>
  function dnbSwitch(evt, name) {{
    var sections = document.getElementsByClassName('news-section');
    for (var i=0; i<sections.length; i++) sections[i].classList.remove('active');
    var tabs = document.getElementsByClassName('tab');
    for (var j=0; j<tabs.length; j++) tabs[j].classList.remove('active');
    document.getElementById(name).classList.add('active');
    evt.currentTarget.classList.add('active');
  }}
  function toggleDark() {{
    var body = document.body;
    var btn  = document.getElementById('dark-btn');
    if (body.classList.contains('dark')) {{
      body.classList.remove('dark');
      btn.innerHTML = '&#9790; Dark';
      localStorage.setItem('dnb-dark', '0');
    }} else {{
      body.classList.add('dark');
      btn.innerHTML = '&#9728; Light';
      localStorage.setItem('dnb-dark', '1');
    }}
  }}
  // Sync button label on load
  (function() {{
    var btn = document.getElementById('dark-btn');
    if (btn && document.body.classList.contains('dark')) btn.innerHTML = '&#9728; Light';
  }})();
</script>
</body>
</html>"""

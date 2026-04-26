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


def _esc(s: Any) -> str:
    return html_lib.escape("" if s is None else str(s))


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
        return "<li><em>No angles returned.</em></li>"
    items = []
    for a in angles:
        label = _esc(a.get("angle", "Angle"))
        outlet = _esc(a.get("outlet", ""))
        summary = _esc(a.get("summary", ""))
        url = a.get("url", "") or ""
        cite = (
            f' <a href="{_esc(url)}" style="color:{NAVY};text-decoration:none;border-bottom:1px dotted {NAVY};">{outlet}</a>'
            if outlet and url
            else (f" <span style=\"color:{MUTED};\">{outlet}</span>" if outlet else "")
        )
        items.append(
            f'<li style="margin:0 0 12px 0;">'
            f'<strong style="color:{NAVY};">{label}</strong>{(" -- " + cite) if cite else ""}'
            f'<div style="color:{INK};margin-top:4px;">{summary}</div>'
            f"</li>"
        )
    return "\n".join(items)


def _render_perspectives(persp: list[dict[str, Any]]) -> str:
    if not persp:
        return "<li><em>No perspectives returned.</em></li>"
    items = []
    for p in persp:
        who = _esc(p.get("stakeholder", "Stakeholder"))
        stance = _esc(p.get("stance", ""))
        quote = _esc(p.get("quote_or_paraphrase", ""))
        outlet = _esc(p.get("source", ""))
        url = p.get("url", "") or ""
        cite = (
            f' <a href="{_esc(url)}" style="color:{NAVY};text-decoration:none;border-bottom:1px dotted {NAVY};">{outlet}</a>'
            if outlet and url
            else (f" <span style=\"color:{MUTED};\">{outlet}</span>" if outlet else "")
        )
        items.append(
            f'<li style="margin:0 0 14px 0;">'
            f'<strong style="color:{NAVY};">{who}:</strong> '
            f'<span style="color:{INK};">{stance}</span>'
            f'<div style="margin-top:4px;color:{INK};font-style:italic;">"{quote}"{(" -- " + cite) if cite else ""}</div>'
            f"</li>"
        )
    return "\n".join(items)


def _render_visual_aid(va: dict[str, Any]) -> str:
    if not va:
        return ""
    title = _esc(va.get("title", "Visual Analysis"))
    inner = va.get("html", "") or ""
    # We trust model-supplied HTML but strip script tags defensively.
    inner = inner.replace("<script", "&lt;script").replace("</script", "&lt;/script")
    return (
        f'<div style="background:#fbf7ec;border:1px solid {RULE};border-left:4px solid {GOLD};'
        f'padding:18px 20px;border-radius:6px;margin:18px 0;">'
        f'<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:10px;">'
        f"Visual Analysis -- {title}</div>"
        f'<div style="color:{INK};font-size:14px;line-height:1.55;">{inner}</div>'
        f"</div>"
    )


def _render_sources_list(item: dict[str, Any]) -> str:
    """Compile a deduped list of every source URL in the news item."""
    seen = set()
    rows = []
    def add(name, url):
        key = (url or "").strip()
        if not key or key in seen:
            return
        seen.add(key)
        rows.append(
            f'<li style="margin:0 0 6px 0;font-size:13px;">'
            f'<a href="{_esc(url)}" style="color:{NAVY};text-decoration:none;border-bottom:1px dotted {NAVY};">{_esc(name or url)}</a>'
            f"</li>"
        )

    lead = item.get("lead_source") or {}
    add(lead.get("name", ""), lead.get("url", ""))
    for b in item.get("summary_bullets", []) or []:
        add(b.get("source", ""), b.get("url", ""))
    for a in item.get("reporting_angles", []) or []:
        add(a.get("outlet", ""), a.get("url", ""))
    for p in item.get("perspectives", []) or []:
        add(p.get("source", ""), p.get("url", ""))
    if item.get("video_url"):
        add("Video report", item.get("video_url"))

    if not rows:
        return ""
    return (
        f'<div style="margin-top:24px;padding-top:14px;border-top:1px solid {RULE};">'
        f'<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:8px;">Sources</div>'
        f'<ul style="margin:0;padding-left:18px;color:{INK};">{"".join(rows)}</ul>'
        f"</div>"
    )


def _render_news_item(item: dict[str, Any]) -> str:
    title = _esc(item.get("title", "Untitled"))
    img_url = item.get("image_url") or ""
    video = item.get("video_url") or ""
    lead = item.get("lead_source") or {}
    lead_name = _esc(lead.get("name", ""))
    lead_url = lead.get("url", "") or ""

    img_block = ""
    if img_url:
        fallback_style = (
            f"display:none;width:100%;padding:18px 20px;margin:6px 0 12px;"
            f"background:#f5f0e6;border:1px solid {RULE};border-radius:6px;"
            f"font-size:13px;color:{MUTED};box-sizing:border-box;"
        )
        img_block = (
            f'<img id="img-{abs(hash(img_url))}" src="{_esc(img_url)}" alt="{title}" '
            f'referrerpolicy="no-referrer" crossorigin="anonymous" '
            f'style="display:block;width:100%;max-height:520px;object-fit:cover;'
            f'border-radius:6px;margin:6px 0 12px;border:1px solid {RULE};" '
            f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\'">'
            f'<div style="{fallback_style}">'
            f'Image unavailable due to source restrictions. '
            + (f'<a href="{_esc(lead_url)}" target="_blank" rel="noopener" '
               f'style="color:{NAVY};font-weight:bold;">View at {lead_name}</a>'
               if lead_url else "")
            + f'</div>'
        )

    video_block = ""
    if video:
        outlet = _esc(_outlet_from_url(video))
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
                f'<div style="font-size:13px;color:{MUTED};margin-bottom:14px;">Lead source: '
                f'<a href="{_esc(lead_url)}" style="color:{NAVY};text-decoration:none;border-bottom:1px dotted {NAVY};">{lead_name}</a></div>'
            )
        else:
            lead_block = f'<div style="font-size:13px;color:{MUTED};margin-bottom:14px;">Lead source: {lead_name}</div>'

    return f"""
    <article style="margin:0 0 32px 0;padding:0 0 32px 0;border-bottom:1px solid {RULE};">
      <h2 style="font-family:'Georgia','Times New Roman',serif;font-size:30px;line-height:1.25;color:{NAVY};margin:0 0 10px 0;">{title}</h2>
      {lead_block}
      {img_block}
      {video_block}
      {_render_visual_aid(item.get("visual_aid") or {})}
      <div style="background:#f6f8fc;border:1px solid {RULE};border-radius:6px;padding:18px 20px;margin:18px 0;">
        <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:10px;">News Summary</div>
        <ul style="margin:0;padding-left:20px;color:{INK};font-size:14.5px;line-height:1.6;">
          {_render_summary(item.get("summary_bullets") or [])}
        </ul>
      </div>
      <div style="background:#fff8eb;border:1px solid {RULE};border-radius:6px;padding:18px 20px;margin:18px 0;">
        <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:10px;">Different Reporting Angles</div>
        <ul style="margin:0;padding-left:20px;color:{INK};font-size:14.5px;line-height:1.55;">
          {_render_angles(item.get("reporting_angles") or [])}
        </ul>
      </div>
      <div style="background:#f3f8f1;border:1px solid {RULE};border-radius:6px;padding:18px 20px;margin:18px 0;">
        <div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;color:{NAVY};margin-bottom:10px;">Diverse Stakeholder Perspectives</div>
        <ul style="margin:0;padding-left:20px;color:{INK};font-size:14.5px;line-height:1.55;">
          {_render_perspectives(item.get("perspectives") or [])}
        </ul>
      </div>
      {_render_sources_list(item)}
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


def _render_edition_index(items: list[dict[str, Any]]) -> str:
    """Right-side newspaper-style 'In This Edition' index (WSJ/FT convention)."""
    SECTION_NUMS = ["01", "02", "03"]
    rows = []
    for i, it in enumerate(items):
        num = SECTION_NUMS[i] if i < len(SECTION_NUMS) else f"0{i+1}"
        cat = _esc((it.get("category") or "").upper())
        lead = it.get("lead_source") or {}
        source_name = _esc(lead.get("name", ""))
        title = _esc(it.get("title", ""))
        border = "border-bottom:1px solid rgba(201,162,74,0.18);" if i < len(items) - 1 else ""
        rows.append(
            f'<div style="display:flex;gap:12px;padding:10px 0;{border}">'
            f'<div style="font-family:Georgia,serif;font-size:22px;font-weight:bold;'
            f'color:rgba(201,162,74,0.35);line-height:1;flex-shrink:0;padding-top:2px;">{num}</div>'
            f'<div>'
            f'<div style="font-size:10px;letter-spacing:2.5px;color:{GOLD};'
            f'text-transform:uppercase;margin-bottom:3px;">{cat}</div>'
            f'<div style="font-size:13px;color:#eae4d4;line-height:1.4;">{title}</div>'
            + (f'<div style="font-size:11px;color:#8a8070;margin-top:3px;letter-spacing:0.5px;">'
               f'{source_name}</div>' if source_name else "")
            + f'</div></div>'
        )
    return "\n".join(rows)


def render_html(weather: dict[str, Any], items: list[dict[str, Any]]) -> str:
    aest = pytz.timezone("Australia/Brisbane")
    hkt = pytz.timezone("Asia/Hong_Kong")
    now_aest = datetime.now(aest)
    now_hkt = datetime.now(hkt)

    edition = f"{now_aest.year}.{now_aest.month}.{now_aest.day}"
    long_date = f"{now_aest.day} {now_aest.strftime('%B %Y, %A, %H:%M')}"
    compiled_aut = now_aest.strftime("%H:%M")
    compiled_hkt = now_hkt.strftime("%H:%M")
    motto = _motto_for(now_aest)

    items_by_cat = {it.get("category"): it for it in items}
    ordered = [items_by_cat.get(c, {"category": c, "title": "(no story)"}) for c in CATEGORY_ORDER]

    sections = []
    for i, it in enumerate(ordered):
        cat = it.get("category", "")
        tab_id = CATEGORY_TAB_IDS.get(cat, f"section-{i}")
        active = " active" if i == 0 else ""
        sections.append(
            f'<section id="{tab_id}" class="news-section{active}" data-category="{_esc(cat)}">'
            f'<div style="font-size:12px;letter-spacing:3px;text-transform:uppercase;color:{GOLD};margin-bottom:12px;font-weight:bold;">{_esc(cat)}</div>'
            f"{_render_news_item(it)}"
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

    preview_block = _render_preview(ordered)

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
  .watermark {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-46%);
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
  .preview {{ background:rgba(2,10,28,0.82); border:1px solid rgba(201,162,74,0.5);
             border-left:4px solid {GOLD}; border-radius:0 6px 6px 0;
             padding:18px 24px; text-align:left; }}
  .edition-index {{ background:rgba(2,10,28,0.82); border:1px solid rgba(201,162,74,0.5);
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
</style>
</head>
<body>
<div class="wrap">
  <header class="hdr">

    <!-- Top strip: weather pill (left) + edition pill (right) -->
    <div class="hdr-strip">
      <div class="pill">{weather_pill}</div>
      <div class="pill-edition">Edition &nbsp;{edition}</div>
    </div>

    <!-- Decorative watermark -->
    <div class="watermark">Daily.</div>

    <!-- Main centred content -->
    <div class="hdr-center">
      <h1 class="brand">Daily News Brief</h1>
      <p class="motto">{_esc(motto)}</p>
      <div class="big-date">{_esc(big_date)}</div>
      <div class="compiled">{compiled_aut} AUT &nbsp;·&nbsp; {compiled_hkt} HKT</div>
      <div class="hdr-bottom">
        <div class="preview">
          <div style="font-size:10px;letter-spacing:3px;color:{GOLD};font-weight:bold;text-transform:uppercase;margin-bottom:12px;border-bottom:1px solid rgba(201,162,74,0.3);padding-bottom:8px;">At a Glance</div>
          {preview_block}
        </div>
        <div class="edition-index">
          <div style="font-size:10px;letter-spacing:3px;color:{GOLD};font-weight:bold;text-transform:uppercase;margin-bottom:4px;border-bottom:1px solid rgba(201,162,74,0.3);padding-bottom:8px;">In This Edition</div>
          {_render_edition_index(ordered)}
        </div>
      </div>
    </div>

  </header>

  <nav class="tabs">
    <button class="tab active" data-target="global"   onclick="dnbSwitch(event,'global')">Global</button>
    <button class="tab"        data-target="business" onclick="dnbSwitch(event,'business')">Business &amp; Markets</button>
    <button class="tab"        data-target="hongkong" onclick="dnbSwitch(event,'hongkong')">Hong Kong</button>
  </nav>

  <main class="body">
    {''.join(sections)}
  </main>

  <footer class="ftr">
    Daily News Brief · {now_aest.strftime('%d %B %Y')} · Compiled {compiled_aut} AUT | {compiled_hkt} HKT · For private use only
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
</script>
</body>
</html>"""

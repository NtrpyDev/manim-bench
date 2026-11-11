"""Static HTML for the report.

Every page is one self-contained file: the CSS is in a ``<style>`` block, there
is no JavaScript, and nothing is loaded from another site. Bars are inline SVG
drawn with attributes, and shading uses classes, so the pages need no inline
``style`` attributes. Every value that comes from the data goes through
``html.escape``, because judge replies and model names are not trusted.
"""

from __future__ import annotations

import hashlib
import re
from html import escape
from typing import Any
from urllib.parse import quote

PARTS = [("judge", "Review"), ("layout", "Layout"), ("pacing", "Pacing")]

GATE_WORDS = {
    "code_parses": "Code parses",
    "scene_class": "Scene class defined",
    "renders": "Renders",
    "video": "Video file produced",
    "duration": "Duration in range",
    "not_blank": "Not blank",
    "has_motion": "Has motion",
}

FAILURE_WORDS = {
    "no_code": "no code",
    "syntax_error": "syntax error",
    "missing_scene_class": "missing scene class",
    "render_timeout": "render timeout",
    "render_error": "render error",
    "no_video": "no video",
    "too_short": "too short",
    "too_long": "too long",
    "blank_video": "blank video",
    "static_video": "static video",
    "unknown": "unknown",
}

# The judge scores each criterion from 0 to 4 (manimbench.scoring.judge.MAX_SCORE).
CRITERION_MAX = 4


# Formatting ---------------------------------------------------------------


def _e(value: Any) -> str:
    return "" if value is None else escape(str(value), quote=True)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _score(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number:.1f}"


def _pct(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number:.1f}%"


def _share(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{100.0 * number:.1f}%"


def _secs(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{number:.1f} s"


def _cost(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"${number:.4f}" if abs(number) < 1 else f"${number:,.2f}"


def _int(value: Any) -> str:
    number = _num(value)
    return "n/a" if number is None else f"{int(number):,}"


def _paragraphs(text: Any) -> str:
    """Prose with its source line breaks joined up. Blank lines start a new paragraph."""
    blocks = re.split(r"\n\s*\n", str(text or "").strip())
    return "".join(f"<p>{_e(' '.join(block.split()))}</p>" for block in blocks if block.strip())


def _words(identifier: Any) -> str:
    return str(identifier).replace("_", " ")


def _failure(identifier: Any) -> str:
    return FAILURE_WORDS.get(str(identifier), _words(identifier))


def _slug(value: Any) -> str:
    """A file and anchor name for an id. Ids that are already safe are kept as they are."""
    text = str(value)
    safe = re.sub(r"[^A-Za-z0-9._-]", "-", text).strip(".")
    if safe != text or not safe:
        safe = f"{safe or 'id'}-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]}"
    return safe


def _asset(prefix: str, path: Any) -> str | None:
    """A link to a copied video or source file, or None when the path is not a plain relative one."""
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        return None
    if any(part in {"", ".", ".."} for part in path.split("/")):
        return None
    return prefix + quote(path)


# Small visuals ------------------------------------------------------------


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _bar(value: Any, kind: str = "") -> str:
    """A 0 to 100 bar. The number is always printed next to it by the caller."""
    number = _num(value)
    fill = "" if number is None else f'<rect class="fil{kind}" width="{_clamp(number):.2f}" height="6"/>'
    return (
        '<svg class="bar" viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true">'
        f'<rect class="trk" width="100" height="6"/>{fill}</svg>'
    )


def _metric(value: Any, label: str = "") -> str:
    tag = f'<span class="lbl">{_e(label)}</span>' if label else ""
    return f'<span class="metric">{tag}{_bar(value)}<span class="n">{_score(value)}</span></span>'


def _interval_bar(score: Any, interval: Any) -> str:
    """The score as a tick on a 0 to 100 track, with its 95% interval as a band."""
    number = _num(score)
    parts = ['<svg class="range" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">',
             '<rect class="trk" y="4" width="100" height="2"/>']
    if isinstance(interval, (list, tuple)) and len(interval) == 2 and None not in (_num(interval[0]), _num(interval[1])):
        low, high = sorted((_clamp(float(interval[0])), _clamp(float(interval[1]))))
        width = max(high - low, 1.0)
        parts.append(f'<rect class="band" x="{min(low, 100 - width):.2f}" y="1" width="{width:.2f}" height="8"/>')
    if number is not None:
        parts.append(f'<rect class="tick" x="{_clamp(number) - 0.6:.2f}" width="1.2" height="10"/>')
    parts.append("</svg>")
    return "".join(parts)


def _shade(value: Any) -> str:
    number = _num(value)
    return "s0" if number is None else f"s{int(round(_clamp(number) / 10))}"


# Page frame ---------------------------------------------------------------

CSS = """
:root{
  --bg:#f6f6f3;--surface:#ffffff;--ink:#1d1f22;--muted:#5d6268;--faint:#8b9097;
  --line:#e2e2dd;--track:#e9e9e4;--accent:#2563a6;--accent-soft:#dbe7f4;--code:#f0f0ec;
  color-scheme:light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#131416;--surface:#1b1d20;--ink:#e6e6e3;--muted:#a2a7ad;--faint:#777d84;
    --line:#2d3034;--track:#2c2f33;--accent:#6ea8e6;--accent-soft:#1f3248;--code:#232528;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#131416;--surface:#1b1d20;--ink:#e6e6e3;--muted:#a2a7ad;--faint:#777d84;
  --line:#2d3034;--track:#2c2f33;--accent:#6ea8e6;--accent-soft:#1f3248;--code:#232528;
  color-scheme:dark;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
.wrap{max-width:1240px;margin:0 auto;padding:20px 16px 56px}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
h1{font-size:26px;line-height:1.2;margin:4px 0 8px;letter-spacing:-0.01em}
h2{font-size:17px;margin:36px 0 10px;letter-spacing:0}
h3{font-size:15px;margin:0}
p{margin:6px 0}
.crumb{font-size:13px;color:var(--muted);margin-bottom:6px}
.sub{color:var(--muted);font-size:13px}
.meta{display:flex;flex-wrap:wrap;gap:4px 22px;margin:10px 0 0;padding:0;font-size:13px}
.meta div{display:flex;gap:6px}
.meta dt{color:var(--muted)}
.meta dd{margin:0;font-weight:600}
.status{margin:16px 0 0;padding:10px 14px;border:1px solid var(--line);border-left:4px solid var(--ink);
  background:var(--surface);border-radius:6px;font-weight:600}
.status span{display:block;font-weight:400;color:var(--muted);font-size:13px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-color:var(--faint) transparent}
table{border-collapse:collapse;width:100%;overflow-wrap:normal}
th,td{padding:9px 10px;text-align:left;vertical-align:middle;border-bottom:1px solid var(--line)}
tr:last-child>td{border-bottom:0}
th{font-size:12px;font-weight:600;color:var(--muted);white-space:nowrap;background:var(--surface)}
th small{display:block;font-weight:400;color:var(--faint)}
td.num,th.num{text-align:right}
td.nw{white-space:nowrap}
.lb td{white-space:nowrap}
.lb td.model{white-space:normal;min-width:150px}
.rank{font-size:18px;font-weight:700;width:1%}
.rank.none{font-size:12px;font-weight:600;color:var(--muted)}
.small{font-size:12px;color:var(--muted);display:block;white-space:normal}
.lb .small.nw{white-space:nowrap}
.lb .scorecell{min-width:230px}
.lb .prov{margin-left:0}
a.more{font-size:12px;margin-top:auto}
.big{font-size:17px;font-weight:700}
.prov{font-size:11px;font-weight:600;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 5px;margin-left:6px}
svg.bar{width:52px;height:6px;border-radius:3px;overflow:hidden;flex:none}
svg.range{width:100px;height:10px;flex:none}
.trk{fill:var(--track)}
.fil{fill:var(--accent)}
.band{fill:var(--accent);opacity:.35}
.tick{fill:var(--ink)}
.metric{display:inline-flex;align-items:center;gap:7px;white-space:nowrap}
.metric .n{min-width:3.3em;text-align:right;font-weight:600}
.metric .lbl{min-width:4.2em;color:var(--muted);font-size:12px}
.scorecell{display:flex;align-items:center;gap:10px}
.scorecell .big{min-width:2.4em}
.grid td,.grid th{text-align:center;padding:0;border:1px solid var(--line)}
.grid th{padding:8px 6px;white-space:normal;min-width:92px;max-width:130px;font-size:11px;vertical-align:bottom}
.grid th.rowh,.grid td.rowh{text-align:left;padding:8px 12px;min-width:140px;position:sticky;left:0;background:var(--surface);z-index:1}
.grid td a{display:block;padding:10px 6px;color:var(--ink);font-weight:600}
.grid td a:hover{text-decoration:none;outline:2px solid var(--accent);outline-offset:-2px}
.grid td.empty{background:repeating-linear-gradient(135deg,transparent 0 5px,var(--track) 5px 6px)}
.grid td.empty a{color:var(--muted);font-weight:400;font-size:12px}
.grid td.total{font-weight:700;padding:10px 8px}
.s0{background:var(--surface)}
.s1{background:color-mix(in srgb,var(--accent) 4%,var(--surface))}
.s2{background:color-mix(in srgb,var(--accent) 8%,var(--surface))}
.s3{background:color-mix(in srgb,var(--accent) 13%,var(--surface))}
.s4{background:color-mix(in srgb,var(--accent) 18%,var(--surface))}
.s5{background:color-mix(in srgb,var(--accent) 24%,var(--surface))}
.s6{background:color-mix(in srgb,var(--accent) 30%,var(--surface))}
.s7{background:color-mix(in srgb,var(--accent) 37%,var(--surface))}
.s8{background:color-mix(in srgb,var(--accent) 44%,var(--surface))}
.s9{background:color-mix(in srgb,var(--accent) 51%,var(--surface))}
.s10{background:color-mix(in srgb,var(--accent) 58%,var(--surface))}
.legend{display:flex;white-space:nowrap;align-items:center;gap:4px;font-size:12px;color:var(--muted);margin:8px 2px 0}
.legend i{display:inline-block;width:18px;height:12px;border:1px solid var(--line)}
.zero{color:var(--faint)}
.how{margin:0;padding:14px 18px 14px 36px;font-size:14px}
.how li{margin:6px 0}
.how li::marker{color:var(--muted);font-weight:600}
.stack{display:flex;height:10px;border-radius:5px;overflow:hidden;max-width:360px;margin:6px 0}
.stack svg{width:100%;height:10px}
.wkey{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:13px}
.crit{width:auto;margin:6px 0 0;font-size:13px}
.crit td{padding:4px 10px 4px 0;border:0;vertical-align:top}
.crit td.num{color:var(--muted);white-space:nowrap}
.part1{fill:var(--accent)}
.part2{fill:var(--accent);opacity:.55}
.part3{fill:var(--accent);opacity:.25}
.tiles{display:flex;flex-wrap:wrap;gap:8px}
.tile{flex:1 1 150px;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:10px 14px;display:flex;flex-direction:column;gap:4px;min-width:0}
.tile.wide{flex:2 1 250px}
.tile .metric .lbl{min-width:6.4em}
.tile h4{margin:0;font-size:12px;font-weight:600;color:var(--muted)}
.tile .prov{margin-left:0;align-self:flex-start}
.tile .small{white-space:normal}
.toc{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 0;padding:0;list-style:none;font-size:13px}
.toc a{display:inline-flex;gap:8px;align-items:center;padding:4px 10px;border:1px solid var(--line);border-radius:999px;background:var(--surface);color:var(--ink)}
.toc b{font-weight:700}
section.task{margin-top:34px}
.taskhead{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:4px 16px;border-bottom:1px solid var(--line);padding-bottom:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,340px),1fr));gap:14px;margin-top:14px}
.cards.compact{grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr))}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px;min-width:0;display:flex;flex-direction:column;gap:10px}
.cardhead{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.cardhead .big{font-size:20px}
video{display:block;width:100%;aspect-ratio:16/9;background:#000;border-radius:5px}
.fail{aspect-ratio:16/9;border-radius:5px;border:1px dashed var(--faint);padding:12px;display:flex;flex-direction:column;justify-content:center;gap:4px;font-size:13px;background:repeating-linear-gradient(135deg,transparent 0 7px,var(--track) 7px 8px)}
.fail b{font-size:14px}
.fail .detail{background:var(--surface);padding:2px 6px;border-radius:4px;align-self:flex-start}
.parts{display:flex;flex-direction:column;gap:3px}
.facts{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:0;font-size:12px}
.facts dt{color:var(--muted)}
.facts dd{margin:0;overflow-wrap:anywhere}
.block{font-size:13px;border-top:1px solid var(--line);padding-top:8px}
.block h4{margin:0 0 4px;font-size:12px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.issues{margin:2px 0 0;padding:0;list-style:none}
.issues li{display:flex;gap:8px;align-items:baseline}
.issues .k{font-size:11px;color:var(--muted);min-width:5.5em}
.issues .t{flex:1;min-width:0}
.issues .s{color:var(--muted);white-space:nowrap}
details{border:1px solid var(--line);border-radius:6px;margin-top:6px}
details>summary{cursor:pointer;padding:6px 10px;display:flex;justify-content:space-between;gap:8px;list-style-position:inside}
details>summary b{font-weight:600}
details[open]>summary{border-bottom:1px solid var(--line)}
.jbody{padding:6px 10px 10px}
.jtab{font-size:12px;margin-top:4px}
.jtab td{padding:4px 6px 4px 0;border-bottom:1px solid var(--line);vertical-align:top}
.jtab tr:last-child td{border-bottom:0}
.jtab td.w{white-space:nowrap;width:1%;padding-right:10px}
.jtab .ev{display:block}
.v{display:inline-block;font-size:11px;font-weight:600;padding:0 6px;border-radius:4px;border:1px solid var(--accent);white-space:nowrap}
.v-yes{background:var(--accent);color:var(--surface)}
.v-partial{color:var(--accent);background:var(--accent-soft)}
.v-no{color:var(--muted);border-color:var(--faint)}
.ev{color:var(--muted)}
.note{font-size:12px;color:var(--muted)}
.prompt{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:6px 14px;margin:8px 0 0;font-size:14px;max-width:820px}
.prompt p{margin:8px 0}
.must{margin:8px 0 0;padding-left:22px;font-size:14px}
.must li{margin:3px 0}
.must code{font-size:12px;color:var(--muted)}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px;background:var(--code);padding:1px 4px;border-radius:3px}
.mrow{margin-top:26px}
.mrow .taskhead h3{font-size:16px}
footer{margin-top:44px;font-size:12px;color:var(--faint)}
@media (max-width:640px){
  .wrap{padding:14px 16px 40px}
  h1{font-size:22px}
  th,td{padding:8px 9px}
}
"""


def _page(title: str, body: str, *, home: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"<title>{_e(title)}</title>\n<style>{CSS}</style>\n</head>\n<body>\n"
        f'<div class="wrap">\n{body}\n<footer><a href="{home}">Leaderboard</a></footer>\n</div>\n</body>\n</html>\n'
    )


# Shared pieces ------------------------------------------------------------


def _model_href(prefix: str, model_id: Any) -> str:
    return f"{prefix}models/{_slug(model_id)}.html"


def _task_href(prefix: str, task_id: Any) -> str:
    return f"{prefix}tasks/{_slug(task_id)}.html"


def _unranked_reason(row: dict[str, Any]) -> str:
    samples = row.get("samples") or {}
    reasons = []
    if samples.get("missing"):
        reasons.append(f"{_int(samples['missing'])} missing")
    if samples.get("awaiting_judge"):
        reasons.append(f"{_int(samples['awaiting_judge'])} awaiting judge")
    return ", ".join(reasons) or "incomplete"


def _cost_cell(cost: dict[str, Any]) -> str:
    generation = _num(cost.get("generation_usd")) or 0.0
    judging = _num(cost.get("judging_usd")) or 0.0
    basis = ", ".join(str(item) for item in cost.get("basis") or []) or "none reported"
    lines = [
        f'<span class="big">{_cost(generation + judging)}</span>',
        f'<span class="small nw">generation {_cost(generation)}</span>',
        f'<span class="small nw">judging {_cost(judging)}</span>',
        f'<span class="small nw">cost basis: {_e(basis)}</span>',
    ]
    missing = int(_num(cost.get("samples_without_cost")) or 0)
    if missing:
        lines.append(f'<span class="small">{missing} sample{"s" if missing != 1 else ""} without cost, not counted</span>')
    return "".join(lines)


def _leaderboard_table(rows: list[dict[str, Any]], weights: dict[str, Any], prefix: str, *, link: bool = True) -> str:
    total_weight = sum(_num(value) or 0.0 for value in weights.values()) or 1.0
    head = ['<th class="num">Rank</th><th>Model</th><th>Score<small>95% interval</small></th><th class="num">Gates passed</th>']
    for key, label in PARTS:
        share = 100.0 * (_num(weights.get(key)) or 0.0) / total_weight
        head.append(f"<th>{label}<small>{share:.0f}% of score</small></th>")
    head.append('<th class="num">Samples<small>scored / expected</small></th><th>Cost</th>')
    body = []
    for row in rows:
        samples = row.get("samples") or {}
        components = row.get("components") or {}
        name = _e(row.get("name") or row.get("model"))
        if link:
            name = f'<a href="{_model_href(prefix, row.get("model"))}">{name}</a>'
        if row.get("rank") is not None:
            rank = f'<td class="rank num">{_int(row["rank"])}</td>'
            interval = row.get("quality_interval")
            interval_text = (
                f"{_score(interval[0])} to {_score(interval[1])}"
                if isinstance(interval, (list, tuple)) and len(interval) == 2
                else "no interval"
            )
            score = (
                f'<td><div class="scorecell"><span class="big">{_score(row.get("quality"))}</span>'
                f'<span>{_interval_bar(row.get("quality"), interval)}<span class="small">{interval_text}</span></span></div></td>'
            )
        else:
            rank = '<td class="rank none num">not ranked</td>'
            score = (
                f'<td><div class="scorecell"><span class="big">{_score(row.get("automated"))}</span>'
                '<span><span class="prov">provisional</span><span class="small">measured parts only</span>'
                f'<span class="small">{_e(_unranked_reason(row))}</span></span></div></td>'
            )
        parts = "".join(f"<td>{_metric(components.get(key))}</td>" for key, _label in PARTS)
        scored = f'{_int(samples.get("scored"))} / {_int(samples.get("expected"))}'
        extra = []
        if samples.get("missing"):
            extra.append(f'{_int(samples["missing"])} missing')
        if samples.get("awaiting_judge"):
            extra.append(f'{_int(samples["awaiting_judge"])} awaiting judge')
        if samples.get("failed_gate"):
            extra.append(f'{_int(samples["failed_gate"])} failed a gate')
        extra_html = f'<span class="small">{", ".join(extra)}</span>' if extra else ""
        body.append(
            f'<tr>{rank}<td class="model">{name}<span class="small">{_e(row.get("vendor"))}</span></td>{score}'
            f'<td class="num">{_pct(row.get("gate_pass_rate"))}</td>{parts}'
            f'<td class="num">{scored}{extra_html}</td><td>{_cost_cell(row.get("cost") or {})}</td></tr>'
        )
    return (
        '<div class="panel scroll"><table class="lb"><thead><tr>'
        + "".join(head)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def _summary_tiles(row: dict[str, Any], weights: dict[str, Any]) -> str:
    """The model's leaderboard row as tiles that wrap on a phone. Same numbers, same formatting."""
    samples = row.get("samples") or {}
    components = row.get("components") or {}
    total_weight = sum(_num(value) or 0.0 for value in weights.values()) or 1.0
    if row.get("rank") is not None:
        interval = row.get("quality_interval")
        interval_text = (
            f"95% interval {_score(interval[0])} to {_score(interval[1])}"
            if isinstance(interval, (list, tuple)) and len(interval) == 2
            else "no interval"
        )
        rank = f'<span class="big">{_int(row["rank"])}</span>'
        score = (
            f'<span class="big">{_score(row.get("quality"))}</span>{_interval_bar(row.get("quality"), interval)}'
            f'<span class="small">{interval_text}</span>'
        )
    else:
        rank = f'<span class="big">not ranked</span><span class="small">{_e(_unranked_reason(row))}</span>'
        score = (
            f'<span class="big">{_score(row.get("automated"))}</span><span class="prov">provisional</span>'
            '<span class="small">measured parts only</span>'
        )
    parts = "".join(
        _metric(components.get(key), f"{label} {100.0 * (_num(weights.get(key)) or 0.0) / total_weight:.0f}%")
        for key, label in PARTS
    )
    extra = []
    for key, words in [("missing", "missing"), ("awaiting_judge", "awaiting judge"), ("failed_gate", "failed a gate")]:
        if samples.get(key):
            extra.append(f"{_int(samples[key])} {words}")
    tiles = [
        ("Rank", rank),
        ("Score", score),
        ("Gates passed", f'<span class="big">{_pct(row.get("gate_pass_rate"))}</span>'),
        ("Parts", f'<span class="parts">{parts}</span>'),
        (
            "Samples scored",
            f'<span class="big">{_int(samples.get("scored"))} / {_int(samples.get("expected"))}</span>'
            + (f'<span class="small">{", ".join(extra)}</span>' if extra else ""),
        ),
        ("Cost", _cost_cell(row.get("cost") or {})),
    ]
    return '<div class="tiles">' + "".join(f'<div class="tile{" wide" if label == "Parts" else ""}"><h4>{label}</h4>{body}</div>' for label, body in tiles) + "</div>"


def _status(leaderboard: dict[str, Any]) -> str:
    out = []
    if not leaderboard.get("official"):
        out.append(
            '<div class="status" role="status">Not an official run: render settings or sample count differ from the suite'
            "<span>Scores are not comparable with official runs.</span></div>"
        )
    if not leaderboard.get("complete"):
        out.append(
            '<div class="status" role="status">Incomplete: some samples are missing or not judged'
            "<span>Models with missing or unjudged samples are not ranked.</span></div>"
        )
    return "".join(out)


# Index --------------------------------------------------------------------


def _index(data: dict[str, Any]) -> str:
    board = data.get("leaderboard") or {}
    rows = board.get("models") or []
    tasks = data.get("tasks") or []
    suite = board.get("suite") or {}
    title = suite.get("title") or suite.get("id") or "ManimBench"
    judges = ", ".join(str(item) for item in board.get("judges") or []) or "none"
    meta = [
        ("Run", board.get("run_id")),
        ("Manim", board.get("manim_version")),
        ("Samples per task", board.get("samples_per_task")),
        ("Judges", judges),
        ("Date", str(board.get("generated_at") or "")[:10]),
    ]
    header = (
        f"<header><h1>{_e(title)}</h1>"
        '<p class="sub">How well AI models teach mathematics with Manim animations.</p>'
        '<dl class="meta">'
        + "".join(f"<div><dt>{label}</dt><dd>{_e(value)}</dd></div>" for label, value in meta)
        + "</dl>"
        + _status(board)
        + "</header>"
    )
    parts = [header, "<h2>Leaderboard</h2>", _leaderboard_table(rows, board.get("weights") or {}, "")]
    parts.append("<h2>Score by task</h2>")
    parts.append(_task_grid(rows, tasks))
    parts.append("<h2>Gate failures</h2>")
    parts.append(_failure_table(rows))
    parts.append("<h2>How scores are made</h2>")
    parts.append(_how(board))
    return _page(f"{title} results", "\n".join(parts), home="index.html")


def _task_grid(rows: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> str:
    head = '<th class="rowh">Model</th>' + "".join(
        f'<th><a href="{_task_href("", task.get("id"))}">{_e(task.get("title") or task.get("id"))}</a></th>' for task in tasks
    ) + "<th>Overall</th>"
    body = []
    for row in rows:
        cells = [f'<td class="rowh"><a href="{_model_href("", row.get("model"))}">{_e(row.get("name") or row.get("model"))}</a></td>']
        by_task = row.get("tasks") or {}
        for task in tasks:
            info = by_task.get(task.get("id")) or {}
            href = f'{_task_href("", task.get("id"))}#m-{_slug(row.get("model"))}'
            if info.get("complete") and _num(info.get("quality")) is not None:
                cells.append(f'<td class="{_shade(info["quality"])}"><a href="{href}">{_score(info["quality"])}</a></td>')
            else:
                counts = f'{_int(info.get("samples", 0))}/{_int(info.get("expected_samples", 0))}'
                cells.append(f'<td class="empty"><a href="{href}">incomplete<br>{counts}</a></td>')
        overall = row.get("quality") if row.get("rank") is not None else None
        cells.append(f'<td class="total">{_score(overall)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    legend = (
        '<div class="legend">0<i class="s0"></i><i class="s2"></i><i class="s4"></i><i class="s6"></i>'
        '<i class="s8"></i><i class="s10"></i>100</div>'
        '<p class="note">Task score, mean over samples. Hatched cells: incomplete.</p>'
    )
    return f'<div class="panel scroll"><table class="grid"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>{legend}'


def _failure_table(rows: list[dict[str, Any]]) -> str:
    kinds = sorted({kind for row in rows for kind in (row.get("failures") or {})})
    if not kinds:
        return '<p class="sub">No sample failed a gate.</p>'
    head = "<th>Model</th>" + "".join(f'<th class="num">{_e(_failure(kind))}</th>' for kind in kinds) + '<th class="num">Failed / present</th>'
    body = []
    for row in rows:
        failures = row.get("failures") or {}
        samples = row.get("samples") or {}
        cells = []
        for kind in kinds:
            count = int(_num(failures.get(kind)) or 0)
            cells.append(f'<td class="num{" zero" if not count else ""}">{count}</td>')
        body.append(
            f'<tr><td class="nw"><a href="{_model_href("", row.get("model"))}">{_e(row.get("name") or row.get("model"))}</a></td>'
            + "".join(cells)
            + f'<td class="num">{_int(samples.get("failed_gate", 0))} / {_int(samples.get("present", 0))}</td></tr>'
        )
    return f'<div class="panel scroll"><table><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _how(board: dict[str, Any]) -> str:
    weights = board.get("weights") or {}
    total = sum(_num(value) or 0.0 for value in weights.values()) or 1.0
    shares = [(label, 100.0 * (_num(weights.get(key)) or 0.0) / total) for key, label in PARTS]
    stack, offset = [], 0.0
    for index, (_label, share) in enumerate(shares, start=1):
        stack.append(f'<rect class="part{index}" x="{offset:.2f}" width="{share:.2f}" height="10"/>')
        offset += share
    criteria = board.get("criteria") or []
    criteria_total = sum(_num(item.get("weight")) or 0.0 for item in criteria) or 1.0
    rows = "".join(
        f'<tr><td class="num">{100.0 * (_num(item.get("weight")) or 0.0) / criteria_total:.0f}%</td>'
        f"<td><b>{_e(_words(item.get('id')))}</b>: {_e(item.get('question'))}</td></tr>"
        for item in criteria
    )
    key = "".join(f"<span>{label} {share:.0f}%</span>" for label, share in shares)
    return (
        '<div class="panel"><ol class="how">'
        "<li><b>Gates.</b> The code must parse, define the scene class and render to a video of allowed length "
        "that is not blank and has motion. A sample that fails a gate scores 0.</li>"
        "<li><b>Parts.</b> A passing sample scores 0 to 100 as a weighted mean of three parts. "
        "Layout counts time with clipped, overlapping or too small text. Pacing counts motion, long still stretches and blank time. "
        "A part that could not be measured is left out and the rest are rescaled."
        f'<div class="stack"><svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">{"".join(stack)}</svg></div>'
        f'<div class="wkey">{key}</div></li>'
        f"<li><b>Review.</b> Each judge scores the video 0 to {CRITERION_MAX} on each question below, and the judges are averaged."
        f'<table class="crit"><tbody>{rows}</tbody></table></li>'
        "<li><b>Totals.</b> A task's score is the mean over its samples. A model's score is the mean over tasks, "
        "with a 95% bootstrap interval. Only models with every sample scored are ranked.</li>"
        "</ol></div>"
    )


# Sample cards -------------------------------------------------------------


def _failed_gate_box(gates: dict[str, Any]) -> str:
    checks = gates.get("checks") or {}
    lines = [f'<b>Failed gate: {_e(_failure(gates.get("failure") or "unknown"))}</b>']
    for name, check in checks.items():
        if isinstance(check, dict) and not check.get("passed"):
            detail = f' <span class="detail">{_e(check.get("detail"))}</span>' if check.get("detail") else ""
            lines.append(f"<span>{_e(GATE_WORDS.get(name, _words(name)))}:{detail}</span>")
    not_run = gates.get("not_run") or []
    if not_run:
        lines.append(f'<span class="note">Not run: {_e(", ".join(GATE_WORDS.get(item, _words(item)).lower() for item in not_run))}</span>')
    return '<div class="fail">' + "".join(lines) + "</div>"


def _sample_score(result: dict[str, Any]) -> tuple[str, str]:
    """The headline number and a short label under it."""
    score = result.get("score") or {}
    status = score.get("status")
    if status == "failed_gate":
        return _score(score.get("quality", 0.0)), "failed gate"
    if status == "scored":
        return _score(score.get("quality")), ""
    return _score(score.get("automated")), "provisional, awaiting judge"


def _media(result: dict[str, Any], prefix: str) -> str:
    gates = result.get("gates") or {}
    if not gates.get("passed"):
        return _failed_gate_box(gates)
    video = _asset(prefix, result.get("video"))
    if video:
        return f'<video controls preload="none" src="{_e(video)}"></video>'
    return '<div class="fail"><b>No video in this report</b></div>'


def _parts(result: dict[str, Any]) -> str:
    components = (result.get("score") or {}).get("components") or {}
    if not components:
        return ""
    return '<div class="parts">' + "".join(_metric(components.get(key), label) for key, label in PARTS) + "</div>"


def _card_head(result: dict[str, Any], label: str) -> str:
    number, note = _sample_score(result)
    note_html = f'<span class="small">{_e(note)}</span>' if note else ""
    return f'<div class="cardhead"><h3>{label}</h3><span><span class="big">{number}</span>{note_html}</span></div>'


def _layout_block(layout: dict[str, Any] | None) -> str:
    if not layout:
        return ""
    if not layout.get("available"):
        reason = _words(layout.get("reason") or "not measured")
        return f'<div class="block"><h4>Layout</h4><span class="note">Not measured: {_e(reason)}</span></div>'
    seconds = layout.get("problem_seconds") or {}
    summary = ", ".join(f"{_e(_words(kind))} {_secs(value)}" for kind, value in seconds.items())
    issues = layout.get("issues") or []
    items = "".join(
        f'<li><span class="k">{_e(_words(issue.get("kind")))}</span><span class="t">{_e(issue.get("text"))}</span>'
        f'<span class="s">{_secs(issue.get("seconds"))}</span></li>'
        for issue in issues
        if isinstance(issue, dict)
    )
    listing = f'<ul class="issues">{items}</ul>' if items else '<span class="note">No layout issues.</span>'
    return f'<div class="block"><h4>Layout {_score(layout.get("score"))}</h4><div class="note">{summary}</div>{listing}</div>'


def _pacing_block(pacing: dict[str, Any] | None) -> str:
    if not pacing:
        return ""
    if not pacing.get("available"):
        return '<div class="block"><h4>Pacing</h4><span class="note">Not measured.</span></div>'
    facts = [
        ("In motion", _share(pacing.get("active_share"))),
        ("Longest still", _secs(pacing.get("longest_still_seconds"))),
        ("Dead time", _secs(pacing.get("dead_seconds"))),
        ("Blank", _share(pacing.get("blank_share"))),
    ]
    return (
        f'<div class="block"><h4>Pacing {_score(pacing.get("score"))}</h4><dl class="facts">'
        + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in facts)
        + "</dl></div>"
    )


def _judge_block(result: dict[str, Any], must_text: dict[str, str]) -> str:
    combined = result.get("judge") or {}
    records = result.get("judgements") or []
    if not records and combined.get("status") in (None, "pending") and not (result.get("gates") or {}).get("passed"):
        return ""
    head = f'Review {_score(combined.get("score"))}'
    detail = f'{_int(combined.get("judges", 0))} of {_int(combined.get("expected", 0))} judges'
    if _num(combined.get("spread")) is not None:
        detail += f', spread {_score(combined.get("spread"))}'
    out = [f'<div class="block"><h4>{head}</h4><span class="note">{_e(_words(combined.get("status") or "pending"))}, {detail}</span>']
    for record in records:
        if not isinstance(record, dict):
            continue
        out.append(_judgement(record, must_text))
    out.append("</div>")
    return "".join(out)


def _judgement(record: dict[str, Any], must_text: dict[str, str]) -> str:
    status = record.get("status")
    summary = f'<summary><b>{_e(record.get("judge_id"))}</b><span>{_score(record.get("score")) if status == "complete" else _e(_words(status or "unknown"))}</span></summary>'
    if status != "complete":
        error = f'<p class="ev">{_e(record.get("error"))}</p>' if record.get("error") else ""
        return f'<details>{summary}<div class="jbody">{error or "<p class=ev>No reply.</p>"}</div></details>'
    reply = record.get("reply") or {}
    must = reply.get("must_show") or {}
    must_rows = "".join(
        f'<tr><td class="w"><span class="v v-{_e(_verdict_class(entry))}">{_e(entry.get("verdict"))}</span></td>'
        f'<td>{_e(must_text.get(item_id) or _words(item_id))}'
        f'<span class="ev">{_e(entry.get("evidence"))}</span></td></tr>'
        for item_id, entry in must.items()
        if isinstance(entry, dict)
    )
    reply_criteria = reply.get("criteria") or {}
    crit_rows = []
    for name, value in (record.get("criteria") or {}).items():
        entry = reply_criteria.get(name)
        if isinstance(entry, dict):
            evidence = _e(entry.get("evidence"))
        else:
            evidence = "from the must-show verdicts" if must else ""
        number = _num(value)
        shown = "n/a" if number is None else f"{number:g} / {CRITERION_MAX}"
        crit_rows.append(
            f'<tr><td class="w">{shown}</td><td>{_e(_words(name))}<span class="ev">{evidence}</span></td></tr>'
        )
    parts = [f'<details>{summary}<div class="jbody">']
    if must_rows:
        parts.append(f'<table class="jtab"><tbody>{must_rows}</tbody></table>')
    if crit_rows:
        parts.append(f'<table class="jtab"><tbody>{"".join(crit_rows)}</tbody></table>')
    errors = [item for item in reply.get("math_errors") or [] if item]
    if errors:
        parts.append('<p class="note">Math errors:</p><ul class="issues">' + "".join(f"<li>{_e(item)}</li>" for item in errors) + "</ul>")
    if reply.get("summary"):
        parts.append(f'<p class="ev">{_e(reply["summary"])}</p>')
    parts.append("</div></details>")
    return "".join(parts)


def _verdict_class(entry: dict[str, Any]) -> str:
    verdict = str(entry.get("verdict"))
    return verdict if verdict in {"yes", "partial", "no"} else "no"


def _generation_block(result: dict[str, Any], prefix: str) -> str:
    info = result.get("generation") or {}
    tokens = f'{_int(info.get("input_tokens"))} in, {_int(info.get("output_tokens"))} out'
    if info.get("reasoning_tokens") is not None:
        tokens += f', {_int(info.get("reasoning_tokens"))} reasoning'
    cost = _cost(info.get("cost_usd"))
    if info.get("cost_basis"):
        cost += f' ({_e(info.get("cost_basis"))})'
    facts = [
        ("Route", _e(info.get("route") or "n/a")),
        ("Model", _e(info.get("response_model") or info.get("requested_model") or "n/a")),
        ("Tokens", tokens),
        ("Cost", cost),
    ]
    render = result.get("render") or {}
    if _num(render.get("duration_seconds")) is not None:
        facts.append(("Video", f'{_secs(render.get("duration_seconds"))}, {_int(render.get("width"))}x{_int(render.get("height"))}'))
    source = _asset(prefix, result.get("source"))
    link = f'<a href="{_e(source)}">Source code</a>' if source else '<span class="note">No source file</span>'
    return (
        f'<div class="block"><h4>Generation</h4><dl class="facts">'
        + "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in facts)
        + f"</dl><p>{link}</p></div>"
    )


def _full_card(result: dict[str, Any], must_text: dict[str, str]) -> str:
    anchor = f's-{_slug(result.get("task", {}).get("id"))}-{_slug(result.get("sample"))}'
    return (
        f'<article class="card" id="{anchor}">'
        + _card_head(result, f'Sample {_e(result.get("sample"))}')
        + _media(result, "../")
        + _parts(result)
        + _layout_block(result.get("layout"))
        + _pacing_block(result.get("pacing"))
        + _judge_block(result, must_text)
        + _generation_block(result, "../")
        + "</article>"
    )


def _compact_card(result: dict[str, Any]) -> str:
    task_id = (result.get("task") or {}).get("id")
    details = f'{_model_href("../", result.get("model"))}#s-{_slug(task_id)}-{_slug(result.get("sample"))}'
    return (
        '<article class="card">'
        + _card_head(result, f'Sample {_e(result.get("sample"))}')
        + _media(result, "../")
        + _parts(result)
        + f'<a class="more" href="{details}">Full details</a>'
        + "</article>"
    )


def _sort_key(result: dict[str, Any]) -> tuple[float, int]:
    score = result.get("score") or {}
    value = _num(score.get("quality"))
    if value is None:
        value = _num(score.get("automated"))
    sample = _num(result.get("sample"))
    return (-(value if value is not None else -1.0), int(sample or 0))


# Model and task pages -----------------------------------------------------


def _task_metric(info: dict[str, Any], complete: bool) -> str:
    if complete:
        return _metric(info.get("quality"), "Task")
    return '<span class="metric"><span class="lbl">Task</span><span class="prov">incomplete</span></span>'


def _model_page(row: dict[str, Any], data: dict[str, Any]) -> str:
    board = data.get("leaderboard") or {}
    tasks = data.get("tasks") or []
    model_id = row.get("model")
    own = [result for result in data.get("results") or [] if result.get("model") == model_id]
    title = row.get("name") or model_id
    suite_title = (board.get("suite") or {}).get("title") or "ManimBench"
    failures = row.get("failures") or {}
    failure_text = ", ".join(f"{_e(_failure(kind))} {_int(count)}" for kind, count in failures.items()) or "none"
    by_task = row.get("tasks") or {}
    toc = []
    sections = []
    for task in tasks:
        task_id = task.get("id")
        info = by_task.get(task_id) or {}
        complete = info.get("complete") and _num(info.get("quality")) is not None
        number = _score(info.get("quality")) if complete else "incomplete"
        toc.append(f'<li><a href="#t-{_slug(task_id)}">{_e(task.get("title") or task_id)} <b>{number}</b></a></li>')
        must_text = {str(item.get("id")): str(item.get("text")) for item in task.get("must_show") or [] if isinstance(item, dict)}
        samples = sorted((result for result in own if (result.get("task") or {}).get("id") == task_id), key=lambda item: _num(item.get("sample")) or 0)
        cards = "".join(_full_card(result, must_text) for result in samples)
        counts = f'{_int(info.get("samples", len(samples)))} of {_int(info.get("expected_samples", board.get("samples_per_task")))} samples, {_int(info.get("passed_gates", 0))} passed the gates'
        sections.append(
            f'<section class="task" id="t-{_slug(task_id)}"><div class="taskhead">'
            f'<h2><a href="{_task_href("../", task_id)}">{_e(task.get("title") or task_id)}</a></h2>'
            f'<span>{_task_metric(info, complete)}<span class="small">{counts}</span></span></div>'
            f'<div class="cards">{cards or "<p class=sub>No samples in this report.</p>"}</div></section>'
        )
    body = (
        f'<nav class="crumb"><a href="../index.html">{_e(suite_title)}</a> / model</nav>'
        f'<header><h1>{_e(title)}</h1><p class="sub">{_e(row.get("vendor"))}{" / " if row.get("vendor") else ""}<code>{_e(model_id)}</code></p>'
        + _status(board)
        + "</header>"
        + "<h2>Summary</h2>"
        + _summary_tiles(row, board.get("weights") or {})
        + f'<p class="sub">Gate failures: {failure_text}</p>'
        + f'<ul class="toc">{"".join(toc)}</ul>'
        + "".join(sections)
    )
    return _page(f"{title} on {suite_title}", body, home="../index.html")


def _task_page(task: dict[str, Any], data: dict[str, Any]) -> str:
    board = data.get("leaderboard") or {}
    rows = board.get("models") or []
    task_id = task.get("id")
    suite_title = (board.get("suite") or {}).get("title") or "ManimBench"
    results = [result for result in data.get("results") or [] if (result.get("task") or {}).get("id") == task_id]
    must = "".join(
        f'<li>{_e(item.get("text"))} <code>{_e(item.get("id"))}</code></li>' for item in task.get("must_show") or [] if isinstance(item, dict)
    )

    def order(row: dict[str, Any]) -> tuple[int, float]:
        info = (row.get("tasks") or {}).get(task_id) or {}
        if info.get("complete") and _num(info.get("quality")) is not None:
            return (0, -float(info["quality"]))
        automated = _num(info.get("automated"))
        return (1, -(automated if automated is not None else -1.0))

    groups = []
    for row in sorted(rows, key=order):
        model_id = row.get("model")
        info = (row.get("tasks") or {}).get(task_id) or {}
        complete = info.get("complete") and _num(info.get("quality")) is not None
        own = sorted((result for result in results if result.get("model") == model_id), key=_sort_key)
        cards = "".join(_compact_card(result) for result in own)
        label = "" if complete else f'<span class="prov">incomplete, {_int(info.get("samples", len(own)))} of {_int(info.get("expected_samples", board.get("samples_per_task")))} samples</span>'
        groups.append(
            f'<section class="mrow" id="m-{_slug(model_id)}"><div class="taskhead">'
            f'<h3><a href="{_model_href("../", model_id)}">{_e(row.get("name") or model_id)}</a>{label}</h3>'
            f'{_metric(info.get("quality"), "Task") if complete else ""}</div>'
            f'<div class="cards compact">{cards or "<p class=sub>No samples in this report.</p>"}</div></section>'
        )
    domains = ", ".join(_words(item) for item in task.get("domains") or [])
    body = (
        f'<nav class="crumb"><a href="../index.html">{_e(suite_title)}</a> / task</nav>'
        f'<header><h1>{_e(task.get("title") or task_id)}</h1><p class="sub"><code>{_e(task_id)}</code>'
        f'{" / " + _e(domains) if domains else ""}</p>'
        + _status(board)
        + "</header>"
        + f'<h2>Prompt</h2><div class="prompt">{_paragraphs(task.get("prompt"))}</div>'
        + f'<h2>Must show</h2><ol class="must">{must}</ol>'
        + '<h2>Samples by model</h2><p class="sub">Best task score first. Within a model, best sample first.</p>'
        + "".join(groups)
    )
    return _page(f"{task.get('title') or task_id} on {suite_title}", body, home="../index.html")


def render_pages(data: dict[str, Any]) -> dict[str, str]:
    """Every page of the report, keyed by its path relative to the report folder."""
    board = data.get("leaderboard") or {}
    pages = {"index.html": _index(data)}
    for row in board.get("models") or []:
        pages[f"models/{_slug(row.get('model'))}.html"] = _model_page(row, data)
    for task in data.get("tasks") or []:
        pages[f"tasks/{_slug(task.get('id'))}.html"] = _task_page(task, data)
    return pages

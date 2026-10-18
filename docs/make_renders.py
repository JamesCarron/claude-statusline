"""Build the README images in docs/img/ from the real status line.

Written 2026-10-18 for the claude-statusline README. Each terminal render is
statusline.sh's own output (preview mode, via config_server.render_preview)
for a synthetic payload and config, drawn as an SVG with the line's ANSI
colours, so the pictures cannot drift from what the script prints. Also draws
the weekly-quota hide-threshold chart. Runs inside a temp LOCALAPPDATA holding
a fresh totals cache, as the tests do, so no ccusage run is triggered and your
real state is untouched. Stdlib only:

    python docs/make_renders.py        (from the repo root)

Verified by opening every SVG in Chrome and checking each against the
script's printed line.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"
sys.path.insert(0, str(ROOT))
import config_server as cs  # noqa: E402

NOW = int(time.time())
DAY = 86400

# terminal palette: ANSI default / dim / cyan / yellow on a dark surface
BG, EDGE, INK, DIM, ACCENT, WARN = "#16161a", "#2c2c33", "#e4e4e8", "#8c8c96", "#6ec6e6", "#e6b450"
FONT = "ui-monospace,SFMono-Regular,'Cascadia Mono',Consolas,'Liberation Mono',monospace"
# Advance per character at 14px. Glyph widths differ between the fonts above, so the
# line is pinned to exactly n * CH with textLength and never clips or trails off.
CH = 8.0


def midnight_in(days: int) -> int:
    """Local midnight `days` from today -- weekly quotas reset at local midnight."""
    t = time.localtime(NOW)
    return int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday + days, 0, 0, 0, 0, 0, -1)))


def windows(reset: int) -> tuple[str, str]:
    """Python mirror of the script's week/month window maths (as in the tests)."""
    t = reset - 604800 + 43200
    wk = time.strftime("%Y%m%d", time.localtime(t))
    while time.localtime(t).tm_mday > 7:
        t -= 604800
    return time.strftime("%Y%m%d", time.localtime(t)), wk


def payload(q5: int, wk: int, wk_reset: int, ctx_used: int = 9, sess: float = 0.62) -> str:
    return json.dumps({
        "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
        "workspace": {"current_dir": "C:\\Users\\me\\Documents\\my-app"},
        "effort": {"level": "high"},
        "cost": {"total_cost_usd": sess},
        "context_window": {"used_percentage": ctx_used, "remaining_percentage": 100 - ctx_used},
        "rate_limits": {"five_hour": {"used_percentage": q5, "resets_at": NOW + 2 * 3600 + 10 * 60},
                        "seven_day": {"used_percentage": wk, "resets_at": wk_reset}},
    })


def render(cfg_over: dict, pl: str, wk_reset: int, week: float = 96.4, month: float = 392.1) -> list[dict]:
    """Shown segments, in order, exactly as the real line would print them."""
    mo, wkf = windows(wk_reset)
    (cs.state_dir() / "totals.txt").write_text(f"{mo} {wkf} {NOW + 3600} {week} {month}\n", newline="\n")
    cfg = cs.validate(cfg_over)
    show = cfg["show"].split(",")
    return [s for s in cs.render_preview(cfg, pl)
            if s["id"] in show and s["text"] and s["colour"] != "hidden"]


def terminal_svg(segs: list[dict]) -> str:
    """One status line under a prompt box, like Claude Code's footer."""
    colour = {"dim": DIM, "accent": ACCENT, "warn": WARN}
    parts, n = [], 0
    for i, s in enumerate(segs):
        if i:
            parts.append(f'<tspan fill="{DIM}"> | </tspan>')
            n += 3
        parts.append(f'<tspan fill="{colour.get(s["colour"], INK)}">{escape(s["text"])}</tspan>')
        n += len(s["text"])
    w = int(n * CH) + 40
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="84" viewBox="0 0 {w} 84">
<rect x="0.5" y="0.5" width="{w - 1}" height="83" rx="8" fill="{BG}" stroke="{EDGE}"/>
<rect x="12.5" y="10.5" width="{w - 25}" height="28" rx="5" fill="none" stroke="{EDGE}"/>
<text x="22" y="29" font-family="{FONT}" font-size="14" fill="{DIM}">&gt;</text>
<text x="20" y="64" font-family="{FONT}" font-size="14" xml:space="preserve" textLength="{n * CH:.1f}" lengthAdjust="spacingAndGlyphs">{"".join(parts)}</text>
</svg>
'''


def threshold_svg() -> str:
    """Used % against days since the weekly reset: the pace line and the fixed line."""
    W, H, L, R, T, B = 680, 330, 58, 24, 22, 52
    pw, ph = W - L - R, H - T - B
    x = lambda d: L + d / 7 * pw  # noqa: E731
    y = lambda p: T + (1 - p / 100) * ph  # noqa: E731
    g = [f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="8" fill="{BG}" stroke="{EDGE}"/>']
    # hidden region under the pace line, shown region above
    g.append(f'<path d="M{x(0)},{y(0)} L{x(7)},{y(100)} L{x(7)},{y(0)} Z" fill="{DIM}" fill-opacity="0.16"/>')
    for p in range(0, 101, 20):
        g.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(p)}" y2="{y(p)}" stroke="{EDGE}"/>')
        g.append(f'<text x="{L - 8}" y="{y(p) + 4}" text-anchor="end" fill="{DIM}">{p}%</text>')
    for d in range(8):
        g.append(f'<text x="{x(d)}" y="{T + ph + 18}" text-anchor="middle" fill="{DIM}">{d}</text>')
    g.append(f'<text x="{L + pw / 2}" y="{H - 10}" text-anchor="middle" fill="{DIM}">days since the weekly reset</text>')
    g.append(f'<text transform="translate(16 {T + ph / 2}) rotate(-90)" text-anchor="middle" fill="{DIM}">weekly quota used</text>')
    # fixed 80 % line and pace line
    g.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(80)}" y2="{y(80)}" stroke="{WARN}" stroke-width="1.5" stroke-dasharray="6 5"/>')
    g.append(f'<text x="{x(0.12)}" y="{y(80) - 7}" fill="{WARN}">fixed: shown from 80% used (default)</text>')
    g.append(f'<line x1="{x(0)}" y1="{y(0)}" x2="{x(7)}" y2="{y(100)}" stroke="{ACCENT}" stroke-width="2"/>')
    g.append(f'<text x="{x(5.85)}" y="{y(92)}" text-anchor="end" fill="{ACCENT}">pace: 14.29% x days</text>')
    g.append(f'<text x="{x(4.6)}" y="{y(22)}" fill="{INK}">hidden: under an even</text>')
    g.append(f'<text x="{x(4.6)}" y="{y(22) + 17}" fill="{INK}">share of the week</text>')
    g.append(f'<text x="{x(0.35)}" y="{y(60)}" fill="{INK}">shown: ahead of pace</text>')
    # the two worked examples from the README, at day 2 (limit 28.6 %)
    # (the shown label sits left of its dot so it stays clear of the rising line)
    for used, fill, label, dx, anchor in ((35, INK, "pace, day 2, 35%: shown", -10, "end"),
                                          (25, DIM, "pace, day 2, 25%: hidden", 10, "start")):
        g.append(f'<circle cx="{x(2)}" cy="{y(used)}" r="4.5" fill="{fill}" stroke="{BG}" stroke-width="1.5"/>')
        g.append(f'<text x="{x(2) + dx}" y="{y(used) + 4}" text-anchor="{anchor}" fill="{fill}">{label}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
            f'font-family="{FONT}" font-size="12.5">\n' + "\n".join(g) + "\n</svg>\n")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    reset_far, reset_near = midnight_in(5), midnight_in(1)
    day2 = NOW + 5 * DAY  # weekly reset 5 days away = 2 days into the week
    scenes = {
        # defaults, early in the week: weekly quota auto-hidden, month total dim
        "default": ({}, payload(23, 41, reset_far)),
        # late in the week: both quotas past 80 % turn amber and show their reset times
        "busy": ({}, payload(86, 84, reset_near, ctx_used=62)),
        # a customised line: effort, percent left, countdowns, every cost item, accent model
        "custom": ({"order": "model,ctx,q5,qwk,sess,wkcost,mo,cwd", "show": "model,ctx,q5,qwk,sess,wkcost,mo",
                    "model.effort": "1", "model.colour": "accent", "ctx.display": "pct", "ctx.measure": "left",
                    "q5.display": "pct", "q5.reset": "countdown", "q5.resetat": "0",
                    "qwk.hide": "off", "qwk.reset": "countdown", "qwk.resetat": "0",
                    "mo.colour": "default", "sess.label": "session"},
                   payload(23, 41, reset_far, sess=3.87)),
        # pace mode on day 2 (limit 28.6 %): under the limit, then ahead of it
        "pace_hidden": ({"qwk.hide": "pace"}, payload(23, 25, day2)),
        "pace_shown": ({"qwk.hide": "pace"}, payload(23, 35, day2)),
    }
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["LOCALAPPDATA"] = tmp
        cs.state_dir().mkdir(parents=True)
        for name, (cfg, pl) in scenes.items():
            reset = json.loads(pl)["rate_limits"]["seven_day"]["resets_at"]
            segs = render(cfg, pl, reset)
            (OUT / f"line_{name}.svg").write_text(terminal_svg(segs), encoding="utf-8", newline="\n")
            print(f"{name:12} " + " | ".join(s["text"] for s in segs))
    (OUT / "weekly_threshold.svg").write_text(threshold_svg(), encoding="utf-8", newline="\n")
    print(f"wrote {len(scenes) + 1} images to {OUT}")


if __name__ == "__main__":
    main()

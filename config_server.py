"""Local config page for the Claude Code status line (statusline.sh).

Written 2026-10-08 for the claude-statusline tool, from the approved mockup
S_Synthesis: a terminal render you drag to reorder (x to hide, a
tray for hidden items) plus a per-item format panel.

The page never formats anything itself. Every preview is rendered by running
the real statusline.sh in preview mode (STATUSLINE_PREVIEW=1) against the last
payload Claude Code sent, so the preview cannot drift from the real line.

    python config_server.py            # or Statusline_Config.bat
    python config_server.py --no-browser

Stdlib only. Binds 127.0.0.1 on an ephemeral port and opens the browser there.
State: %LOCALAPPDATA%\\Tools\\claude_statusline\\ (config.txt, last_payload.json,
totals.txt) -- the same folder statusline.sh uses.
Verified by tests/test_statusline.py and by driving the page in Chrome.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "statusline.sh"
TEMPLATE = HERE / "config_page.html"

# ---- the items and their format controls ---------------------------------------
# Option values are what config.txt and statusline.sh use; labels are for the page.
COLOUR = {"key": "colour", "label": "Colour", "type": "select",
          "options": [["default", "Default"], ["dim", "Dim"], ["accent", "Accent"]]}
PCT = [
    {"key": "measure", "label": "Measure", "type": "select", "options": [["used", "Used"], ["left", "Left"]]},
    {"key": "display", "label": "Display", "type": "select",
     "options": [["pct", "Percent"], ["bar", "Bar"], ["both", "Bar + percent"]]},
    {"key": "colour", "label": "Colour", "type": "select",
     "options": [["threshold", "Threshold"], ["default", "Default"], ["dim", "Dim"], ["accent", "Accent"]]},
    {"key": "warn", "label": "Warn at (used %)", "type": "number", "when": ["colour", "threshold"]},
]
RESET = {"key": "reset", "label": "Reset time", "type": "select",
         "options": [["clock", "Clock time"], ["countdown", "Countdown"], ["hide", "Hide"]]}
RESET_AT = {"key": "resetat", "label": "Show reset from (used %)", "type": "number",
            "when": ["reset", ["clock", "countdown"]]}
HIDE = [
    {"key": "hide", "label": "Hide until", "type": "select",
     "options": [["off", "Always show"], ["fixed", "Fixed % used"], ["pace", "Ahead of pace"]]},
    {"key": "hidefixed", "label": "Show from (used %)", "type": "number", "when": ["hide", "fixed"]},
    {"key": "hidepace", "label": "Pace (% per day since reset)", "type": "number", "decimals": 2,
     "when": ["hide", "pace"], "hint": "14.29 = 1/7 of the week per day"},
]
LABEL = {"key": "label", "label": "Label", "type": "text"}
COST = [
    {"key": "dec", "label": "Decimals", "type": "select", "options": [["0", "Whole dollars"], ["2", "Cents"]]},
    {"key": "sep", "label": "Thousands separator", "type": "toggle"},
    LABEL, COLOUR,
]
ITEMS = [
    {"id": "model", "name": "Model", "desc": "Model name from the Claude Code payload.", "controls": [
        {"key": "style", "label": "Show as", "type": "select",
         "options": [["display", "Display name"], ["short", "Short name"], ["id", "Model id"]]},
        {"key": "effort", "label": "Append effort level", "type": "toggle"}, COLOUR]},
    {"id": "cwd", "name": "Folder", "desc": "Working folder of the session.", "controls": [
        {"key": "path", "label": "Path", "type": "select",
         "options": [["home", "~ shortened"], ["full", "Full path"], ["last2", "Last two folders"], ["name", "Folder name"]]},
        {"key": "max", "label": "Max length", "type": "select",
         "options": [["0", "No limit"], ["20", "20"], ["30", "30"], ["40", "40"]]}, COLOUR]},
    {"id": "ctx", "name": "Context", "desc": "Context window use. The label goes after the value.",
     "controls": [LABEL, *PCT]},
    {"id": "q5", "name": "5-hour quota", "desc": "5-hour limit use, as /usage shows it. Subscription plans only.",
     "controls": [LABEL, *PCT, RESET, RESET_AT]},
    {"id": "qwk", "name": "Weekly quota", "desc": "Weekly limit use, as /usage shows it. Subscription plans only.",
     "controls": [LABEL, *PCT, RESET, RESET_AT, *HIDE]},
    {"id": "mo", "name": "Month total", "desc": "Cost since the first weekly reset of the month (ccusage, refreshed every 5 min).",
     "controls": COST},
    {"id": "wkcost", "name": "Week total", "desc": "Cost since the current weekly reset (ccusage, refreshed every 5 min).",
     "controls": COST},
    {"id": "sess", "name": "Session cost", "desc": "This session's cost from the Claude Code payload.",
     "controls": COST},
]
# Must equal the built-in defaults in statusline.sh (tests/test_statusline.py checks).
DEFAULTS = {
    "order": "model,cwd,ctx,q5,qwk,mo,wkcost,sess",
    "show": "model,cwd,ctx,q5,qwk,mo",
    "model.style": "display", "model.effort": "0", "model.colour": "default",
    "cwd.path": "last2", "cwd.max": "0", "cwd.colour": "default",
    "ctx.label": "ctx", "ctx.measure": "used", "ctx.display": "bar", "ctx.colour": "threshold", "ctx.warn": "80",
    "q5.label": "5h", "q5.measure": "used", "q5.display": "both", "q5.colour": "threshold", "q5.warn": "80",
    "q5.reset": "clock", "q5.resetat": "60",
    "qwk.label": "wk", "qwk.measure": "used", "qwk.display": "pct", "qwk.colour": "threshold", "qwk.warn": "80",
    "qwk.reset": "clock", "qwk.resetat": "60",
    "qwk.hide": "fixed", "qwk.hidefixed": "80", "qwk.hidepace": "14.29",
    "mo.dec": "0", "mo.sep": "1", "mo.label": "mo", "mo.colour": "dim",
    "wkcost.dec": "0", "wkcost.sep": "1", "wkcost.label": "wk", "wkcost.colour": "default",
    "sess.dec": "2", "sess.sep": "1", "sess.label": "sess", "sess.colour": "default",
}
IDS = [i["id"] for i in ITEMS]

# Used for the preview until Claude Code has run the status line once.
SAMPLE_PAYLOAD = {
    "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
    "workspace": {"current_dir": str(Path.home() / "Documents")},
    "effort": {"level": "medium"},
    "cost": {"total_cost_usd": 0.62},
    "context_window": {"used_percentage": 9, "remaining_percentage": 91},
    "rate_limits": {"five_hour": {"used_percentage": 23, "resets_at": 0},
                    "seven_day": {"used_percentage": 54, "resets_at": 0}},
}


def state_dir() -> Path:
    """Same folder statusline.sh resolves; tests point both at a temp LOCALAPPDATA."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Tools" / "claude_statusline"


def find_bash() -> str:
    """Git Bash, never WSL's C:\\Windows\\System32\\bash.exe."""
    for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if Path(p).exists():
            return p
    git = shutil.which("git")
    if git:
        cand = Path(git).resolve().parent.parent / "bin" / "bash.exe"
        if cand.exists():
            return str(cand)
    raise RuntimeError("Git Bash not found; statusline.sh needs it")


# ---- config file ------------------------------------------------------------------
def _allowed(key: str) -> dict | None:
    item, _, ctl = key.partition(".")
    for it in ITEMS:
        if it["id"] == item:
            return next((c for c in it["controls"] if c["key"] == ctl), None)
    return None


def validate(cfg: dict) -> dict:
    """Return a full, clean config (defaults filled in); raise ValueError on bad input."""
    out = dict(DEFAULTS)
    for k, v in cfg.items():
        v = str(v)
        if "\n" in v or "\r" in v:
            raise ValueError(f"{k}: newlines are not allowed")
        if k in ("order", "show"):
            ids = [x for x in v.split(",") if x]
            if any(x not in IDS for x in ids) or len(set(ids)) != len(ids):
                raise ValueError(f"{k}: unknown or repeated item")
            if k == "order":
                ids += [x for x in IDS if x not in ids]  # never lose an item
            out[k] = ",".join(ids)
            continue
        ctl = _allowed(k)
        if ctl is None:
            raise ValueError(f"unknown key {k}")
        if ctl["type"] == "select" and v not in [o[0] for o in ctl["options"]]:
            raise ValueError(f"{k}: {v!r} is not an option")
        if ctl["type"] == "toggle" and v not in ("0", "1"):
            raise ValueError(f"{k}: must be 0 or 1")
        if ctl["type"] == "number":
            dec = ctl.get("decimals", 0)
            whole, dot, frac = v.partition(".")
            frac_ok = (frac.isdigit() and len(frac) <= dec) if dot else True
            if not (whole.isdigit() and frac_ok and float(v) <= 100):
                raise ValueError(f"{k}: must be 0-100" + (f" with up to {dec} decimals" if dec else ""))
        out[k] = v.strip() if ctl["type"] == "text" else v
    return out


def read_config(path: Path | None = None) -> dict:
    path = path or state_dir() / "config.txt"
    cfg = dict(DEFAULTS)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k in DEFAULTS:
                    cfg[k] = v
    return cfg


def format_config(cfg: dict) -> str:
    lines = ["# Claude Code status line config -- written by config_server.py; read by statusline.sh"]
    lines += [f"{k}={cfg[k]}" for k in DEFAULTS]
    return "\n".join(lines) + "\n"


def write_config(cfg: dict, path: Path | None = None) -> Path:
    path = path or state_dir() / "config.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(format_config(cfg), encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path


# ---- preview: run the real script -------------------------------------------------
def payload_text() -> str:
    p = state_dir() / "last_payload.json"
    if p.exists() and p.stat().st_size:
        return p.read_text(encoding="utf-8", errors="replace")
    import time
    s = json.loads(json.dumps(SAMPLE_PAYLOAD))
    s["rate_limits"]["five_hour"]["resets_at"] = int(time.time()) + 2 * 3600 + 600
    s["rate_limits"]["seven_day"]["resets_at"] = int(time.time()) + 2 * 86400 + 13 * 3600
    return json.dumps(s)


def render_preview(cfg: dict, payload: str | None = None) -> list[dict]:
    """Every item's text and colour, rendered by statusline.sh under `cfg`."""
    sd = state_dir()
    sd.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="preview_", suffix=".txt", dir=sd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(format_config(cfg))
        env = dict(os.environ, STATUSLINE_PREVIEW="1", STATUSLINE_CONFIG=tmp)
        res = subprocess.run([find_bash(), str(SCRIPT)], input=(payload or payload_text()).encode("utf-8"),
                             capture_output=True, env=env, timeout=20)
    finally:
        os.unlink(tmp)
    segs = []
    for line in res.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            segs.append({"id": parts[0], "colour": parts[1], "text": parts[2]})
    return segs


# ---- page + server ------------------------------------------------------------------
def build_page() -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__ITEMS__", json.dumps(ITEMS)).replace("__DEFAULTS__", json.dumps(DEFAULTS))
    # optional: inline a house stylesheet if one is installed; otherwise the
    # page's own neutral fallback tokens apply
    brand = Path(os.environ.get("STATUSLINE_HOUSE_DIR", r"C:\Tools\brand"))
    if (brand / "house_inline.py").exists():
        sys.path.insert(0, str(brand))
        from house_inline import inline_into  # noqa: PLC0415
        html = inline_into(html)
    return html


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode("utf-8"))

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            # built per request, so a template edit needs only a browser refresh
            self._send(200, build_page().encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/api/config":
            self._json(read_config())
        else:
            self._send(404, b"{}")

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            cfg = validate(body)
        except (ValueError, json.JSONDecodeError) as e:
            return self._json({"error": str(e)}, 400)
        if self.path == "/api/preview":
            try:
                self._json({"segments": render_preview(cfg)})
            except (RuntimeError, subprocess.TimeoutExpired) as e:
                self._json({"error": str(e)}, 500)
        elif self.path == "/api/save":
            path = write_config(cfg)
            self._json({"saved": str(path), "config": cfg})
        else:
            self._send(404, b"{}")


def main() -> None:
    build_page()  # fail fast on a broken template
    srv =ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Status line config: {url}  (Ctrl+C or close this window to stop)", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.3, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

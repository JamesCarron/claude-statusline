"""Tests for statusline.sh and config_server.py.

Written 2026-10-08 for the claude-statusline tool. Runs the real bash script
against a synthetic payload inside a temp LOCALAPPDATA holding a fresh totals
cache, so no ccusage run is triggered. Stdlib only:

    python -m unittest discover -s tests -v      (from the statusline folder)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import config_server as cs  # noqa: E402

HOME = os.environ.get("USERPROFILE", str(Path.home()))
CWD = HOME + "\\Documents"
NOW = int(time.time())
R5 = NOW + 2 * 3600 + 10 * 60 + 30   # 5-hour reset in 2h 10m
RWK = NOW + 2 * 86400 + 13 * 3600 + 30  # weekly reset in 2d 13h
PAYLOAD = json.dumps({
    "session_id": "s-1", "prompt_id": "p-1",
    "model": {"id": "claude-opus-5-5", "display_name": "Opus 5.5"},
    "workspace": {"current_dir": CWD},
    "effort": {"level": "medium"},
    "cost": {"total_cost_usd": 0.62},
    "context_window": {"current_usage": {"input_tokens": 2}, "used_percentage": 9, "remaining_percentage": 91},
    "rate_limits": {"five_hour": {"used_percentage": 23, "resets_at": R5},
                    "seven_day": {"used_percentage": 54, "resets_at": RWK}},
})


def windows(reset: int) -> tuple[str, str]:
    """Python mirror of the script's week/month window maths."""
    t = reset - 604800 + 43200
    wk = time.strftime("%Y%m%d", time.localtime(t))
    while time.localtime(t).tm_mday > 7:
        t -= 604800
    return time.strftime("%Y%m%d", time.localtime(t)), wk


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp.name
        self.sd = cs.state_dir()
        self.sd.mkdir(parents=True)
        mo, wk = windows(RWK)
        (self.sd / "totals.txt").write_text(f"{mo} {wk} {NOW + 3600} 384.23 1247.83\n", newline="\n")
        (self.sd / "last_payload.json").write_text(PAYLOAD)

    def tearDown(self):
        if self.env_old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.env_old
        self.tmp.cleanup()

    # the percent threshold (default 60) would hide every test value; tests of
    # other options switch it off, and test_percent_threshold covers it
    NOPCT = {"ctx.pctat": "0", "q5.pctat": "0", "qwk.pctat": "0"}

    def line(self, cfg: dict | None = None) -> str:
        env = dict(os.environ)
        if cfg is not None:
            path = self.sd / "t_config.txt"
            cs.write_config(cs.validate({**self.NOPCT, **cfg}), path)
            env["STATUSLINE_CONFIG"] = str(path)
        r = subprocess.run([cs.find_bash(), str(cs.SCRIPT)], input=PAYLOAD.encode(), capture_output=True, env=env)
        return r.stdout.decode("utf-8")

    def seg(self, overrides: dict, item: str) -> dict:
        return {s["id"]: s for s in cs.render_preview(cs.validate({**self.NOPCT, **overrides}), PAYLOAD)}[item]


class Parity(Base):
    def test_bash_defaults_equal_python_defaults(self):
        # no config file at all vs. a config file holding config_server.DEFAULTS
        self.assertEqual(self.line(), self.line(dict(cs.DEFAULTS)))
        env = dict(os.environ, STATUSLINE_PREVIEW="1")
        bare = subprocess.run([cs.find_bash(), str(cs.SCRIPT)], input=PAYLOAD.encode(), capture_output=True, env=env)
        prev = "".join(f"{s['id']}\t{s['colour']}\t{s['text']}\n" for s in cs.render_preview(dict(cs.DEFAULTS), PAYLOAD))
        self.assertEqual(bare.stdout.decode("utf-8"), prev)

    def test_default_line(self):
        # 23% is below the default 60% reset threshold, so no reset time; the
        # weekly quota (54%) is under the default fixed 80% "show from", so hidden
        self.assertEqual(self.line(), "Opus 5.5 | " + HOME.rsplit("\\", 1)[-1] + "\\Documents | █░░░░░░░ ctx"
                         " | 5h ██░░░░░░ 23% | \x1b[2m$1,248 mo\x1b[0m")

    def test_percent_threshold(self):
        bar = "█░░░░░░░"  # 9% used
        for over, want in [({"ctx.pctat": "9"}, "91% ctx"),
                           ({"ctx.pctat": "10"}, None),                       # pct only: hidden
                           ({"ctx.display": "both", "ctx.measure": "used", "ctx.pctat": "10"}, f"{bar} ctx"),
                           ({"ctx.display": "both", "ctx.measure": "used", "ctx.pctat": "9"}, f"{bar} 9% used ctx"),
                           ({"ctx.display": "bar", "ctx.measure": "used", "ctx.pctat": "100"}, f"{bar} ctx")]:
            with self.subTest(over=over):
                self.assertEqual(self.line({"show": "ctx", "ctx.measure": "left", "ctx.display": "pct", **over}), want or "")
        self.assertEqual(self.line({"show": "q5", "q5.display": "pct", "q5.pctat": "24"}), "")
        self.assertEqual(self.line({"show": "q5", "q5.display": "pct", "q5.pctat": "23"}), "5h 23%")

    def test_reset_threshold(self):
        rwk = time.strftime("%a %H:%M", time.localtime(RWK))
        self.assertEqual(self.line({"show": "qwk", "qwk.hide": "off", "qwk.resetat": "54"}), f"wk 54% ({rwk})")
        self.assertEqual(self.line({"show": "qwk", "qwk.hide": "off", "qwk.resetat": "55"}), "wk 54%")

    def test_weekly_auto_hide(self):
        for over, shown in [({"qwk.hide": "off"}, True),
                            ({"qwk.hide": "fixed", "qwk.hidefixed": "54"}, True),
                            ({"qwk.hide": "fixed", "qwk.hidefixed": "55"}, False),
                            ({"qwk.hide": "pace", "qwk.hidepace": "12"}, True),     # 12 x 4.46 d = 53.5% <= 54%
                            ({"qwk.hide": "pace", "qwk.hidepace": "12.2"}, False),  # 54.4% > 54%
                            ({"qwk.hide": "pace"}, False),                          # 14.29 %/day
                            ({}, False)]:                         # default: fixed, shown from 80%
            with self.subTest(over=over):
                self.assertEqual(self.line({"show": "qwk", **over}) == "wk 54%", shown)
                self.assertEqual(self.seg(over, "qwk")["colour"] == "hidden", not shown)

    def test_order_and_show(self):
        out = self.line({"order": "mo,model,cwd,ctx,q5,qwk,wkcost,sess", "show": "mo,model,sess", "mo.colour": "default"})
        self.assertEqual(out, "$1,248 mo | Opus 5.5 | $0.62 sess")

    def test_threshold_colour_is_ansi(self):
        self.assertEqual(self.line({"show": "qwk", "qwk.hide": "off", "qwk.warn": "50"}), "\x1b[33mwk 54%\x1b[0m")


class Formats(Base):
    CASES = [
        ({"model.style": "short"}, "model", "Opus"),
        ({"model.style": "id"}, "model", "claude-opus-5-5"),
        ({"model.effort": "1"}, "model", "Opus 5.5 · medium"),
        ({"cwd.path": "full"}, "cwd", CWD),
        ({"cwd.path": "name"}, "cwd", "Documents"),
        ({"cwd.path": "last2"}, "cwd", HOME.rsplit("\\", 1)[-1] + "\\Documents"),
        ({"cwd.path": "full", "cwd.max": "20"}, "cwd", "…" + CWD[-19:]),
        ({"ctx.display": "pct"}, "ctx", "9% used ctx"),
        ({"ctx.measure": "left", "ctx.display": "pct"}, "ctx", "91% ctx"),
        ({"ctx.measure": "left"}, "ctx", "███████░ ctx"),
        ({}, "ctx", "█░░░░░░░ ctx"),
        ({"ctx.display": "both", "ctx.label": ""}, "ctx", "█░░░░░░░ 9% used"),
        ({"q5.display": "pct", "q5.reset": "countdown", "q5.resetat": "0"}, "q5", "5h 23% (in 2h 10m)"),
        ({"q5.display": "pct", "q5.reset": "countdown"}, "q5", "5h 23%"),
        ({"q5.display": "pct", "q5.reset": "hide", "q5.measure": "left", "q5.resetat": "0"}, "q5", "5h 77% left"),
        ({}, "q5", "5h ██░░░░░░ 23%"),
        ({"qwk.reset": "countdown", "qwk.label": "week", "qwk.resetat": "0"}, "qwk", "week 54% (in 2d 13h)"),
        ({"qwk.resetat": "50"}, "qwk", "wk 54% (" + time.strftime("%a %H:%M", time.localtime(RWK)) + ")"),
        ({"mo.dec": "2"}, "mo", "$1,247.83 mo"),
        ({"mo.sep": "0"}, "mo", "$1248 mo"),
        ({"mo.label": ""}, "mo", "$1,248"),
        ({}, "wkcost", "$384 wk"),
        ({"sess.dec": "0"}, "sess", "$1 sess"),
    ]

    def test_formats(self):
        for overrides, item, want in self.CASES:
            with self.subTest(overrides=overrides):
                self.assertEqual(self.seg(overrides, item)["text"], want)

    def test_colours(self):
        self.assertEqual(self.seg({"model.colour": "dim"}, "model")["colour"], "dim")
        self.assertEqual(self.seg({"mo.colour": "accent"}, "mo")["colour"], "accent")
        self.assertEqual(self.seg({"qwk.hide": "off", "qwk.warn": "50"}, "qwk")["colour"], "warn")
        self.assertEqual(self.seg({"qwk.hide": "off"}, "qwk")["colour"], "")


class Simulate(Base):
    def test_current_usage(self):
        u = cs.current_usage(PAYLOAD)
        self.assertEqual({k: u[k] for k in ("ctx", "q5", "qwk", "reset")}, {"ctx": 9, "q5": 23, "qwk": 54, "reset": RWK})
        self.assertAlmostEqual(u["days"], 7 - (RWK - time.time()) / 86400, places=1)
        self.assertEqual(cs.current_usage(json.dumps({"model": {}})),
                         {"ctx": None, "q5": None, "qwk": None, "reset": None, "days": None})

    def test_days_moves_the_clock_not_the_reset(self):
        p, now = cs.simulate(PAYLOAD, {"days": 2.5})
        self.assertEqual(now, RWK - 604800 + 216000)
        self.assertEqual(p, cs.simulate(PAYLOAD, {})[0])
        self.assertIsNone(cs.simulate(json.dumps({"model": {}}), {"days": 3})[1])

    def test_simulated_values_reach_the_line(self):
        p, _ = cs.simulate(PAYLOAD, {"ctx": 70, "q5": 65, "qwk": 61})
        self.assertEqual({k: v for k, v in cs.current_usage(p).items() if k in cs.SIM}, {"ctx": 70, "q5": 65, "qwk": 61})
        self.assertIn(f'"resets_at": {RWK}', p)  # windows untouched
        segs = {s["id"]: s for s in cs.render_preview(cs.validate({"ctx.measure": "left", "ctx.display": "pct", "q5.display": "pct"}), p)}
        self.assertEqual(segs["ctx"]["text"], "30% ctx")
        self.assertEqual(segs["q5"]["text"], "5h 65% (" + time.strftime("%H:%M", time.localtime(R5)) + ")")

    def test_rejects_bad_sim(self):
        for bad in ({"ctx": 101}, {"ctx": -1}, {"ctx": "50"}, {"ctx": True}, {"mo": 5}, {"days": 8}, {"days": "1"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                cs.simulate(PAYLOAD, bad)

    def test_pace_modes(self):
        # a week resetting Sun 00:00 local, seen at Thu 18:00 (4.75 days in), pace 20 %/day
        reset = int(time.mktime((2026, 10, 18, 0, 0, 0, 0, 0, -1)))
        p = json.loads(PAYLOAD)
        p["rate_limits"]["seven_day"]["resets_at"] = reset
        now = reset - 604800 + 4 * 86400 + 18 * 3600
        for days, unit, want, counted in [("all", "continuous", "95.00", "475 475"),     # 4.75 d
                                          ("all", "whole", "80.00", "475 400"),          # Sun-Wed
                                          ("weekdays", "continuous", "75.00", "375 375"),  # Mon-Wed + 0.75 Thu
                                          ("weekdays", "whole", "60.00", "375 300")]:    # Mon-Wed
            with self.subTest(days=days, unit=unit):
                segs = {s["id"]: s for s in cs.render_preview(
                    cs.validate({"qwk.hide": "pace", "qwk.hidepace": "20", "qwk.pacedays": days, "qwk.paceunit": unit}), json.dumps(p), now)}
                self.assertEqual(segs["qwk.thr"]["text"], want)
                self.assertEqual(segs["qwk.days"]["text"], counted)
                self.assertEqual(segs["qwk"]["colour"] == "hidden", 54 < float(want))


class Validate(unittest.TestCase):
    def test_rejects_bad_values(self):
        for bad in ({"model.style": "huge"}, {"ctx.warn": "200"}, {"nope.x": "1"},
                    {"mo.label": "a\nb"}, {"show": "model,model"}, {"order": "model,zzz"},
                    {"qwk.hidepace": "14.295"}, {"qwk.hidepace": "14."}, {"qwk.hidefixed": "1.5"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                cs.validate(bad)

    def test_order_never_loses_items(self):
        self.assertEqual(cs.validate({"order": "mo"})["order"].split(","), ["mo"] + [i for i in cs.IDS if i != "mo"])


if __name__ == "__main__":
    unittest.main()

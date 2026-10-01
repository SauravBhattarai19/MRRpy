# -*- coding: utf-8 -*-
"""
wizard.py
=========
``MRRpy wizard`` — build a configuration by answering questions.

It uses plain ``input()`` / ``print()`` only (no colours, cursor movement or
box-drawing characters), so it works over SSH, inside Jupyter, in any
terminal, and with screen readers.  Every question shows its current value
in [brackets] and pressing Enter keeps it, so a first run can be finished by
pressing Enter on everything that doesn't matter.

At any question:  ?  more help · back  previous question · done  skip to the
end · quit  stop.

Only the questions that matter for your earlier answers are asked (e.g. the
gauge files only for gauge rainfall), basic questions first; each part then
offers its advanced settings, which most people leave alone.
"""

import builtins
import contextlib
import copy
import glob
import json
import os
import shutil
import textwrap

from .. import config_schema as S
from ..config import Config
from . import render


class _Back(Exception):
    pass


class _Done(Exception):
    pass


class _Quit(Exception):
    pass


_TYPE_HINTS = {
    "latlon": "Type latitude, longitude — e.g. 27.6322, 85.2933",
    "bbox": "Type west, south, east, north in degrees — e.g. 85.1, 27.5, 85.6, 27.9",
    "datetime": "Type a date and time as YYYY-MM-DD HH:MM — e.g. 2024-09-27 06:00",
    "multichoice": "Type the numbers or names you want, separated by commas — e.g. 0, 2",
    "order_table": "Type one value per stream order, starting at order 1 — e.g. 3, 5, 8, 12",
    "elev_table": "Type 'upper elevation: n' bands from low to high — e.g. 1500: 0.06, 9000: 0.04",
    "hg_coeffs": "Type the four coefficients w_a, w_b, d_a, d_b — e.g. 2.7, 0.352, 0.3, 0.213",
    "crs": "Type an EPSG code — e.g. EPSG:32645 or just 32645",
    "bool": "Type yes or no",
}

_INTRO = """\
MRRpy configuration wizard

Answer each question and press Enter.  Pressing Enter on its own keeps the
value shown in [brackets], so you only need to answer what matters to you.

At any question you can type:
  ?      more help on that question
  back   go back to the previous question
  done   skip the remaining questions (they keep their current values)
  quit   stop without saving
"""


class Wizard:
    """
    The question-and-answer engine.  ``Wizard(...).run()`` returns the edited
    Config (or None if the user quit).  ``run_wizard`` adds saving.

    input_fn / print_fn default to the builtins; tests pass scripted ones.
    """

    def __init__(self, config=None, ask_all=False, starting_point=None,
                 input_fn=None, print_fn=None, show_help=True):
        self.cfg = copy.deepcopy(config) if config is not None else Config()
        self.editing = config is not None
        self.ask_all = ask_all
        self.starting_point = starting_point
        self.show_help = show_help
        self._in = input_fn or builtins.input
        self._out = print_fn or builtins.print
        self.asked = set()        # params answered (or kept) in this session
        self.history = []         # ("param"|"gate", name/section, phase index)
        self.opened = set()       # sections whose advanced settings were opened
        self.gated = set()        # sections whose "advanced?" question was answered
        self.focus = set()        # advanced params a starting point promotes
        self._last_section = None
        self._catchup_said = False
        self.phases = []
        for sec in S.SECTIONS:
            self.phases += [("basic", sec.key), ("gate", sec.key), ("rest", sec.key)]
        self.phases.append(("catchup", None))
        try:
            self._width = min(shutil.get_terminal_size((88, 24)).columns, 100) - 1
        except (OSError, ValueError):
            self._width = 87

    # ── Output helpers ────────────────────────────────────────────────────────
    def say(self, text="", indent="", hang=None):
        """Print wrapped text; *hang* is the indent of continuation lines."""
        if not text:
            self._out("")
            return
        hang = (" " * len(indent)) if hang is None else hang
        for para in str(text).split("\n"):
            wrapped = textwrap.wrap(para, self._width, initial_indent=indent,
                                    subsequent_indent=hang, break_on_hyphens=False,
                                    break_long_words=False)
            for line in wrapped or [""]:
                self._out(line)

    def _read(self, prompt, completion=False):
        """input() with the wizard commands; returns the raw text or None for help."""
        with self._path_completion(completion):
            try:
                raw = self._in(prompt)
            except EOFError:
                raise _Quit("eof") from None
            except KeyboardInterrupt:
                raise _Quit("interrupt") from None
        word = raw.strip().lower()
        if word in ("?", "help"):
            return None
        if word in ("back", "<"):
            raise _Back()
        if word == "done":
            raise _Done()
        if word in ("quit", "exit"):
            raise _Quit("quit")
        return raw

    @contextlib.contextmanager
    def _path_completion(self, enabled):
        """Tab-completion of file names while a path question is open (real terminals only)."""
        if not enabled or self._in is not builtins.input:
            yield
            return
        try:
            import readline
        except ImportError:
            yield
            return
        old, delims = readline.get_completer(), readline.get_completer_delims()

        def complete(text, state):
            hits = [h + ("/" if os.path.isdir(h) else "")
                    for h in sorted(glob.glob(os.path.expanduser(text) + "*"))]
            return hits[state] if state < len(hits) else None

        try:
            readline.set_completer_delims(" \t\n;")
            if "libedit" in (readline.__doc__ or ""):
                readline.parse_and_bind("bind ^I rl_complete")
            else:
                readline.parse_and_bind("tab: complete")
            readline.set_completer(complete)
            yield
        finally:
            readline.set_completer(old)
            readline.set_completer_delims(delims)

    def yes_no(self, question, default=False):
        hint = "yes" if default else "no"
        while True:
            raw = self._read(f"{question} [{hint}]: ")
            if raw is None:
                self.say("Type yes or no (or press Enter for the answer in brackets).", "  ")
                continue
            word = raw.strip().lower()
            if not word:
                return default
            if word in ("y", "yes"):
                return True
            if word in ("n", "no"):
                return False
            self.say("Please type yes or no.", "  ")

    # ── Flow ──────────────────────────────────────────────────────────────────
    def _in_scope(self, p):
        return (p.level == "basic" or self.ask_all or p.name in self.focus
                or p.section in self.opened)

    def _pending_advanced(self, sec, values):
        return [p for p in S.PARAMS
                if p.section == sec and p.level == "advanced" and p.name not in self.asked
                and p.name not in self.focus and S.is_visible(p, values)]

    def _next(self, start):
        """(phase index, 'param'|'gate', Param|section) of the next question, or None."""
        values = S.values_of(self.cfg)
        for i in range(start, len(self.phases)):
            kind, sec = self.phases[i]
            if kind == "gate":
                if not self.ask_all and sec not in self.gated and self._pending_advanced(sec, values):
                    return i, "gate", sec
                continue
            for p in S.PARAMS:
                if p.name in self.asked or (sec is not None and p.section != sec):
                    continue
                if kind == "basic" and not (p.level == "basic" or p.name in self.focus
                                            or self.ask_all):
                    continue
                if kind != "basic" and not self._in_scope(p):
                    continue
                if S.is_visible(p, values):
                    return i, "param", p
        return None

    def ask_starting_point(self):
        sp_param = S.Param("START", "project", "Starting point", "", "choice",
                           choices=[s.key for s in S.STARTING_POINTS],
                           choice_labels={s.key: s.label for s in S.STARTING_POINTS})
        self.say()
        self.say("What would you like to simulate?  This only pre-selects a few "
                 "settings; you can change everything afterwards.")
        key = self._ask_value(sp_param, "design_storm", show_help=False,
                              prompt_label="Starting point")
        self._apply_starting_point(key)

    def _apply_starting_point(self, key):
        sp = S.STARTING_POINT_BY_KEY[key]
        for name, value in S.apply_starting_point(self.cfg, key):
            self.say(f"This sets {name} = {S.format_value(S.param(name), value)}.", "  ")
        self.focus.update(sp.focus)

    def ask_questions(self):
        """Ask every relevant question; returns when done (or 'done' was typed)."""
        phase, forced = 0, None
        while True:
            if forced is not None:
                phase, kind, obj = forced
                forced = None
            else:
                nxt = self._next(phase)
                if nxt is None:
                    return
                phase, kind, obj = nxt
            try:
                if kind == "param":
                    if self.phases[phase][0] == "catchup" and not self._catchup_said:
                        self._catchup_said = True
                        self.say()
                        self.say("Because of later answers, a few earlier questions now apply:")
                    self._section_header(obj.section)
                    self.ask_param(obj)
                    self.asked.add(obj.name)
                    self.history.append(("param", obj.name, phase))
                else:
                    self._ask_gate(obj)
                    self.history.append(("gate", obj, phase))
            except _Back:
                if not self.history:
                    self.say("This is the first question.", "  ")
                    forced = (phase, kind, obj)
                    continue
                hkind, name, hphase = self.history.pop()
                if hkind == "param":
                    self.asked.discard(name)
                    forced = (hphase, "param", S.param(name))
                else:
                    self.gated.discard(name)
                    self.opened.discard(name)
                    forced = (hphase, "gate", name)
            except _Done:
                return

    def _section_header(self, key):
        if key == self._last_section:
            return
        self._last_section = key
        sec = S.SECTION_BY_KEY[key]
        n = S.SECTIONS.index(sec) + 1
        self.say()
        self.say(f"Part {n} of {len(S.SECTIONS)}: {sec.title}")
        self.say(sec.intro)

    def _ask_gate(self, sec):
        pending = self._pending_advanced(sec, S.values_of(self.cfg))
        title = S.SECTION_BY_KEY[sec].title
        self.say()
        names = "; ".join(p.label for p in pending[:4])
        more = ", …" if len(pending) > 4 else ""
        self.say(f"{title} has {len(pending)} advanced setting"
                 f"{'s' if len(pending) != 1 else ''} ({names}{more}).  Most people "
                 "keep their defaults.")
        answer = self.yes_no(f"Review the advanced settings for {title}?", False)
        self.gated.add(sec)
        if answer:
            self.opened.add(sec)

    # ── Questions ─────────────────────────────────────────────────────────────
    def ask_param(self, p):
        """Ask one parameter and store the answer on self.cfg."""
        if p.kind in ("qbf", "channel_n", "hg"):
            value = self._ask_composite(p)
        elif p.kind == "points":
            value = self._ask_points(p)
        else:
            value = self._ask_value(p, getattr(self.cfg, p.name))
        setattr(self.cfg, p.name, value)
        if p.name == "OUTPUT_DIR":
            self.cfg.update_output_paths()

    def _show_help(self, p, detail=False):
        if detail:
            self.say()
            self.say(render.explain_param(p) if p.name in S.PARAM_BY_NAME
                     and S.PARAM_BY_NAME[p.name] is p else p.help, "  ")
        elif self.show_help and p.help:
            self.say(p.help, "  ")
        hint = _TYPE_HINTS.get(p.kind)
        if hint:
            self.say(hint + ".", "  ")
        if p.optional and p.none_label and detail:
            self.say(f"Type 'none' for: {p.none_label}.", "  ")
        if p.kind == "file" and detail and self._in is builtins.input:
            self.say("The Tab key completes file and folder names.", "  ")

    def _show_choices(self, p, current):
        for i, (value, label) in enumerate(S.choices_for(p)):
            if p.kind == "multichoice":
                mark = "  (selected)" if value in (current or []) else ""
            else:
                mark = "  (current)" if value == current else ""
            self.say(f"{i:>2}  {label}{mark}", "    ", hang=" " * 8)

    def _shown(self, p, value):
        if value is None or value == "":
            return p.none_label or "empty"
        if p.kind == "choice":
            codes = [c for c, _ in S.choices_for(p)]
            return f"{codes.index(value)} {value}" if value in codes else str(value)
        return S.format_value(p, value)

    def _ask_value(self, p, current, show_help=True, prompt_label=None, extra=None):
        """Ask for one value of *p* (Enter keeps *current*); returns the new value."""
        default = current
        if p.kind == "crs":
            suggestion, why = S.suggest_crs(S.values_of(self.cfg))
            untouched = (not self.editing and current == Config.TARGET_CRS_EPSG)
            if suggestion and suggestion != current:
                if untouched:
                    default = suggestion
                    self.say(f"Suggested: {suggestion} ({why}).", "  ")
                else:
                    self.say(f"Tip: {suggestion} is {why}.", "  ")
        self.say()
        if show_help:
            self._show_help(p)
        if extra:
            self.say(extra, "  ")
        if p.kind in ("choice", "multichoice"):
            self._show_choices(p, current)
        label = prompt_label or p.title
        while True:
            raw = self._read(f"{label} [{self._shown(p, default)}]: ",
                             completion=p.kind in ("file", "folder"))
            if raw is None:
                self._show_help(p, detail=True)
                if p.kind in ("choice", "multichoice"):
                    self._show_choices(p, current)
                continue
            if raw.strip() == "":
                if default is None and not p.optional and p.kind not in ("choice",):
                    self.say(f"{p.label} needs a value.", "  ")
                    continue
                if default is not current or p.kind not in ("file",):
                    return default
                value = default
            else:
                try:
                    value = S.parse_value(p, raw)
                except ValueError as exc:
                    self.say(f"Sorry — {exc}", "  ")
                    continue
            if p.kind == "file" and value and isinstance(value, str) and not os.path.exists(value):
                self.say(f"I can't find {value!r} (looking from {os.getcwd()}).", "  ")
                if not self.yes_no("Use it anyway?", False):
                    continue
            return value

    def _ask_composite(self, p):
        current = getattr(self.cfg, p.name)
        cur_mode, cur_sub = S.split_composite(p, current)
        modes = S.modes_for(p, current)
        mode_param = S.Param(p.name, p.section, p.label, p.help, "choice",
                             choices=[m.key for m in modes],
                             choice_labels={m.key: f"{m.key} — {m.label[0].lower()}{m.label[1:]}"
                                            for m in modes})
        while True:
            mode = self._ask_value(mode_param, cur_mode, prompt_label=p.title)
            m = next(x for x in modes if x.key == mode)
            if m.sub is None:
                return current if mode == "custom" else S.join_composite(p, mode, None)
            extra = None
            if p.kind == "qbf" and mode == "formula":
                from ..core.routing.qbf import describe_presets
                extra = ("Presets you can type by name:\n" + describe_presets()
                         + "\nVariables: A drainage area [km²], A_below(z)/A_above(z) area "
                           "below/above elevation z [km²], H mean elevation [m], P mean "
                           "annual rain [mm, needs Earth Engine].")
            try:
                sub = self._ask_value(m.sub, cur_sub if mode == cur_mode else None,
                                      show_help=False, prompt_label=m.sub.title, extra=extra)
            except _Back:
                continue                                  # back to the mode question
            return S.join_composite(p, mode, sub)

    def _ask_points(self, p):
        current = getattr(self.cfg, p.name)
        layout = "name, latitude, longitude" + (", hydrograph CSV" if p.needs_csv else "")
        self.say()
        if self.show_help:
            self.say(p.help, "  ")
        self.say(f"Type one point per line as: {layout}.  An empty line finishes.", "  ")
        if current:
            self.say(f"Current ({len(current)}):", "  ")
            for line in S.format_value(p, current).splitlines():
                self.say(line, "    ")
            self.say("Press Enter to keep them, or type 'none' to remove them all.", "  ")
        while True:
            first = self._read(f"{p.label}, point 1 [{'keep' if current else 'none'}]: ")
            if first is None:
                self._show_help(p, detail=True)
                continue
            if not first.strip():
                return current
            if first.strip().lower() in ("none", "-"):
                return None
            lines = [first]
            while True:
                try:
                    with self._path_completion(p.needs_csv):
                        nxt = self._in(f"{p.label}, point {len(lines) + 1} (Enter to finish): ")
                except (EOFError, KeyboardInterrupt):
                    raise _Quit("eof") from None
                if not nxt.strip():
                    break
                lines.append(nxt)
            try:
                value = S.parse_value(p, "\n".join(lines))
            except ValueError as exc:
                self.say(f"Sorry — {exc}  Please type the points again.", "  ")
                continue
            missing = [pt["csv"] for pt in value or [] if pt.get("csv")
                       and not os.path.exists(pt["csv"])]
            if missing:
                self.say(f"I can't find {', '.join(missing)}.", "  ")
                if not self.yes_no("Use them anyway?", False):
                    continue
            return value

    # ── Review ────────────────────────────────────────────────────────────────
    def review(self):
        """Summarise, check, and offer to fix problems.  True when no problems remain."""
        self.say()
        self.say("Review")
        self.say("Here is what this configuration will do:")
        for line in render.describe_run(self.cfg):
            self.say(line, "  - ", hang="    ")
        if any(req for _w, req in S.earth_engine_uses(S.values_of(self.cfg))):
            project = self.cfg.GEE_PROJECT or os.environ.get("GEE_PROJECT") or "<your-project>"
            self.say()
            self.say("These choices use Google Earth Engine. If this computer has never "
                     "signed in, do it once (it prints a link and asks for a code):")
            self._out(f"    MRRpy earth-engine-login --project {project}")
        while True:
            probs = S.problems(self.cfg)
            self.say()
            if not probs:
                self.say("Checked: no problems found.")
                return True
            self.say(f"Found {len(probs)} problem{'s' if len(probs) > 1 else ''}:")
            for i, msg in enumerate(probs, 1):
                self.say(f"{i}. {msg}", "  ", hang="     ")
            names = []
            for msg in probs:
                names += [n for n in S.params_in_message(msg) if n not in names]
            try:
                fix = bool(names) and self.yes_no("Fix them now?", True)
            except (_Back, _Done):
                fix = False
            if not fix:
                return False
            before = S.values_of(self.cfg)
            for name in names:
                p = S.param(name)
                if not S.is_visible(p, S.values_of(self.cfg)):
                    continue
                try:
                    self.ask_param(p)
                except _Back:
                    continue
                except _Done:
                    break
            if all(S._same(before[k], v) for k, v in S.values_of(self.cfg).items()):
                self.say()
                self.say("Nothing was changed, so the problem is still there.")
                return False

    def run(self):
        """Intro, starting point, questions.  Returns the Config, or None on quit."""
        try:
            self.say(_INTRO)
            if self.editing:
                self.say("Editing an existing configuration: its values are the "
                         "defaults in [brackets].")
            elif self.starting_point:
                self._apply_starting_point(self.starting_point)
            else:
                while True:
                    try:
                        self.ask_starting_point()
                        break
                    except _Back:
                        self.say("This is the first question.", "  ")
                    except _Done:
                        return self.cfg
            self.ask_questions()
            return self.cfg
        except _Quit:
            return None


def _answer(wiz, question, default):
    """yes_no where 'back'/'done' simply mean 'take the default'."""
    try:
        return wiz.yes_no(question, default)
    except (_Back, _Done):
        return default


def _default_name(output, edit_path):
    return output or edit_path or "run.yaml"


def _save(cfg, path, write_all, source):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        data = {}
        for p in S.PARAMS:
            try:
                data[p.name] = render.plain(getattr(cfg, p.name))
            except render.Unrepresentable:
                pass
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return path
    return render.save_yaml(cfg, path, full=write_all, source=source)


def run_wizard(config=None, output=None, ask_all=False, write_all=False,
               starting_point=None, save=True, offer_run=False, show_help=True,
               input_fn=None, print_fn=None):
    """
    Build or edit a configuration by answering questions.

    Parameters
    ----------
    config : Config, path, or None
        Start from this Config or config file (``--edit``); None = defaults.
    output : str, optional
        File to save to (asked, with this as the default).  ``.yaml`` or ``.json``.
    ask_all : bool
        Ask every relevant question, advanced ones included.
    write_all : bool
        Save every setting (a long reference file) instead of only the ones
        that matter for these choices.
    starting_point : str, optional
        Skip the first question; one of ``config_schema.STARTING_POINT_BY_KEY``.
    save : bool
        Ask where to save and write the file (False just returns the Config).
    offer_run : bool
        After saving, offer to run the model straight away.
    show_help : bool
        Print the one-line explanation above each question.

    Returns
    -------
    Config, or None if the user quit.
    """
    edit_path = None
    if isinstance(config, (str, os.PathLike)):
        edit_path = os.fspath(config)
        config = Config.from_file(edit_path)
    wiz = Wizard(config, ask_all=ask_all, starting_point=starting_point,
                 input_fn=input_fn, print_fn=print_fn, show_help=show_help)
    cfg = wiz.run()
    if cfg is None:
        wiz.say()
        wiz.say("Stopped — nothing was saved.")
        return None
    try:
        ok = wiz.review()
        if not ok and save and not _answer(wiz, 
                "Save anyway?  You can fix the file later (MRRpy wizard --edit <file>).", True):
            wiz.say("Nothing was saved.")
            return cfg
        if save:
            default = _default_name(output, edit_path)
            while True:
                try:
                    raw = wiz._read(f"Save the configuration as [{default}]: ", completion=True)
                except (_Back, _Done):
                    raw = ""
                if raw is None:
                    wiz.say("Type a file name ending in .yaml (or .json), or press Enter "
                            "for the name in brackets.", "  ")
                    continue
                path = os.path.expanduser(raw.strip() or default)
                if os.path.isdir(path):
                    path = os.path.join(path, "run.yaml")
                if os.path.splitext(path)[1].lower() not in (".yaml", ".yml", ".json"):
                    wiz.say("Please use a name ending in .yaml (or .json).", "  ")
                    continue
                same = edit_path and os.path.abspath(path) == os.path.abspath(edit_path)
                if os.path.exists(path) and not same and not _answer(
                        wiz, f"{path} already exists.  Replace it?", False):
                    continue
                break
            _save(cfg, path, write_all, source="MRRpy wizard")
            wiz.say()
            wiz._out(f"Saved {path}")
            wiz.say("Next steps (commands are on their own line, ready to copy):")
            for what, cmd in (("Run the model:", f"MRRpy run -c {path}"),
                              ("Check it again later:", f"MRRpy validate -c {path}"),
                              ("Change it with questions:", f"MRRpy wizard --edit {path}")):
                wiz.say(what, "  ")
                wiz._out(f"    {cmd}")
            if offer_run and ok and _answer(wiz, "Run the model now?  It can take a while.", False):
                from ..pipeline import run_pipeline
                run_pipeline(cfg)
    except _Quit:
        wiz.say()
        wiz.say("Stopped — nothing was saved.")
        return None
    return cfg

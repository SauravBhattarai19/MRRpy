# -*- coding: utf-8 -*-
"""Helpers shared by the interactive-config tests (not collected by pytest)."""

import copy

from MRRpy import Config
from MRRpy import config_schema as S


def example_for(p):
    """A valid value for *p* that differs from its default."""
    if p.example is not None:
        return copy.deepcopy(p.example)
    if p.kind == "bool":
        return not p.default
    if p.kind == "choice":
        for value, _label in S.choices_for(p):
            if value != p.default and value != "dynamic":   # dynamic is under development
                return value
    raise AssertionError(f"{p.name} needs an `example=` in config_schema.py")


def visible_config(p, cfg=None):
    """A Config (default: fresh) in which *p* matters."""
    cfg = cfg if cfg is not None else Config()
    groups = [p.when] + ([p.when_any[0]] if p.when_any else [])
    for group in groups:
        for name, pred in group:
            setattr(cfg, name, pred.example(S.param(name)))
    return cfg


def normalised(p, value):
    """*value* as the catalogue stores it (tuples→lists, enum codes→names, …)."""
    return S.check_value(p, value)


def same(a, b):
    return S._same(a, b)


class Script:
    """
    A scripted user for the wizard: answers prompts that contain a key with the
    queued answers for it (each answer used once, in order); every other prompt
    gets Enter.  Records every prompt, and fails loudly on a runaway loop.
    """

    def __init__(self, answers=None, default="", limit=400):
        self.answers = {k: (list(v) if isinstance(v, list) else [v])
                        for k, v in (answers or {}).items()}
        self.default = default
        self.limit = limit
        self.prompts = []
        self.printed = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if len(self.prompts) > self.limit:
            raise AssertionError("wizard asked too many questions; last prompts:\n"
                                 + "\n".join(self.prompts[-15:]))
        for key, queue in self.answers.items():
            if key in prompt and queue:
                answer = queue.pop(0)
                if isinstance(answer, BaseException) or (
                        isinstance(answer, type) and issubclass(answer, BaseException)):
                    raise answer
                return answer
        return self.default

    def out(self, *args):
        self.printed.append(" ".join(str(a) for a in args))

    @property
    def text(self):
        return "\n".join(self.printed)

    def asked(self, fragment):
        return sum(fragment in p for p in self.prompts)

    def unused(self):
        return {k: v for k, v in self.answers.items() if v}

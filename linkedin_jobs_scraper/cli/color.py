"""Minimal ANSI colour helper for CLI diagnostics.

Colour is gated per stream: a caller decides once whether a given stream may carry
escape codes and passes that verdict to a Colorizer, which either wraps text or
returns it untouched.
"""
from __future__ import annotations

import os
from typing import TextIO

ANSI_RESET = '\x1b[0m'
ANSI_RED = '\x1b[31m'
ANSI_GREEN = '\x1b[32m'
ANSI_YELLOW = '\x1b[33m'
ANSI_DIM = '\x1b[2m'


def color_enabled(no_color: bool, stream: TextIO) -> bool:
    """Colour is allowed only when not disabled, NO_COLOR is unset, and the stream is a tty."""
    if no_color or os.environ.get('NO_COLOR'):
        return False
    return stream.isatty()


class Colorizer:
    """Wraps text in ANSI codes when enabled, and is a no-op otherwise."""

    def __init__(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self._enabled:
            return text
        return f'{code}{text}{ANSI_RESET}'

    def red(self, text: str) -> str:
        return self._wrap(ANSI_RED, text)

    def green(self, text: str) -> str:
        return self._wrap(ANSI_GREEN, text)

    def yellow(self, text: str) -> str:
        return self._wrap(ANSI_YELLOW, text)

    def dim(self, text: str) -> str:
        return self._wrap(ANSI_DIM, text)

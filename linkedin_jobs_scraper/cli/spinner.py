"""Animated terminal spinner that coordinates the two CLI output streams.

The CLI writes diagnostics to stderr and job data to stdout, both usually the same
physical terminal. A single animated line lives on stderr; any code that prints to
the terminal during the run does so inside `with spinner.pause():` so the animated
line is cleared first and never interleaves with the printed text.
"""
from __future__ import annotations

import contextlib
import itertools
import sys
import threading
from typing import Iterator, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from .args import CliConfig

FRAMES = ('⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏')
INTERVAL_SECONDS = 0.1
SEARCH_EMOJI = '🔎'
JOIN_TIMEOUT_SECONDS = 1.0

# Carriage return then ANSI erase-to-end-of-line. Clears by terminal column rather than
# by character count, so a leading wide glyph like the emoji leaves no residue.
CLEAR_LINE = '\r\x1b[K'


class Spinner:
    """A braille spinner drawn on a stream by one daemon thread, guarded by a lock.

    Every write to the stream — the animation redraw, the clear, and any external
    pause — is serialised through a single lock, so the animated line and printed
    output never interleave on the shared terminal. Disabled spinners are inert: every
    method is a no-op and `pause()` yields without touching the stream.
    """

    def __init__(self, stream: TextIO, enabled: bool) -> None:
        self._stream = stream
        self._enabled = enabled
        self._frames = itertools.cycle(FRAMES)
        self._label = ''
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active = False

    def _compose(self, frame: str) -> str:
        return f'{SEARCH_EMOJI} {frame} {self._label}'

    def _draw(self, frame: str) -> None:
        """Redraw the current label with a frame, erasing any previous line first."""
        self._stream.write(CLEAR_LINE + self._compose(frame))
        self._stream.flush()

    def _clear(self) -> None:
        """Erase the drawn line entirely, by terminal column."""
        self._stream.write(CLEAR_LINE)
        self._stream.flush()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                if self._active:
                    self._draw(next(self._frames))
            self._stop_event.wait(INTERVAL_SECONDS)

    def start(self, label: str) -> None:
        """Set the initial label and start the animation thread, lazily and once."""
        if not self._enabled:
            return
        with self._lock:
            self._label = label
            self._active = True
        if self._thread is None:
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def set_label(self, label: str) -> None:
        """Change the label shown on the next tick."""
        if not self._enabled:
            return
        with self._lock:
            self._label = label

    def stop(self) -> None:
        """Stop the animation, join the thread briefly, and clear the line. Idempotent."""
        if not self._enabled:
            return
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=JOIN_TIMEOUT_SECONDS)
            self._thread = None
        # Clear only after the animation thread is joined, so nothing can redraw after it.
        with self._lock:
            self._active = False
            self._clear()

    @contextlib.contextmanager
    def pause(self) -> Iterator[None]:
        """Hold the lock, clear the animated line, yield for the caller to print, then release.

        The animation resumes on the next tick after the caller returns. When disabled
        this is a plain no-op context manager so callers can wrap writes unconditionally.
        """
        if not self._enabled:
            yield
            return
        with self._lock:
            self._clear()
            yield


def create_spinner(config: 'CliConfig') -> Spinner:
    """Build the stderr spinner, animated only on an interactive, non-quiet run."""
    return Spinner(sys.stderr, enabled=sys.stderr.isatty() and not config.quiet)

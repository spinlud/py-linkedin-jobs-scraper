"""Offline tests for the CLI spinner (linkedin_jobs_scraper.cli.spinner).

No real sleep timing or frame counts are asserted; the draw/clear helpers are exercised
directly and the background thread is started then immediately stopped where needed.
"""
from __future__ import annotations

import io

from linkedin_jobs_scraper.cli.spinner import CLEAR_LINE, FRAMES, Spinner


def _spinner(enabled: bool) -> tuple[Spinner, io.StringIO]:
    stream = io.StringIO()
    return Spinner(stream, enabled=enabled), stream


# --- disabled spinner is inert -------------------------------------------

def test_disabled_spinner_writes_nothing() -> None:
    spinner, stream = _spinner(enabled=False)
    spinner.start('loading')
    spinner.set_label('working')
    spinner.stop()
    assert stream.getvalue() == ''


def test_disabled_pause_is_a_noop_context_manager() -> None:
    spinner, stream = _spinner(enabled=False)
    with spinner.pause():
        pass
    assert stream.getvalue() == ''


def test_disabled_stop_is_idempotent() -> None:
    spinner, _ = _spinner(enabled=False)
    spinner.stop()
    spinner.stop()


# --- enabled spinner lifecycle -------------------------------------------

def test_enabled_start_and_stop_do_not_raise_and_stop_is_idempotent() -> None:
    spinner, _ = _spinner(enabled=True)
    spinner.start('loading')
    spinner.set_label('working')
    spinner.stop()
    spinner.stop()


def test_enabled_pause_works_as_context_manager() -> None:
    spinner, stream = _spinner(enabled=True)
    with spinner.pause():
        stream.write('row\n')
    assert 'row' in stream.getvalue()


# --- draw and clear helpers ----------------------------------------------

def test_draw_writes_emoji_frame_and_label_after_erase() -> None:
    spinner, stream = _spinner(enabled=True)
    spinner._label = 'searching'
    spinner._draw(FRAMES[0])
    output = stream.getvalue()

    assert '🔎' in output
    assert FRAMES[0] in output
    assert 'searching' in output
    # The line is erased to end-of-line before the text, not padded by character count.
    assert output.startswith(CLEAR_LINE)


def test_clear_uses_erase_to_end_of_line() -> None:
    spinner, stream = _spinner(enabled=True)
    spinner._label = 'searching'
    spinner._draw(FRAMES[0])
    stream.seek(0)
    stream.truncate(0)

    spinner._clear()
    # The clear emits only the erase sequence, with no space padding.
    assert stream.getvalue() == CLEAR_LINE
    assert ' ' not in stream.getvalue()


def test_shorter_redraw_leaves_no_residue() -> None:
    spinner, stream = _spinner(enabled=True)
    spinner._label = 'a very long label that occupies width'
    spinner._draw(FRAMES[0])

    spinner._label = 'short'
    spinner._draw(FRAMES[1])

    # Each redraw starts by erasing to end-of-line, so nothing of the longer label lingers.
    tail = stream.getvalue().split(CLEAR_LINE)[-1]
    assert tail == '🔎 ' + FRAMES[1] + ' short'

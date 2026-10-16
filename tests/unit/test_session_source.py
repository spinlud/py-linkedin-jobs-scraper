"""Offline tests for the session source precedence: explicit profile, then environment cookies,
then the default profile.

HOME and the default profile constant point into tmp_path, so the real ~/.lijs is never
touched, and every browser launch is replaced with a stub: no network, no Chrome.
"""
from __future__ import annotations

import importlib
import logging
import stat
from pathlib import Path

import pytest
from selenium.webdriver.chrome.options import Options

from linkedin_jobs_scraper import login as login_module
from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.events import Events
from linkedin_jobs_scraper.exceptions import InvalidCookieException
from linkedin_jobs_scraper.linkedin_scraper import LinkedinScraper
from linkedin_jobs_scraper.query import Query
from linkedin_jobs_scraper.utils import chrome_driver as chrome_driver_module
from linkedin_jobs_scraper.utils import session_source as session_source_module
from linkedin_jobs_scraper.utils.session_source import (SessionSourceKind, create_profile_dir,
                                                        resolve_session_source)

scraper_module = importlib.import_module('linkedin_jobs_scraper.linkedin_scraper')
main_module = importlib.import_module('linkedin_jobs_scraper.cli.main')

SESSION_SOURCE_PREFIX = 'Session source:'


class BrowserLaunchBlocked(Exception):
    """Raised by the stubs standing in for a real browser launch."""


def _block_browser(*_args: object, **_kwargs: object) -> None:
    raise BrowserLaunchBlocked()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home_dir = tmp_path / 'home'
    home_dir.mkdir()
    monkeypatch.setenv('HOME', str(home_dir))
    monkeypatch.setattr(session_source_module, 'DEFAULT_CHROME_PROFILE',
                        home_dir / '.lijs' / 'chrome-profile')
    for name in ('LI_AT_COOKIE', 'LI_RM_COOKIE', 'LI_BCOOKIE'):
        monkeypatch.setattr(Config, name, None)
    monkeypatch.setattr(scraper_module, 'build_driver', _block_browser)
    monkeypatch.setattr(login_module, 'build_driver', _block_browser)
    return home_dir


@pytest.fixture
def default_profile(home: Path) -> Path:
    return home / '.lijs' / 'chrome-profile'


@pytest.fixture
def cookie_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, 'LI_RM_COOKIE', 'remember-value')
    monkeypatch.setattr(Config, 'LI_BCOOKIE', 'browser-id-value')


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _session_source_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records
            if SESSION_SOURCE_PREFIX in record.getMessage()]


def _populate(profile: Path) -> None:
    """Make a profile directory that is not empty, the way a browser leaves one."""
    profile.mkdir(parents=True, exist_ok=True)
    (profile / 'Local State').write_text('{}')


def _mode_at_launch(monkeypatch: pytest.MonkeyPatch, profile: Path) -> dict[Path, int]:
    """Stub the login browser launch, recording each directory's mode when it is reached."""
    modes: dict[Path, int] = {}

    def _record(**_kwargs: object) -> None:
        for directory in (profile, profile.parent):
            modes[directory] = _mode(directory)
        raise BrowserLaunchBlocked()

    monkeypatch.setattr(login_module, 'build_driver', _record)
    return modes


def _run_once(scraper: LinkedinScraper) -> None:
    # build_driver is stubbed, so the query fails inside its worker and is reported as an
    # ERROR event rather than raised
    scraper.run(Query(query='engineer'))


# Precedence


def test_explicit_profile_beats_cookies(home: Path, cookie_pair: None, tmp_path: Path) -> None:
    profile = tmp_path / 'explicit'
    scraper = LinkedinScraper(chrome_user_data_dir=str(profile), max_workers=3)

    assert scraper.session_source.kind is SessionSourceKind.PROFILE
    assert scraper.chrome_user_data_dir == str(profile)
    assert scraper._pool._max_workers == 1


def test_chrome_options_user_data_dir_counts_as_explicit(home: Path, tmp_path: Path) -> None:
    options = Options()
    options.add_argument(f'--user-data-dir={tmp_path / "from-options"}')

    source = resolve_session_source(None, options)
    scraper = LinkedinScraper(chrome_options=options, max_workers=3)

    assert source.kind is SessionSourceKind.OPTIONS_PROFILE
    assert source.options_user_data_dir == str(tmp_path / 'from-options')
    assert scraper.chrome_user_data_dir is None
    assert scraper._pool._max_workers == 3


def test_cookies_without_profile_use_cookie_mode(home: Path, cookie_pair: None) -> None:
    scraper = LinkedinScraper(max_workers=3)

    assert scraper.session_source.kind is SessionSourceKind.COOKIES
    assert scraper.chrome_user_data_dir is None
    assert scraper._pool._max_workers == 3


def test_session_cookie_alone_uses_cookie_mode(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')

    assert resolve_session_source().kind is SessionSourceKind.COOKIES


def test_half_a_cookie_pair_falls_back_to_default_profile(
        home: Path, default_profile: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Config, 'LI_RM_COOKIE', 'remember-value')

    source = resolve_session_source()

    assert source.kind is SessionSourceKind.DEFAULT_PROFILE
    assert source.chrome_user_data_dir == default_profile


def test_neither_uses_default_profile_with_one_worker(home: Path, default_profile: Path) -> None:
    scraper = LinkedinScraper(max_workers=3)

    assert scraper.session_source.kind is SessionSourceKind.DEFAULT_PROFILE
    assert scraper.chrome_user_data_dir == str(default_profile)
    assert scraper._pool._max_workers == 1


def test_explicit_profile_expands_tilde(home: Path) -> None:
    scraper = LinkedinScraper(chrome_user_data_dir='~/custom-profile')

    assert scraper.chrome_user_data_dir == str(home / 'custom-profile')


def test_interactive_login_accepts_default_profile(home: Path) -> None:
    scraper = LinkedinScraper(interactive_login=True)

    assert scraper.session_source.kind is SessionSourceKind.DEFAULT_PROFILE


def test_interactive_login_rejects_cookie_mode(home: Path, cookie_pair: None) -> None:
    with pytest.raises(ValueError, match='interactive_login requires a Chrome profile'):
        LinkedinScraper(interactive_login=True)


# Missing default profile


def test_missing_default_profile_fails_run_without_creating_it(home: Path, default_profile: Path) -> None:
    scraper = LinkedinScraper()
    invalid_sessions: list[bool] = []
    scraper.on(Events.INVALID_SESSION, lambda: invalid_sessions.append(True))

    with pytest.raises(InvalidCookieException, match='lijs login') as exc_info:
        _run_once(scraper)

    assert '~/.lijs/chrome-profile does not exist' in str(exc_info.value)
    assert 'linkedin_jobs_scraper.login.sign_in' in str(exc_info.value)
    assert invalid_sessions == [True]
    assert not (home / '.lijs').exists()


def test_missing_default_profile_fails_scrape_job_without_creating_it(home: Path) -> None:
    scraper = LinkedinScraper()
    invalid_sessions: list[bool] = []
    scraper.on(Events.INVALID_SESSION, lambda: invalid_sessions.append(True))

    with pytest.raises(InvalidCookieException, match='lijs login'):
        scraper.scrape_job('123456789')

    assert invalid_sessions == [True]
    assert not (home / '.lijs').exists()


def test_existing_default_profile_reaches_the_browser(home: Path, default_profile: Path) -> None:
    _populate(default_profile)
    scraper = LinkedinScraper()
    errors: list[str] = []
    scraper.on(Events.ERROR, errors.append)

    _run_once(scraper)

    assert len(errors) == 1
    assert 'BrowserLaunchBlocked' in errors[0]


def test_cli_jobs_reports_missing_default_profile(
        home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main_module.main(['--quiet', 'jobs', 'engineer', '--limit', '1', '--no-color'])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert 'error: No session available: the Chrome profile ~/.lijs/chrome-profile does not exist.' in captured.err
    assert '`lijs login`' in captured.err
    assert not (home / '.lijs').exists()


# Session source log line


@pytest.mark.parametrize(('setup', 'expected'), [
    ('default', 'Session source: Chrome profile ~/.lijs/chrome-profile (default)'),
    ('explicit', 'Session source: Chrome profile ~/explicit'),
    ('options', 'Session source: Chrome profile /opt/profile (from chrome_options)'),
    ('pair', 'Session source: cookie pair from environment (LI_RM_COOKIE, LI_BCOOKIE)'),
    ('li_at', 'Session source: session cookie from environment (LI_AT_COOKIE)'),
])
def test_one_session_source_line_per_run(
        setup: str, expected: str, home: Path, default_profile: Path,
        monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=Config.LOGGER_NAMESPACE)
    kwargs: dict[str, object] = {}

    if setup == 'default':
        _populate(default_profile)
    elif setup == 'explicit':
        _populate(home / 'explicit')
        kwargs['chrome_user_data_dir'] = '~/explicit'
    elif setup == 'options':
        options = Options()
        options.add_argument('--user-data-dir=/opt/profile')
        kwargs['chrome_options'] = options
    elif setup == 'pair':
        monkeypatch.setattr(Config, 'LI_RM_COOKIE', 'remember-value')
        monkeypatch.setattr(Config, 'LI_BCOOKIE', 'browser-id-value')
    else:
        monkeypatch.setattr(Config, 'LI_AT_COOKIE', 'session-value')

    scraper = LinkedinScraper(**kwargs)
    scraper.on(Events.ERROR, lambda _error: None)
    _run_once(scraper)

    lines = _session_source_lines(caplog)
    assert len(lines) == 1
    assert expected in lines[0]
    assert all(record.levelno == logging.INFO for record in caplog.records
               if SESSION_SOURCE_PREFIX in record.getMessage())
    assert 'remember-value' not in caplog.text
    assert 'session-value' not in caplog.text


# Login


def test_sign_in_without_profile_creates_default_owner_only(
        home: Path, default_profile: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    modes = _mode_at_launch(monkeypatch, default_profile)

    with pytest.raises(BrowserLaunchBlocked):
        login_module.sign_in()

    assert modes == {default_profile: 0o700, default_profile.parent: 0o700}


def test_sign_in_leaves_existing_parent_permissions(
        home: Path, default_profile: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    default_profile.parent.mkdir(mode=0o755)
    default_profile.parent.chmod(0o755)
    modes = _mode_at_launch(monkeypatch, default_profile)

    with pytest.raises(BrowserLaunchBlocked):
        login_module.sign_in()

    assert modes == {default_profile: 0o700, default_profile.parent: 0o755}
    assert _mode(default_profile.parent) == 0o755


def test_sign_in_leaves_existing_profile_permissions(home: Path, default_profile: Path) -> None:
    default_profile.mkdir(parents=True)
    default_profile.chmod(0o750)

    with pytest.raises(BrowserLaunchBlocked):
        login_module.sign_in()

    assert _mode(default_profile) == 0o750


def test_sign_in_expands_tilde(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[tuple[str, int]] = []

    def _record(**kwargs: object) -> None:
        profile = Path(str(kwargs['chrome_user_data_dir']))
        received.append((str(profile), _mode(profile)))
        raise BrowserLaunchBlocked()

    monkeypatch.setattr(login_module, 'build_driver', _record)

    with pytest.raises(BrowserLaunchBlocked):
        login_module.sign_in('~/custom-profile')

    assert received == [(str(home / 'custom-profile'), 0o700)]


def test_has_credentials_without_profile_dir_opens_no_browser(home: Path, default_profile: Path) -> None:
    assert login_module.has_credentials() is False
    assert not default_profile.exists()


def test_create_profile_dir_creates_every_missing_parent_owner_only(tmp_path: Path) -> None:
    profile = tmp_path / 'a' / 'b' / 'profile'

    create_profile_dir(profile)

    for directory in (tmp_path / 'a', tmp_path / 'a' / 'b', profile):
        assert _mode(directory) == 0o700


def test_cli_login_without_flag_uses_default_profile(
        home: Path, default_profile: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    received: list[object] = []

    def _sign_in(profile: object, *_args: object) -> None:
        received.append(profile)
        return None

    monkeypatch.setattr(main_module, 'sign_in', _sign_in)

    exit_code = main_module.main(['login', '--no-color'])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert received == [default_profile]
    assert 'Chrome profile: ~/.lijs/chrome-profile' in captured.out


def test_cli_login_expands_tilde(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[object] = []

    def _sign_in(profile: object, *_args: object) -> None:
        received.append(profile)
        return None

    monkeypatch.setattr(main_module, 'sign_in', _sign_in)

    main_module.main(['login', '--chrome-profile', '~/custom-profile', '--no-color'])

    assert received == [home / 'custom-profile']


# Driver options


def test_build_driver_adds_profile_to_caller_options(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chrome_driver_module, '_build_chrome_service', _block_browser)
    options = Options()

    with pytest.raises(BrowserLaunchBlocked):
        chrome_driver_module.build_driver(options=options, chrome_user_data_dir=str(tmp_path / 'p'))

    assert f'--user-data-dir={(tmp_path / "p").resolve()}' in options.arguments


def test_build_driver_keeps_caller_user_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chrome_driver_module, '_build_chrome_service', _block_browser)
    options = Options()
    options.add_argument('--user-data-dir=/opt/profile')

    with pytest.raises(BrowserLaunchBlocked):
        chrome_driver_module.build_driver(options=options, chrome_user_data_dir=str(tmp_path / 'p'))

    assert [argument for argument in options.arguments if argument.startswith('--user-data-dir=')] == [
        '--user-data-dir=/opt/profile']


# Sign in cleanup


class FakeLoginDriver:
    """Stands in for the visible login browser; it writes into the profile like Chrome does."""

    def __init__(self, profile: Path, fail_on_get: bool = False) -> None:
        self._profile = profile
        self._fail_on_get = fail_on_get
        self.profile_existed_at_quit: bool | None = None
        (profile / 'Local State').write_text('{}')
        (profile / 'Default').mkdir()
        (profile / 'Default' / 'Cookies').write_text('')

    def get(self, _url: str) -> None:
        if self._fail_on_get:
            raise RuntimeError('navigation failed')

    def quit(self) -> None:
        self.profile_existed_at_quit = self._profile.exists()


def _fake_login_browser(monkeypatch: pytest.MonkeyPatch, fail_on_get: bool = False) -> list[FakeLoginDriver]:
    drivers: list[FakeLoginDriver] = []

    def _build(**kwargs: object) -> FakeLoginDriver:
        driver = FakeLoginDriver(Path(str(kwargs['chrome_user_data_dir'])), fail_on_get)
        drivers.append(driver)
        return driver

    monkeypatch.setattr(login_module, 'build_driver', _build)
    monkeypatch.setattr(login_module, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(login_module, 'get_session_cookie', lambda _driver: None)
    return drivers


def _wait_returning(value: str | None):
    def _wait(_driver: object, timeout: int = 0) -> str | None:
        return value
    return _wait


def _wait_raising(error: BaseException):
    def _wait(_driver: object, timeout: int = 0) -> str | None:
        raise error
    return _wait


def test_sign_in_failing_launch_removes_created_dirs(home: Path) -> None:
    with pytest.raises(BrowserLaunchBlocked):
        login_module.sign_in()

    assert not (home / '.lijs').exists()


def test_sign_in_exception_removes_created_dirs_after_quitting(
        home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    drivers = _fake_login_browser(monkeypatch, fail_on_get=True)

    with pytest.raises(RuntimeError, match='navigation failed'):
        login_module.sign_in()

    assert drivers[0].profile_existed_at_quit is True
    assert not (home / '.lijs').exists()
    assert list(home.iterdir()) == []


def test_sign_in_timeout_removes_created_dirs(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    drivers = _fake_login_browser(monkeypatch)
    monkeypatch.setattr(login_module, 'wait_for_session', _wait_returning(None))

    assert login_module.sign_in() is None

    assert drivers[0].profile_existed_at_quit is True
    assert not (home / '.lijs').exists()


def test_sign_in_interrupt_removes_created_dirs_and_reraises(
        home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    drivers = _fake_login_browser(monkeypatch)
    monkeypatch.setattr(login_module, 'wait_for_session', _wait_raising(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        login_module.sign_in()

    assert drivers[0].profile_existed_at_quit is True
    assert not (home / '.lijs').exists()


def test_sign_in_closed_browser_ends_the_wait_and_removes_created_dirs(
        home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class ClosedBrowser(FakeLoginDriver):
        @property
        def window_handles(self) -> list[str]:
            raise RuntimeError('browser has exited')

    def _build(**kwargs: object) -> ClosedBrowser:
        return ClosedBrowser(Path(str(kwargs['chrome_user_data_dir'])))

    _fake_login_browser(monkeypatch)
    monkeypatch.setattr(login_module, 'build_driver', _build)

    assert login_module.sign_in() is None
    assert not (home / '.lijs').exists()


def test_sign_in_keeps_preexisting_parent(home: Path, default_profile: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    default_profile.parent.mkdir()
    (default_profile.parent / 'notes').write_text('keep')
    _fake_login_browser(monkeypatch)
    monkeypatch.setattr(login_module, 'wait_for_session', _wait_raising(KeyboardInterrupt()))

    with pytest.raises(KeyboardInterrupt):
        login_module.sign_in()

    assert not default_profile.exists()
    assert (default_profile.parent / 'notes').read_text() == 'keep'


@pytest.mark.parametrize('failure', [RuntimeError('boom'), KeyboardInterrupt(), None])
def test_sign_in_never_removes_a_preexisting_profile(
        failure: BaseException | None, home: Path, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    profile = tmp_path / 'existing-profile'
    profile.mkdir()
    (profile / 'Previous Session').write_text('valid')
    drivers = _fake_login_browser(monkeypatch)
    if failure is None:
        monkeypatch.setattr(login_module, 'wait_for_session', _wait_returning(None))
    else:
        monkeypatch.setattr(login_module, 'wait_for_session', _wait_raising(failure))

    if failure is None:
        assert login_module.sign_in(profile) is None
    else:
        with pytest.raises(type(failure)):
            login_module.sign_in(profile)

    assert len(drivers) == 1
    assert (profile / 'Previous Session').read_text() == 'valid'
    assert (profile / 'Local State').exists()


def test_sign_in_success_keeps_the_profile(home: Path, default_profile: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_login_browser(monkeypatch)
    monkeypatch.setattr(login_module, 'wait_for_session', _wait_returning('session-value'))
    monkeypatch.setattr(login_module, 'get_cookie', lambda _driver, name: f'{name}-value')

    credentials = login_module.sign_in()

    assert credentials is not None
    assert credentials['li_at'] == 'session-value'
    assert (default_profile / 'Local State').exists()
    assert _mode(default_profile) == 0o700


def test_cli_login_interrupt_exits_130_without_traceback(
        home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _fake_login_browser(monkeypatch)
    monkeypatch.setattr(login_module, 'wait_for_session', _wait_raising(KeyboardInterrupt()))

    exit_code = main_module.main(['login', '--no-color'])
    captured = capsys.readouterr()

    assert exit_code == 130
    assert 'Interrupted: no session was established.' in captured.err
    assert 'Traceback' not in captured.err
    assert not (home / '.lijs').exists()


# Profiles that hold no session


def test_empty_default_profile_fails_like_a_missing_one(home: Path, default_profile: Path) -> None:
    default_profile.mkdir(parents=True)
    scraper = LinkedinScraper()
    invalid_sessions: list[bool] = []
    scraper.on(Events.INVALID_SESSION, lambda: invalid_sessions.append(True))

    with pytest.raises(InvalidCookieException, match='lijs login') as exc_info:
        _run_once(scraper)

    assert '~/.lijs/chrome-profile is empty' in str(exc_info.value)
    assert invalid_sessions == [True]
    assert list(default_profile.iterdir()) == []


@pytest.mark.parametrize('is_created', [True, False])
def test_empty_or_missing_explicit_profile_without_cookies_fails(
        is_created: bool, home: Path) -> None:
    profile = home / 'explicit'
    if is_created:
        profile.mkdir()
    scraper = LinkedinScraper(chrome_user_data_dir=str(profile))
    invalid_sessions: list[bool] = []
    scraper.on(Events.INVALID_SESSION, lambda: invalid_sessions.append(True))

    with pytest.raises(InvalidCookieException, match='No session available'):
        scraper.scrape_job('123456789')

    assert invalid_sessions == [True]
    assert profile.exists() is is_created


def test_empty_explicit_profile_with_cookies_reaches_the_browser(home: Path, cookie_pair: None) -> None:
    profile = home / 'explicit'
    profile.mkdir()
    scraper = LinkedinScraper(chrome_user_data_dir=str(profile))
    errors: list[str] = []
    scraper.on(Events.ERROR, errors.append)

    _run_once(scraper)

    assert len(errors) == 1
    assert 'BrowserLaunchBlocked' in errors[0]


def test_cli_jobs_reports_empty_default_profile(
        home: Path, default_profile: Path, capsys: pytest.CaptureFixture[str]) -> None:
    default_profile.mkdir(parents=True)

    exit_code = main_module.main(['jobs', 'engineer', '--limit', '1', '--no-color'])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert 'error: session invalid or refused' in captured.err
    assert 'error: No session available: the Chrome profile ~/.lijs/chrome-profile is empty.' in captured.err


class FakeScrapeDriver:
    """A browser that loads every page and never holds a session."""

    def get(self, _url: str) -> None:
        return None

    def quit(self) -> None:
        return None


@pytest.fixture
def sessionless_browser(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from linkedin_jobs_scraper.strategies import authenticated_strategy as strategy_module

    monkeypatch.setattr(scraper_module, 'build_driver', lambda **_kwargs: FakeScrapeDriver())
    monkeypatch.setattr(strategy_module, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(strategy_module, 'wait_for_linkedin', lambda _driver: True)
    monkeypatch.setattr(strategy_module, 'mask_headless_user_agent', lambda _driver: None)
    monkeypatch.setattr(strategy_module, 'get_session_cookie', lambda _driver: None)
    monkeypatch.setattr(strategy_module, 'get_cookie', lambda _driver, _name: None)
    monkeypatch.setattr(strategy_module.AuthenticatedStrategy, '_AuthenticatedStrategy__wait_for_session',
                        staticmethod(lambda _driver, timeout=0: None))


def test_profile_without_session_emits_invalid_session(
        sessionless_browser: None, default_profile: Path) -> None:
    _populate(default_profile)
    scraper = LinkedinScraper()
    invalid_sessions: list[bool] = []
    scraper.on(Events.INVALID_SESSION, lambda: invalid_sessions.append(True))

    with pytest.raises(InvalidCookieException, match='No usable session'):
        _run_once(scraper)

    assert invalid_sessions == [True]


@pytest.mark.parametrize('argv', [
    ['jobs', 'engineer', '--limit', '1', '--no-color'],
    ['job', '123456789', '--no-color'],
])
def test_cli_profile_without_session_exits_2(
        argv: list[str], sessionless_browser: None, default_profile: Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    _populate(default_profile)

    exit_code = main_module.main(argv)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert 'error: session invalid or refused' in captured.err
    assert 'error: No usable session:' in captured.err


# Session row in the CLI summary


def test_cli_summary_names_default_profile(
        home: Path, default_profile: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _populate(default_profile)

    main_module.main(['jobs', 'engineer', '--limit', '1', '--no-color'])
    captured = capsys.readouterr()

    assert '   session    Chrome profile ~/.lijs/chrome-profile (default)\n' in captured.err


def test_cli_summary_names_cookie_pair(
        home: Path, cookie_pair: None, capsys: pytest.CaptureFixture[str]) -> None:
    main_module.main(['job', '123456789', '--no-color'])
    captured = capsys.readouterr()

    assert '   session    cookie pair from environment (LI_RM_COOKIE, LI_BCOOKIE)\n' in captured.err
    assert 'remember-value' not in captured.err
    assert 'browser-id-value' not in captured.err


def test_cli_summary_omitted_when_quiet(
        home: Path, cookie_pair: None, capsys: pytest.CaptureFixture[str]) -> None:
    main_module.main(['--quiet', 'job', '123456789', '--no-color'])

    assert 'session ' not in capsys.readouterr().err


# Worker count


PROFILE_WORKER_WARNING = 'A Chrome profile cannot be shared by concurrent browsers'


def test_max_workers_defaults_to_one(home: Path, cookie_pair: None) -> None:
    assert LinkedinScraper()._pool._max_workers == 1


def test_profile_with_default_workers_does_not_warn(
        home: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=Config.LOGGER_NAMESPACE)

    scraper = LinkedinScraper()

    assert scraper._pool._max_workers == 1
    assert PROFILE_WORKER_WARNING not in caplog.text


@pytest.mark.parametrize('kwargs', [{}, {'chrome_user_data_dir': '~/explicit'}])
def test_profile_with_explicit_workers_warns_and_runs_one(
        kwargs: dict[str, str], home: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=Config.LOGGER_NAMESPACE)

    scraper = LinkedinScraper(max_workers=2, **kwargs)

    assert scraper._pool._max_workers == 1
    assert PROFILE_WORKER_WARNING in caplog.text


def test_cookie_mode_honours_explicit_workers(
        home: Path, cookie_pair: None, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=Config.LOGGER_NAMESPACE)

    scraper = LinkedinScraper(max_workers=2)

    assert scraper._pool._max_workers == 2
    assert PROFILE_WORKER_WARNING not in caplog.text

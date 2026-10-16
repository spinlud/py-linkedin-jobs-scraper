"""Where a run's LinkedIn session comes from, decided once before any browser opens.

The precedence is the same for the command line and the library:

1. a Chrome profile the caller names, through chrome_user_data_dir or a --user-data-dir
   argument in their own chrome_options;
2. otherwise the cookies in the environment, when they make a usable credential on their
   own: LI_AT_COOKIE, or LI_RM_COOKIE together with LI_BCOOKIE;
3. otherwise the default profile, DEFAULT_CHROME_PROFILE, which `lijs login` creates.
"""
from __future__ import annotations

import enum
import shutil
from dataclasses import dataclass
from pathlib import Path

from selenium.webdriver.chrome.options import Options

from ..config import Config

DEFAULT_CHROME_PROFILE = Path.home() / '.lijs' / 'chrome-profile'

# Owner only: the profile holds a signed in LinkedIn session
PROFILE_DIR_MODE = 0o700

USER_DATA_DIR_ARGUMENT = '--user-data-dir='


class SessionSourceKind(enum.Enum):
    PROFILE = 'profile'
    OPTIONS_PROFILE = 'options_profile'
    COOKIES = 'cookies'
    DEFAULT_PROFILE = 'default_profile'


@dataclass(frozen=True)
class SessionSource:
    kind: SessionSourceKind
    # The profile the scraper hands to build_driver, None when the browser gets a throwaway
    # profile or when the caller's own chrome_options already carry --user-data-dir
    chrome_user_data_dir: Path | None = None
    # The --user-data-dir found in the caller's chrome_options, for reporting only
    options_user_data_dir: str | None = None

    @property
    def is_persistent_profile(self) -> bool:
        return self.kind in (SessionSourceKind.PROFILE, SessionSourceKind.DEFAULT_PROFILE)

    def summary(self) -> str:
        """The source on its own, e.g. `Chrome profile ~/.lijs/chrome-profile (default)`.

        Never includes any cookie value.
        """
        if self.kind is SessionSourceKind.DEFAULT_PROFILE:
            return f'Chrome profile {display_path(self.chrome_user_data_dir)} (default)'
        if self.kind is SessionSourceKind.PROFILE:
            return f'Chrome profile {display_path(self.chrome_user_data_dir)}'
        if self.kind is SessionSourceKind.OPTIONS_PROFILE:
            return f'Chrome profile {self.options_user_data_dir} (from chrome_options)'
        if has_cookie_pair():
            return 'cookie pair from environment (LI_RM_COOKIE, LI_BCOOKIE)'
        return 'session cookie from environment (LI_AT_COOKIE)'

    def describe(self) -> str:
        """One line naming the source, never any cookie value."""
        return f'Session source: {self.summary()}'


def default_chrome_profile() -> Path:
    """The default profile, read at call time so tests can point it elsewhere."""
    return DEFAULT_CHROME_PROFILE


def expand_profile_path(chrome_user_data_dir: str | Path) -> Path:
    return Path(chrome_user_data_dir).expanduser()


def display_path(path: Path | None) -> str:
    """Render a path under the home directory with a leading ~."""
    if path is None:
        return ''
    try:
        return str(Path('~') / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def has_cookie_pair() -> bool:
    return bool(Config.LI_RM_COOKIE and Config.LI_BCOOKIE)


def has_cookie_credentials() -> bool:
    """True when the environment holds a credential AuthenticatedStrategy can use on its own."""
    return bool(Config.LI_AT_COOKIE) or has_cookie_pair()


def find_options_user_data_dir(chrome_options: Options | None) -> str | None:
    if chrome_options is None:
        return None
    for argument in chrome_options.arguments:
        if argument.startswith(USER_DATA_DIR_ARGUMENT):
            return argument[len(USER_DATA_DIR_ARGUMENT):]
    return None


def resolve_session_source(chrome_user_data_dir: str | Path | None = None,
                           chrome_options: Options | None = None) -> SessionSource:
    """Pick the session source by the precedence described in the module docstring."""
    if chrome_user_data_dir:
        return SessionSource(SessionSourceKind.PROFILE, expand_profile_path(chrome_user_data_dir))

    options_user_data_dir = find_options_user_data_dir(chrome_options)
    if options_user_data_dir:
        return SessionSource(SessionSourceKind.OPTIONS_PROFILE,
                             options_user_data_dir=options_user_data_dir)

    if has_cookie_credentials():
        return SessionSource(SessionSourceKind.COOKIES)

    return SessionSource(SessionSourceKind.DEFAULT_PROFILE, default_chrome_profile())


def resolve_login_profile(chrome_user_data_dir: str | Path | None = None) -> Path:
    """The profile a sign in writes to: the one named, or the default one. Never cookies."""
    if chrome_user_data_dir:
        return expand_profile_path(chrome_user_data_dir)
    return default_chrome_profile()


def create_profile_dir(profile: Path) -> list[Path]:
    """
    Create the profile directory and any missing parent, each owner only

    Directories that already exist keep the permissions they have. A failure part way
    through removes whatever this call had already created.

    :param profile: Path
    :return: list[Path] the directories this call created, outermost first
    """
    missing = [directory for directory in (profile, *profile.parents) if not directory.exists()]
    created: list[Path] = []
    try:
        for directory in reversed(missing):
            directory.mkdir(mode=PROFILE_DIR_MODE)
            created.append(directory)
            # mkdir's mode is filtered by the umask, so the permissions are set explicitly
            directory.chmod(PROFILE_DIR_MODE)
    except BaseException:
        remove_created_profile_dirs(created)
        raise
    return created


def remove_created_profile_dirs(created: list[Path]) -> None:
    """
    Remove the directories a create_profile_dir call returned, innermost first

    The innermost one is the profile, which Chrome has filled with its own files, so it is
    removed with everything in it. Each parent is removed only once it is empty, so nothing
    put there by anything else is lost. Paths that are no longer directories, or are
    symbolic links, are left alone.

    :param created: list[Path] as returned by create_profile_dir
    :return: None
    """
    for index, directory in enumerate(reversed(created)):
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            if index == 0:
                shutil.rmtree(directory)
            else:
                directory.rmdir()
        except OSError:
            # A parent that is not empty, or a file Chrome still holds, stays where it is
            return


def is_empty_dir(path: Path) -> bool:
    return path.is_dir() and next(path.iterdir(), None) is None


def missing_session_message(missing_profile: Path | None = None) -> str:
    """
    The error for a run with nothing to authenticate with

    :param missing_profile: Path | None a profile directory the run expected and found missing or empty
    :return: str
    """
    reason = ''
    if missing_profile is not None:
        state = 'is empty' if missing_profile.is_dir() else 'does not exist'
        reason = f' the Chrome profile {display_path(missing_profile)} {state}.'
    return (f'No session available:{reason} Set LI_RM_COOKIE with LI_BCOOKIE (or LI_AT_COOKIE), '
            f'or sign in once with `lijs login` (default profile '
            f'{display_path(default_chrome_profile())}, or --chrome-profile <path>; from Python: '
            f'linkedin_jobs_scraper.login.sign_in())')

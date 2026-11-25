"""Every Chrome a test here starts reaches the fake LinkedIn, and no other host."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Iterator
from datetime import datetime, tzinfo
from pathlib import Path
from typing import NamedTuple

import pytest
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webdriver import WebDriver

from linkedin_jobs_scraper.config import Config
from linkedin_jobs_scraper.exceptions import ChromedriverResolutionException
from linkedin_jobs_scraper.strategies import authenticated_strategy
from linkedin_jobs_scraper.utils import chrome_driver, session_source

from .fake_linkedin import SESSION, FakeLinkedin
from .network_block import assert_blocked, block_arguments

# Several times what the slowest test takes
TEST_TIMEOUT = 30


class Launch(NamedTuple):
    """A browser the package started, and the arguments it asked for, the block not included."""

    driver: WebDriver
    requested_arguments: list[str]


def block_browsers(monkeypatch: pytest.MonkeyPatch, port: int) -> list[Launch]:
    """
    Cut off every browser the package starts, the short one that reads the User-Agent included

    The block is added to the options the package built, on their way to Chrome: passing
    chrome_options instead would replace those options, and the way headless is masked.
    """
    launches: list[Launch] = []

    class BlockedChrome(webdriver.Chrome):
        def __init__(self, options: Options, service: Service) -> None:
            launches.append(Launch(self, list(options.arguments)))
            for argument in block_arguments(port):
                options.add_argument(argument)
            super().__init__(options=options, service=service)

    monkeypatch.setattr(webdriver, 'Chrome', BlockedChrome)
    # Selenium Manager answers from its cache, and reports to nobody
    monkeypatch.setenv('SE_OFFLINE', 'true')
    monkeypatch.setenv('SE_AVOID_STATS', 'true')
    return launches


@pytest.fixture(scope='session')
def certificate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp('tls')
    path = directory / 'certificate.pem'
    key = directory / 'key.pem'
    command = 'openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=www.linkedin.com'
    subprocess.run(
        [*command.split(), '-keyout', str(key), '-out', str(path)], check=True, capture_output=True
    )
    path.write_text(path.read_text() + key.read_text())
    return path


@pytest.fixture(scope='session', autouse=True)
def _block_holds(certificate: Path) -> None:
    """No test runs unless another host is seen to be unreachable."""
    with FakeLinkedin(certificate).serving() as fake, pytest.MonkeyPatch.context() as patch:
        block_browsers(patch, fake.port)
        try:
            assert_blocked(fake)
        except AssertionError as e:
            pytest.exit(f'The network block does not hold: {e}', returncode=1)
        except ChromedriverResolutionException as e:
            pytest.exit(
                f'Run `npm run test:browser:driver` once, for this Chrome: {e}', returncode=1
            )


@pytest.fixture
def linkedin(certificate: Path) -> Iterator[FakeLinkedin]:
    with FakeLinkedin(certificate).serving() as fake:
        yield fake


@pytest.fixture(autouse=True)
def launches(
    monkeypatch: pytest.MonkeyPatch, linkedin: FakeLinkedin, tmp_path: Path
) -> Iterator[list[Launch]]:
    monkeypatch.setattr(chrome_driver, '_masked_user_agent', None)
    monkeypatch.setattr(chrome_driver, '_is_user_agent_resolved', False)
    # With a cookie Chrome gets a profile of its own, deleted when it closes
    monkeypatch.setattr(Config, 'LI_AT_COOKIE', SESSION)
    monkeypatch.setattr(Config, 'LI_RM_COOKIE', None)
    monkeypatch.setattr(Config, 'LI_BCOOKIE', None)
    monkeypatch.setattr(session_source, 'DEFAULT_CHROME_PROFILE', tmp_path / 'no-profile')
    launches = block_browsers(monkeypatch, linkedin.port)

    def close() -> None:
        for launch in launches:
            chrome_driver.quit_driver(launch.driver)

    # A search that no longer finds its jobs goes on from page to page: without a browser it ends
    deadline = threading.Timer(TEST_TIMEOUT, close)
    deadline.start()
    yield launches
    deadline.cancel()


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> FixedClock:
            return cls(2026, 11, 23, 18, 30, tzinfo=tz)

    monkeypatch.setattr(authenticated_strategy, 'datetime', FixedClock)

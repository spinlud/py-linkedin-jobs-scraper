from __future__ import annotations

from .fake_linkedin import FakeLinkedin
from .network_block import assert_blocked


def test_another_host_is_unreachable(linkedin: FakeLinkedin) -> None:
    assert_blocked(linkedin)

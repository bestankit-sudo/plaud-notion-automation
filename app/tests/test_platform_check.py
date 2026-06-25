import platform
import sys

import pytest

from app import platform_check


def test_supported_on_darwin_arm64(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert platform_check.is_supported() is True


def test_unsupported_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert platform_check.is_supported() is False


def test_unsupported_on_intel_mac(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    assert platform_check.is_supported() is False


def test_assert_supported_exits_when_unsupported(monkeypatch):
    monkeypatch.setattr(platform_check, "is_supported", lambda: False)
    with pytest.raises(SystemExit) as exc:
        platform_check.assert_supported()
    assert exc.value.code == 1

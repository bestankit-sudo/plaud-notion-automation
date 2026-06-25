"""Hard gate: this app only runs on macOS / Apple Silicon (the local Whisper +
launchd stack is arm64-only). Used by the ./run bootstrap and importable for tests."""

from __future__ import annotations

import platform
import sys


def is_supported() -> bool:
    return sys.platform == "darwin" and platform.machine() == "arm64"


def assert_supported() -> None:
    if not is_supported():
        sys.stderr.write(
            "plaudautomation requires macOS on Apple Silicon (arm64). "
            f"Detected: {sys.platform}/{platform.machine()}.\n"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    assert_supported()
    print("platform OK: macOS/arm64")

"""Ordered registry of setup-wizard install steps. Pure data — imports nothing
that shells out. `kind` is "auto" (the wizard can run it) or "guide" (a human /
GUI step: show a link + Test). Detection and command-planning live in
detect.py / plan.py and key off step.id; Step itself stays a plain dataclass."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    kind: str  # "auto" | "guide"
    detail: str
    guide_url: str | None = None


ALL_STEPS: list[Step] = [
    Step("brew", "Homebrew", "guide",
         "Package manager (ffmpeg + Python 3.12 come from it). Installs need your password in Terminal.",
         "https://brew.sh"),
    Step("ffmpeg", "ffmpeg", "auto", "Audio decoding for transcription."),
    Step("py312", "Python 3.12", "auto",
         "Required for the ML stack — torch/pyannote have no wheels for newer Python."),
    Step("ml", "Local ML stack", "auto",
         "Whisper + speaker diarization, installed into worker/.venv-ml."),
    Step("docker", "Docker Desktop", "guide",
         "Needed to run Riffado. Install the app, then start it.",
         "https://www.docker.com/products/docker-desktop/"),
    Step("riffado", "Riffado", "auto", "Self-hosted sync from Plaud (via docker compose)."),
    Step("plaud_otp", "Connect Plaud", "guide",
         "Log into Riffado (email OTP), then paste its API key into the Riffado field above.",
         "http://127.0.0.1:3000"),
    Step("launchd", "Background services", "auto",
         "Schedule the worker and keep the dashboard always-on."),
]

STEPS_BY_ID: dict[str, Step] = {s.id: s for s in ALL_STEPS}

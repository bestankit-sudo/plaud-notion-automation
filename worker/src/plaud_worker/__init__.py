"""plaud_worker — local worker that turns Riffado-synced Plaud recordings into
Circleback-style meeting notes in Notion.

Pipeline (built incrementally):
    Riffado read API → local Whisper + diarization → voiceprint identification
    → OpenAI structuring → Notion writer (Circleback template) → SQLite ledger
"""

__version__ = "0.1.0"

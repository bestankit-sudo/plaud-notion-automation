"""Multilingual transcription — preserve each speaker's spoken language.

Whisper detects ONE language per file (from the opening seconds), so a meeting
that starts in English gets the rest — including Chinese / Hindi speech —
*translated* to English. To keep the transcript in the original language, we
transcribe per diarization speaker-block with per-block language auto-detection,
then clean the result (collapse repetition loops, drop noise-language fragments).

This is ~2x slower than single-pass, so the pipeline only uses it for meetings
that `is_multilingual()` flags; monolingual meetings stay on the fast path.
"""

from __future__ import annotations

import re
from collections import Counter

from .models import TranscriptTurn

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"

# scripts we expect; the output script is the most reliable language signal
_CJK = ("一", "鿿")        # Chinese
_DEVANAGARI = ("ऀ", "ॿ")  # Hindi
_ARABIC = ("؀", "ۿ")      # Urdu/Arabic — almost always a misdetect here

GAP_MERGE = 1.0    # merge same-speaker turns separated by < 1s
MIN_BLOCK = 1.5    # absorb sub-1.5s blocks into the previous one for context
MIN_CLIP_S = 0.4   # skip clips shorter than this


def _count(s: str, lo: str, hi: str) -> int:
    return sum(1 for c in s if lo <= c <= hi)


def _collapse_repeats(s: str) -> str:
    """Collapse a repeated unit (word, phrase, or character run) occurring 3+
    times in a row to a single instance — '他们他们他们...' -> '他们',
    'terminal terminal terminal' -> 'terminal', 'Let us go Let us go' ->
    'Let us go'. Whisper loops on short/noisy clips; this removes the loop while
    keeping the real content. The 40-char window covers multi-word phrase loops."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(.{1,40}?)\1{2,}", r"\1", s)
    return s.strip()


def merge_blocks(turns: list, gap: float = GAP_MERGE, min_block: float = MIN_BLOCK) -> list[dict]:
    """Merge consecutive same-speaker diarization turns into blocks long enough
    for reliable per-block language detection + transcription."""
    ordered = sorted(turns, key=lambda t: t.start)
    blocks: list[dict] = []
    for t in ordered:
        if blocks and t.speaker == blocks[-1]["speaker"] and t.start - blocks[-1]["end"] < gap:
            blocks[-1]["end"] = t.end
        else:
            blocks.append({"start": t.start, "end": t.end, "speaker": t.speaker})
    out: list[dict] = []
    for b in blocks:
        if out and (b["end"] - b["start"]) < min_block and (b["start"] - out[-1]["end"]) < gap:
            out[-1]["end"] = b["end"]
        else:
            out.append(b)
    return out


# Whisper hallucinates short, isolated non-English clips into nonsense. Drop a
# non-English block unless it carries enough script to be real content. Chinese
# is dense (a few characters can be a full clause), Devanagari needs more.
_MIN_CJK = 3
_MIN_DEVA = 10


def _clean(text: str, lang: str) -> tuple[str, str] | None:
    """Clean a block's text and resolve its language from the output script.
    Returns (text, lang) or None to drop the block (noise / misdetect)."""
    txt = _collapse_repeats(text.strip())
    if not txt:
        return None
    cjk = _count(txt, *_CJK)
    deva = _count(txt, *_DEVANAGARI)
    arab = _count(txt, *_ARABIC)
    # script overrides the detected label — it's what was actually written
    if cjk:
        return (txt, "zh") if cjk >= _MIN_CJK else None
    if deva:
        return (txt, "hi") if len(txt) >= _MIN_DEVA else None
    if arab:
        # Arabic script in these meetings is a Hindi/Chinese misdetect — drop it
        return None
    if lang not in ("en", "zh", "hi") and len(txt) < 25:
        return None  # short fragment in an unexpected language => noise
    return txt, ("en" if lang not in ("en", "zh", "hi") else lang)


def _transcribe_clip(clip, model: str, language: str | None = None):
    import mlx_whisper

    return mlx_whisper.transcribe(
        clip, path_or_hf_repo=model, language=language,
        condition_on_previous_text=False, compression_ratio_threshold=2.4,
        no_speech_threshold=0.6,
    )


# Languages where per-block transcription is worth its noise: dense non-Latin
# scripts that a single English pass *translates away entirely*. Chinese
# qualifies. Hindi/Hinglish does NOT — single-pass gives a readable English
# transcript, while per-block produces ~44% loop/garble junk on the noisy,
# rapidly code-switched audio (see git history). So Hindi-only meetings stay on
# the fast path.
PER_BLOCK_LANGS = {"zh"}


def detect(audio, blocks: list[dict], *, model: str = DEFAULT_MODEL,
           n_sample: int = 20, min_foreign_frac: float = 0.20,
           min_foreign: int = 3) -> tuple[bool, str | None]:
    """Sample a spread of blocks and decide if per-block transcription is worth
    it. Returns (use_per_block, secondary_language). Only a dense non-Latin
    secondary (PER_BLOCK_LANGS, i.e. Chinese) triggers the per-block path.

    Trigger requires the secondary to be a *substantial share* of the meeting,
    not just present: at least `min_foreign` content blocks AND at least
    `min_foreign_frac` of all content blocks. A count-only threshold flags
    English-dominant factory meetings that carry a few stray Chinese technical
    terms (~6-16% Chinese) — single-pass already transcribes those correctly,
    so per-block there only costs 2x time. The fraction gate isolates the
    genuinely bilingual meetings (>=~20% Chinese)."""
    from collections import Counter

    from mlx_whisper.audio import SAMPLE_RATE

    usable = [b for b in blocks if (b["end"] - b["start"]) >= 1.0]
    if not usable:
        return False, None
    step = max(1, len(usable) // n_sample)
    foreign: Counter = Counter()
    content = 0  # blocks that yielded real speech (the fraction's denominator)
    for b in usable[::step][:n_sample]:
        s, e = int(b["start"] * SAMPLE_RATE), int(b["end"] * SAMPLE_RATE)
        r = _transcribe_clip(audio[s:e], model)
        cleaned = _clean(r.get("text", ""), r.get("language", "en"))
        if not cleaned:
            continue
        content += 1
        if cleaned[1] in PER_BLOCK_LANGS:
            foreign[cleaned[1]] += 1
    total = sum(foreign.values())
    if content and total >= min_foreign and total / content >= min_foreign_frac:
        return True, foreign.most_common(1)[0][0]
    return False, None


def is_multilingual(audio, blocks: list[dict], **kw) -> bool:
    return detect(audio, blocks, **kw)[0]


def transcribe_blocks(audio, blocks: list[dict], *, model: str = DEFAULT_MODEL,
                      secondary: str | None = None) -> list[TranscriptTurn]:
    """Per-block transcription with per-block language detection + cleanup.

    A block whose auto-detected language falls outside {English, secondary} is
    re-transcribed forcing the meeting's `secondary` language — Whisper's stray
    third-language mis-detections (Spanish/Korean/Urdu on accented Hindi/Chinese)
    are the main source of garbage, and forcing the real language fixes them.
    Returns speaker-labelled turns, coalescing consecutive same-speaker blocks."""
    from mlx_whisper.audio import SAMPLE_RATE

    # Languages we actually support — keep these as detected. Anything else is a
    # mis-detect (stray Spanish/Korean on accented speech) and gets re-transcribed
    # in the meeting's real secondary language. A genuine Hindi block in a Chinese
    # meeting stays Hindi (never force-translated to Chinese).
    real = {"en", "zh", "hi"}
    turns: list[TranscriptTurn] = []
    for b in blocks:
        s, e = int(b["start"] * SAMPLE_RATE), int(b["end"] * SAMPLE_RATE)
        clip = audio[s:e]
        if len(clip) < SAMPLE_RATE * MIN_CLIP_S:
            continue
        r = _transcribe_clip(clip, model)
        lang = r.get("language", "en")
        if secondary and lang not in real:
            # re-transcribe in the meeting's real secondary language
            r = _transcribe_clip(clip, model, language=secondary)
            lang = secondary
        cleaned = _clean(r.get("text", ""), lang)
        if not cleaned:
            continue
        txt, _lang = cleaned
        if turns and turns[-1].speaker == b["speaker"]:
            turns[-1].text = f"{turns[-1].text} {txt}".strip()
        else:
            turns.append(TranscriptTurn(speaker=b["speaker"], text=txt))
    return turns


def lang_mix(turns: list[TranscriptTurn]) -> dict[str, int]:
    """Rough per-language turn count (by dominant script) — for logging."""
    mix: Counter = Counter()
    for t in turns:
        if _count(t.text, *_CJK):
            mix["zh"] += 1
        elif _count(t.text, *_DEVANAGARI):
            mix["hi"] += 1
        else:
            mix["en"] += 1
    return dict(mix)

# Design: Clone-and-run setup wizard + Local/Notion destinations + provider picker

Date: 2026-06-25
Status: Approved (brainstorming complete)
Owner: self

## 1. Goal

Turn `plaudautomation` from a personal, single-machine automation into something
a recipient can **clone, run, and self-serve**: running the repo opens a local
web app whose first run is a **setup wizard**, after which the same app is a
**notes viewer**. During setup the user chooses where finished meeting notes
land — **Notion** (cloud) or **Local** (an on-disk SQLite store viewed in the
app) — and which **AI provider/model** writes the summaries.

Scope is bounded to **Apple-Silicon Macs only** (the existing local Whisper +
launchd stack is unchanged). Non-Mac support, local LLM summaries, and a native
desktop bundle are explicitly out of scope (§14).

## 2. Decisions (locked)

| Area | Decision |
|---|---|
| "Local" output | SQLite store (`state/notes.db`) + a web viewer in the same app |
| Audience / OS | Apple-Silicon Macs only; wizard hard-checks hardware and refuses elsewhere |
| Form factor | One local web app: first run = wizard, after = viewer |
| Setup scope | Full auto-installer (shells out to brew/docker/pip, generates Riffado secrets) with live logs + manual-command fallback + Test buttons |
| Destination | Single-select **Notion** or **Local** (abstraction supports both; v1 offers one) |
| Speaker naming | Opt-in toggle at config; starts at `Guest N`; viewer has a "listen to snippet → name" panel that back-fills past + future pages |
| AI provider | Pick **OpenAI** or **Anthropic** + model, with a live cost estimate; only the chosen provider's key is then required |
| Architecture | `Destination` + `Summarizer` interfaces in the worker; web app in a separate top-level `app/` |

## 3. Architecture

Three new pieces + small, surgical worker changes. The worker never imports the
web app; the web app calls the worker as a library.

```
plaudautomation/
├── run                              # NEW · bootstrap launcher ("double-click")
├── app/                             # NEW · local web app (wizard + viewer)
│   ├── server.py                    #   FastAPI: wizard API, viewer API, SSE log stream
│   ├── setup/                       #   install/detect/test actions (brew, docker, pip, riffado, keys)
│   └── web/                         #   static HTML + vanilla JS (no build step)
└── worker/src/plaud_worker/
    ├── destinations/                # NEW · Notion-vs-Local abstraction
    │   ├── base.py                  #   Destination protocol
    │   ├── notion.py                #   wraps today's NotionWriter
    │   └── local.py                 #   writes to state/notes.db + media
    ├── summarizers/                 # NEW · OpenAI-vs-Anthropic abstraction
    │   ├── base.py                  #   Summarizer protocol
    │   ├── openai.py                #   wraps today's structure.py call
    │   └── anthropic.py             #   official `anthropic` SDK, messages.parse() + Pydantic
    ├── appconfig.py                 # NEW · reads/writes state/config.json (non-secret settings)
    ├── pipeline.py                  # CHANGED · writes via destination; summarizes via summarizer
    ├── ledger.py                    # CHANGED · per-destination refs
    └── config.py                    # CHANGED · provider/Notion creds conditional on choices
```

**Boundary rule:** the pipeline never knows which destination or provider it's
using — it calls `Destination.publish()` and `Summarizer.summarize()`. Adding a
third of either is a one-file job.

## 4. Destination abstraction

```python
# destinations/base.py
class Destination(Protocol):
    name: str  # "notion" | "local"
    def publish(self, meeting: Meeting, *, prior_ref: str | None) -> str:
        """Create or update this meeting's note. Returns a stable ref
        (Notion page id / local row id) stored in the ledger for idempotent reruns."""
```

- **`NotionDestination`** — thin wrapper over today's
  `NotionWriter.create_meeting_page` (zero behavior change to existing output).
- **`LocalDestination`** — upserts the `Meeting` into `state/notes.db` and ensures
  the audio sits in the media dir. `Meeting.to_dict()` already exists, so this is
  mostly a SQL upsert.

Pipeline write-point (`pipeline.py:152-157`) changes from "construct
NotionWriter" to "loop over `get_destinations(settings)` and `publish()` each,
recording each ref."

## 5. Local notes store + media

Second SQLite DB, `state/notes.db` (separate from ledger/voiceprint DBs):

```
meetings(recording_id PK, title, recorded_at, duration_ms, source_url,
         audio_rel_path, overview_json, sections_json, action_items_json,
         attendees_json, transcript_json, updated_at)
```

JSON columns mirror `Meeting.to_dict()` — trivial round-trip, queryable enough
for the viewer's list/search; re-render just re-upserts the row. Audio already
lives at `state/audio/{rid}.mp3`; the viewer serves it directly.

## 6. Summarizer abstraction + provider/model picker

```python
# summarizers/base.py
class Summarizer(Protocol):
    def summarize(self, transcript_text: str, *, title: str,
                  participants: list[str]) -> tuple[str, list[str], list[Section], list[ActionItem]]:
        """Returns (title, overview, sections, action_items). Always English output."""
```

- **`OpenAISummarizer`** — wraps today's `structure.py` call.
- **`AnthropicSummarizer`** — official `anthropic` SDK via `client.messages.parse()`
  against a Pydantic schema (title / overview / sections / action_items).
  Structured outputs, no prompt-prefill. Default model `claude-opus-4-8`.

Config gains `SUMMARIZER_PROVIDER` + `SUMMARIZER_MODEL`. The required key becomes
`ANTHROPIC_API_KEY` **or** `OPENAI_API_KEY_*` depending on the choice.

### Model picker + live cost estimate (wizard step)

Cost basis: a typical ~30-min meeting ≈ **~8K input + ~1.5K output tokens**.
Per-meeting and per-100-meetings, cheapest → priciest:

| Provider | Model | $/1M (in / out) | Per mtg | Per 100 | Tier |
|---|---|---|---|---|---|
| OpenAI | gpt-5 nano | 0.05 / 0.40 | ~$0.001 | ~$0.10 | ultra-budget (lowest quality) |
| OpenAI | gpt-5.4 nano | 0.20 / 1.25 | ~$0.003 | ~$0.35 | ultra-budget |
| OpenAI | gpt-5 mini | 0.25 / 2 | ~$0.005 | ~$0.50 | budget |
| OpenAI | gpt-5.4 mini | 0.75 / 4.50 | ~$0.013 | ~$1.28 | budget |
| Anthropic | claude-haiku-4-5 | 1 / 5 | ~$0.016 | ~$1.55 | budget |
| OpenAI | gpt-5 | 1.25 / 10 | ~$0.025 | ~$2.50 | balanced |
| OpenAI | gpt-5.4 | 2.50 / 15 | ~$0.043 | ~$4.25 | balanced — great value |
| Anthropic | claude-sonnet-4-6 | 3 / 15 | ~$0.047 | ~$4.65 | **best value (rec)** |
| Anthropic | claude-opus-4-6 | 5 / 25 | ~$0.078 | ~$7.75 | top (prev-gen) |
| Anthropic | claude-opus-4-7 | 5 / 25 | ~$0.078 | ~$7.75 | top (prev-gen) |
| Anthropic | claude-opus-4-8 | 5 / 25 | ~$0.078 | ~$7.75 | **top quality (default)** |
| OpenAI | gpt-5.5 | 5 / 30 | ~$0.085 | ~$8.50 | flagship |
| OpenAI | gpt-5.5 Pro | 30 / 180 | ~$0.51 | ~$51 | premium |

Notes:
- Default selection **claude-opus-4-8**; **claude-sonnet-4-6** flagged "best value."
- Nano tiers produce noticeably weaker meeting notes — picker marks them "lowest
  quality"; practical floor for clean notes is the budget tier.
- Opus 4.7 / 4.6 are the same price as 4.8 (lower capability) — offered for pinning.
- Advanced/premium also available behind an expander: gpt-5 Pro, gpt-5.4 Pro, gpt-5.2.
- OpenAI batch/cached-input discounts do **not** apply (one unique transcript per poll).
- Anthropic prices are authoritative (claude-api reference, 2026-06-04); OpenAI prices
  fetched live (aipricing.guru, 2026-06-25). The wizard renders the table from a small
  price map kept in the repo so numbers don't silently drift.

## 7. Config & secrets decoupling

So a stranger's clone works without the owner's central store:

- **Non-secret settings** → `state/config.json` (new `appconfig.py`): `destination`,
  `speaker_naming_enabled`, `summarizer_provider`, `summarizer_model`,
  `notion_parent_page_id`, paths. Written by the wizard, resumable.
- **Secrets** → `worker/.env` (already gitignored, already loaded by `config.py`).
- Central `~/.config/env-variables/secrets.env` remains an **optional override** if
  present (owner's machine keeps working unchanged).
- **Conditional required keys:** Notion token/page required only if destination
  includes Notion; `ANTHROPIC_API_KEY` vs `OPENAI_API_KEY_*` required per provider
  choice. Local-only + Anthropic setups need no Notion creds and no OpenAI key.

Keys stay server-side only (app bound to `127.0.0.1`); nothing secret ships to the
browser.

## 8. The web app — bootstrap, wizard, viewer

**`./run` launcher** (solves the bootstrap paradox — the wizard is itself Python):
1. Assert macOS + `arm64`; else exit with a clear message.
2. Ensure Homebrew → python3 → `worker/.venv` with a **minimal** server dep set
   (fastapi + uvicorn only — boots in seconds).
3. Launch uvicorn, open `http://127.0.0.1:8787`. Heavy ML deps are installed **by
   the wizard** with streamed logs, so first boot is fast.

**Wizard (first run)** — each step = detect → auto-run if missing → Test:
1. Hardware check (arm64, macOS, disk).
2. System deps: `brew install ffmpeg`; Docker Desktop is a GUI app → guide + Test.
3. Python ML deps: `pip install -r worker/requirements-ml.txt` (streamed via SSE).
4. Riffado: auto-generate secrets (`openssl`), `docker compose up` from
   `deploy/riffado/`, then the one human-only step — Plaud email-OTP login in the
   Riffado tab — then Test (polls Riffado API).
5. **Destination:** Local (default, zero extra keys) or Notion (token + parent page;
   offer to auto-create the parent page via the Notion API).
6. **AI provider/model:** pick OpenAI or Anthropic + model (cost table from §6);
   paste the chosen provider's key; HF token (required once for pyannote) + Test.
7. **Speaker-naming opt-in** toggle.
8. Schedule: generate the launchd plist with correct absolute paths and load it
   (or "I'll run it manually").
9. Finish → kick off first sync → redirect to viewer.

Each step persists to `state/config.json`; re-running `./run` resumes at the first
incomplete step.

**Viewer (after setup):** searchable meeting list (destination badge) → detail with
audio player, overview, sections, action items + owners, attendees, transcript.
"Sync now" button. Reads from `state/notes.db`.

## 9. Speaker-naming opt-in flow

When the toggle is **on**, the viewer shows an **"Unknown voices"** panel:
- Lists recurring unidentified speakers (Guest/Speaker N) with a stitched ~25s
  snippet (reuses `scripts/snippet_unknowns.py` logic) + an audio player.
- User types a name → enrolls voiceprint + renames (reuses
  `scripts/rename_speaker.py` / the voiceprint store) → re-renders affected meetings
  to whichever destination is active (the `state/meetings/` cache makes this cheap —
  no re-transcribe).
- New recordings keep matching that person going forward; library grows from naming.

When **off**: diarization still labels turns, but everyone stays `Guest N` and the
panel is hidden.

## 10. Idempotency & re-render

- New `destination_refs(recording_id, destination, ref, updated_at)` table in the
  ledger; existing `processed` table keeps status. (`notion_page_id` column stays for
  back-compat.)
- Reruns update in place — Local upserts by `recording_id`, Notion updates the page id.
- Rename back-fill re-renders affected meetings to the active destination from the
  cached `Meeting`.

## 11. Error handling (auto-installer)

- Every auto-step streams stdout/stderr to the browser (SSE); on non-zero exit it
  shows the exact command + Copy + Retry, never a half-state.
- Docker Desktop and Plaud-OTP are guide+Test by nature (can't fully automate a GUI
  app install or an OTP entry).
- Re-running `./run` resumes at the first incomplete step (state-driven + live checks).

## 12. Testing strategy

- Unit: `LocalDestination.publish` (Meeting → DB → read-back round-trip);
  destination selection from config (local-only needs no Notion creds);
  `destination_refs` upsert idempotency.
- Unit: `Summarizer` selection from config; `AnthropicSummarizer` returns the 4-tuple
  shape (mock the SDK); provider-conditional key requirements.
- Unit: wizard detect/test functions (hardware check, tool presence) with fakes.
- API: viewer list/detail/audio endpoints against a seeded `notes.db`.
- Flow: rename back-fill updates both DB rows and re-renders.
- Smoke: `./run` boots the server; hardware-check endpoint responds.

## 13. Privacy

In **Local** mode, audio *and* notes never leave the machine — stronger than the
current Notion-egress exception. The only egress is transcript text → the chosen AI
provider (summaries) and a one-time pyannote download from HuggingFace. The wizard
states this plainly per destination/provider.

## 14. Out of scope

- Fully-offline summaries (local LLM instead of OpenAI/Anthropic).
- Non-Mac / non-Apple-Silicon support.
- A native desktop bundle (Electron/Tauri).
- Enabling Local + Notion simultaneously (abstraction supports it; v1 is single-select).

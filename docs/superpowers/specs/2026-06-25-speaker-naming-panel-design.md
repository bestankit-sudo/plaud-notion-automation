# Speaker-Naming Panel (Plan 2c) — Design

> Produced by an ultracode understand+design workflow (6 subsystem mappers → 3 independent designs → judge synthesis → adversarial critic), verified against the live code. Run: `wf_d5225c92-228`.

## The key fact (verified against the code)
`voiceprints.db` is already the system of record for voice→name, and `identify_speakers(diar, store, threshold=0.75)` already runs on **every** recording at [pipeline.py:133](worker/src/plaud_worker/pipeline.py#L133). **So enrolling a named voice auto-labels all FUTURE meetings with zero new matching code.** The whole feature is: give the user a way to attach a name to a voice (enroll its embedding) and read back who's who.

- `VoiceprintStore.enroll(name, embedding)` — normalizes + stores a prototype + folds into a running-average centroid.
- `VoiceprintStore.match(embedding, *, threshold)` → `(name|None, score)`, prototype-first.
- `VoiceprintStore.rename(old, new)` — rename, merging via weighted average if `new` exists.
- `VoiceprintStore.names()` → `[(name, n)]`.
- Live DB: 8 named voiceprints, 44 prototype rows. `name` is the TEXT PRIMARY KEY (keep it — GAP option a; no schema migration).

## The one hard problem
There is **no stored link** between the on-screen display name (`Guest 1` / real name, in `notes.db`) and the anonymous `SPEAKER_XX` label that owns the embedding + timing (in `diar_full`). Naming a voice needs that bridge. Phase 1 recomputes it on demand (driven off label + a live `match()` so it can't mislead); Phase 2 persists it.

## Critical implementation constraints (verified)
- **Keep the viewer credential-free.** `torch`/`pyannote` import lazily inside `diarize()` ([diarize.py:55](worker/src/plaud_worker/diarize.py#L55)), so importing `diarize_cached`/`identify_speakers` is safe (numpy+stdlib) **as long as `diarize()` is never called at request time** (read the `diar_full` JSON cache only). BUT `pipeline._display_names` drags the summarizer/riffado import stack — **do not import it**; factor its ~12-line guest-numbering into a pure module imported by both `pipeline.py` and the viewer. **This is the single most important wiring decision.**
- `VoiceprintStore` uses a bare `sqlite3.connect` — open a short-lived store per request (like `NotesStore` in `server.py`) and serialize naming writes with a single-writer lock.
- **Enroll from `diar_full.embeddings[label]`** (the true 256-d L2-normalized pyannote vector) — **never** a vector re-extracted from the audio snippet. The snippet is for human listening only; this structurally prevents library poisoning.
- `ffmpeg`: resolve via `shutil.which` + clear 500 if missing (the launchd-ffmpeg silent-failure mode is a known risk; the web app runs in a different context). Snippets are on-demand so they never block the pipeline.

---

## Phase 1 — MVP "Speaker Key" panel (local-first, low-risk, sound)
The critic rated Phase 1 **sound and shippable**. Scope: name voices in the **current** meeting + future meetings auto-label. No legacy back-fill, no Notion writes from the viewer, no Undo — which sidesteps every must-fix the critic raised (all of which are Phase-2 concerns).

**Endpoints** (all gated on `AppConfig.speaker_naming_enabled` — its first real consumer):
- `GET /api/speakers` → `{speakers:[{name, samples, updated_at}]}` (`store.names()`) — library overview + autocomplete; flags `n<5` as "needs more samples".
- `GET /api/meetings/{rid}/speakers` → `{recording_id, threshold:0.75, speakers:[{label, display, source, score, enrolled, sample_count, total_speech_sec, snippet:{start,end}}]}`. Reads `diar_full` for timing+embeddings, `store.match(emb, threshold=0.0)` for the nearest-name hint. Driven off label + live match so a stale cached transcript can't mislead. Speakers with no `SPEAKER_XX` label / no embedding are excluded (not offered a broken "name this voice").
- `GET /api/audio/{rid}/snippet?label=SPEAKER_01` → `FileResponse audio/mpeg`. Validate `label` against `^SPEAKER_\d+$` AND presence in `diar_full.embeddings` before it reaches ffmpeg/fs; lift `snippet_unknowns._extract` verbatim (longest turns up to ~25s / 8 segments); cache to `state/snippets_panel/`; reuse `get_audio`'s traversal guard.
- `POST /api/meetings/{rid}/speakers/{label}/name` body `{name}` → `store.enroll(name, diar_full[label])` (idempotency-guarded: same name + already-high score = skip-enroll no-op); update THIS meeting's local display (`notes.db` via `NotesStore.upsert` + `meetings/{rid}.json`); append to `state/speaker_log.jsonl`. **Scoped to this rid only; no Notion write.**

**UI** (inline in `app/web/app.js loadDetail`, vanilla JS, `textContent`-safe): a collapsible "Speaker Key" card above the transcript — one chip per speaker (enrolled solid; Guest/unknown with a "name this voice" affordance + nearest hint "sounds like Akash Jain 0.61" and a "< 0.75 needed to auto-label" note). Each transcript speaker label becomes clickable → inline panel with `<audio controls>` (src set lazily on open so ffmpeg runs only on demand), the best-match line, a name `<input>` backed by a `<datalist>` from `/api/speakers`, Save/Cancel. On Save → POST, optimistic relabel, re-fetch chips.

**Tests** (`app/tests/test_viewer_api.py`): response shape vs a fixture `diar_full`+`voiceprints.db`; snippet label-validation + traversal guard; enroll writes a prototype + rewrites ONLY the target rid (assert other meetings untouched); no audio egress.

**Reuses:** `enroll/match/names`, `identify_speakers`, the factored-pure `_display_names`, `diar_full` JSON, `snippet_unknowns._extract`, `NotesStore`, `get_audio` traversal guard, `app.js loadDetail`, `speaker_naming_enabled`.

---

## Phase 2 — durability (deferred; critic verdict: NEEDS_REVISION on 3 must-fixes)
Adds: persisted `state/labelmap/{rid}.json` bridge written at pipeline time + lazy reconstruction for the ~36 legacy meetings; identity-keyed **async back-fill** across all meetings on enroll/rename; `scope:'all'|'this'`; `POST /api/speakers/rename`; `VoiceprintStore.delete_prototype` + Undo via `speaker_log.jsonl`.

**Must resolve before building Phase 2 (from the adversarial critic):**
1. **Notion back-fill vs the credential-free viewer** — re-publishing to Notion needs the Notion token + `ledger.db` page-id mapping, which the read-only viewer must not hold. **Delegate cloud re-publish to the worker process**; don't load the secret into `server.py`.
2. **Legacy labelmap reconstruction** must replay `label_segments` + `_display_names` over `diar_full` (not a transcript-order heuristic); unalignable speakers default to **play-only / non-enrollable** to prevent wrong-embedding enrollment (poisoning).
3. **Undo must snapshot/restore the centroid** (not just delete a prototype — `enroll` already mutated the running average); the enroll endpoint must enforce the idempotency precondition explicitly (the store has no dedup); add within-meeting 1:1 collision handling (two labels → same name) and transactional consistency across the 4 caches the async sweep mutates.

## Open decisions (recommended defaults)
1. **Persisted labelmap now or on-demand only?** → Phase 1 on-demand (label+live-match); Phase 2 persisted bridge.
2. **Back-fill scope default?** → `'all'` async (Phase 2), keyed on label-identity re-match (never raw string-replace).
3. **Re-publish to Notion on naming?** → names yes (consistent with `rename_speaker.py` + the audio-to-Notion egress exception), **but** via the worker, never the viewer; snippet audio + embeddings stay strictly on 127.0.0.1.
4. **Mis-match recovery?** → Phase 2 (`delete_prototype` + centroid-snapshot Undo).

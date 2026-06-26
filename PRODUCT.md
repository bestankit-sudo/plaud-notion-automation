# Product

## Register

product

## Users

Two audiences, one local app (runs on 127.0.0.1, single user at a time):
- **The owner** — a developer running this as a personal Mac-local automation. Comfortable in a terminal, but wants the day-to-day to be effortless.
- **Recipients** — less-technical people the owner shares the cloned repo with. Their first contact is the setup wizard on their own Mac; they should get to "it works" without hand-holding.

Context of use: a one-time **setup wizard** (install the local pipeline + configure destination/AI/keys), then ongoing **note viewing** (browse meeting notes, play audio, name the voices in the Speaker Key).

## Product Purpose

Turns Plaud voice recordings into structured meeting notes — in Notion or fully local — **entirely on the user's Mac**. Audio is transcribed (MLX Whisper on the Apple GPU), speakers are separated and recognized (pyannote + on-device voiceprints), and an LLM structures the notes. Success: a recipient can clone, run `./run`, and be processing notes with no friction; and the owner trusts that raw audio and biometric voiceprints never leave the machine.

## Brand Personality

Warm, approachable, reassuring. Plain-spoken and human — softer copy over jargon, a calm guide rather than a technical console. Quietly confident about privacy: "this stays on your Mac" is the emotional throughline. Three words: **warm, trustworthy, unfussy**.

## Anti-references

- **SaaS marketing aesthetics** — no hero sections, no tiny tracked-uppercase eyebrows, no gradient CTAs, no testimonial/feature-card grids. This is a tool, not a landing page.
- **Heavy enterprise dashboard** — no cramped data-grid chrome, no border-heavy panels stacked in dense columns, no "admin console" coldness.
- Cross-register bans still apply: no gradient text, no decorative glassmorphism, no side-stripe accent borders.

## Design Principles

1. **Reassure as you go.** Every step explains why it's needed and what stays on the machine — privacy is the feature, surfaced not buried.
2. **Plain human language.** A non-technical recipient should never feel lost; prefer "name a voice" over "enroll an embedding."
3. **Calm warmth, not flair.** Warmth comes from color, type, and copy — never from marketing tropes or visual density.
4. **Honest state.** Clear done / pending / running, real streamed logs, no fake progress or empty spinners.
5. **Local-first dignity.** It should feel like a trustworthy desktop companion, not a cloud product.

## Accessibility & Inclusion

WCAG AA: body text ≥ 4.5:1 contrast (no light-gray-on-tint), large/bold ≥ 3:1; visible keyboard focus on every control; honor `prefers-reduced-motion`; fully operable keyboard-only. Status must never be conveyed by color alone (pair the badge text with the color).

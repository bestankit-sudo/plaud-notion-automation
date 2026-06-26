---
name: plaudautomation
description: Warm, local-first UI for turning voice recordings into meeting notes on your Mac
colors:
  bg: "#fdfaf6"
  surface: "#ffffff"
  surface-2: "#f7f3ed"
  ink: "#241e1a"
  ink-muted: "#635951"
  accent: "#b15229"
  accent-strong: "#9e3e0e"
  accent-ink: "#8a3915"
  accent-tint: "#ffe9db"
  success: "#287c42"
  success-ink: "#195c2e"
  success-tint: "#d9f6dd"
  danger: "#bd3931"
  danger-ink: "#a12721"
  border: "#e3dfda"
  border-strong: "#d2cdc5"
typography:
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, system-ui, 'Segoe UI', Roboto, sans-serif"
    fontSize: "24px"
    fontWeight: 650
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 650
    lineHeight: 1.3
    letterSpacing: "-0.012em"
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "0.05em"
  mono:
    fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
rounded:
  sm: "8px"
  md: "12px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "28px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    rounded: "{rounded.sm}"
    padding: "11px 20px"
  button-primary-hover:
    backgroundColor: "{colors.accent-strong}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.accent-ink}"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  button-secondary-hover:
    backgroundColor: "{colors.accent-tint}"
    textColor: "{colors.accent-ink}"
  badge-success:
    backgroundColor: "{colors.success-tint}"
    textColor: "{colors.success-ink}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  badge-neutral:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.md}"
    padding: "14px 16px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
---

# Design System: plaudautomation

## 1. Overview

**Creative North Star: "The Warm Workbench"**

plaudautomation is a tool you run on your own Mac — a calm, warm workbench where your recordings become notes and never leave the machine. The interface should feel like a trustworthy desktop companion that reassures as it works, not a cloud product trying to sell itself. Warmth comes from a clay accent, warm off-white surfaces, and plain-spoken copy — never from decoration. The default posture is restraint: one accent, tonal warm neutrals, generous breathing room, and honest state.

It explicitly rejects two things. First, **SaaS marketing aesthetics** — no hero sections, no tiny tracked-uppercase eyebrows, no gradient CTAs or testimonial grids; this is a tool, not a landing page. Second, **heavy enterprise-dashboard density** — no cramped data-grid chrome, no border-heavy panels stacked in cold columns. The line it walks: warm and human without ever becoming a playful consumer toy.

**Key Characteristics:**
- One warm clay accent, used only for primary actions, selection, and state.
- Warm tonal neutrals (page → surface → panel), depth by layering before shadow.
- Plain human copy ("name a voice", not "enroll an embedding"); privacy stated, not buried.
- WCAG AA throughout: every text pair ≥ 4.5:1, visible focus, reduced-motion honored.
- System fonts only — no webfont fetch (the app runs offline, local-first).

## 2. Colors

A warm clay-and-paper palette: one earthy terracotta accent over warm off-whites, with green and red reserved for true state. **Canonical values are OKLCH** (see `app/web/style.css` `:root`); the hex in the frontmatter is a faithful sRGB approximation for tooling.

### Primary
- **Clay** (`#b15229` / `oklch(0.55 0.135 42)`): primary action buttons (Install, Finish setup, Save), the selection underline on tabs, the header mark, and focus rings. **Clay Deep** (`#9e3e0e`) is its hover. **Clay Ink** (`#8a3915`) is the readable accent text on light surfaces (secondary-button labels, links). **Clay Tint** (`#ffe9db`) fills selected rows, the step-number chips, and the destination badge.

### Neutral
- **Warm Paper** (`#fdfaf6`): the page background — a near-white with a hint of warmth, kept above the cream band so it never reads as parchment slop.
- **Surface** (`#ffffff`): cards, inputs, fieldsets, the header bar.
- **Panel** (`#f7f3ed`): the secondary layer — the meetings sidebar, code chips, neutral badges.
- **Ink** (`#241e1a`): body and headings (15.8:1 on Paper).
- **Muted Ink** (`#635951`): meta, hints, durations, the "Why/How" labels — **6.5:1 on Paper**, deliberately not the light gray that fails AA.

### State
- **Green** (`#287c42`) + **Green Tint** (`#d9f6dd`): the "done" / "enrolled" badges and success status.
- **Red** (`#bd3931` / Ink `#a12721`): errors and failed connection tests only.

### Named Rules
**The One Clay Rule.** The clay accent marks action, selection, and state — never decoration. If clay is filling more than a couple of elements on a screen, one of them is decoration; make it outline or neutral.

**The No-Light-Gray Rule.** Muted text is `#635951`, never a lighter gray "for elegance". Every text color is verified ≥ 4.5:1 against its surface before it ships.

## 3. Typography

**Body / Display Font:** the native system stack (`-apple-system, BlinkMacSystemFont, system-ui, "Segoe UI", Roboto, sans-serif`) — one family across headings, labels, body, and controls.
**Mono Font:** `ui-monospace, "SF Mono", Menlo, monospace` — install logs and inline `code` only.

**Character:** unfussy and familiar. On Apple hardware this is SF; it disappears into the task, which is exactly right for a tool. No font is fetched — local-first means no network for type.

### Hierarchy
- **Headline** (650, 24px, 1.2, -0.02em): the meeting title in the viewer. `text-wrap: balance`.
- **Title** (650, 17px, -0.012em): the header wordmark, section/fieldset legends.
- **Body** (400, 15px, 1.55): notes, transcript, descriptions. Prose capped at ~65–72ch.
- **Label** (700, 11px, +0.05em, UPPERCASE): the "Why it's needed" / "How" mini-labels only.
- **Mono** (400, 12px): the streamed install log and `code`.

### Named Rules
**The Fixed-Scale Rule.** Sizes are fixed px/rem, never `clamp()` fluid — a tool is viewed at consistent DPI, and a heading that shrinks in a panel looks worse, not designed.

## 4. Elevation

Mostly flat, depth by **tonal layering** first (Paper → Surface → Panel), shadow second. Cards that hold live, interactive content (install steps, the Speaker Key) get one soft shadow to lift them off the page; everything else is flat with a 1px warm border.

### Shadow Vocabulary
- **Card lift** (`box-shadow: 0 1px 2px oklch(0.4 0.02 60 / 0.05), 0 6px 20px oklch(0.4 0.02 60 / 0.05)`): install-step and speaker-key cards.
- **Primary hover lift** (`0 4px 14px oklch(0.55 0.135 42 / 0.28)` + `translateY(-1px)`): primary buttons on hover — a warm clay glow, the one place color enters a shadow.
- **Focus ring** (`0 0 0 3px oklch(0.60 0.15 42 / 0.32)`): inputs on `:focus-visible`; other controls use a 2px clay outline with 2px offset.

### Named Rules
**The Flat-Until-Live Rule.** Surfaces are flat at rest. A shadow appears to mark something live (a card you act on) or a state (hover, focus) — never as ambient decoration.

## 5. Components

### Buttons
- **Shape:** gently rounded (8px), comfortable hit area (secondary ≥ 34px tall, primary ≥ 44px).
- **Primary:** clay fill (`{colors.accent}`), white text, `11px 20px`. Hover → Clay Deep + 1px lift + warm glow. Reserved for the one decisive action on a surface (Install's "Start background services", "Finish setup", "Save").
- **Secondary (default):** white surface, 1px `border-strong`, Clay Ink text, `7px 13px`. Hover → Clay Tint fill + clay border. This is the *common* button (Re-check, Re-run, hear, Generate secrets) — calm by default so a screen of steps doesn't shout.
- **Hover / Focus:** 160ms ease-out transitions; `:focus-visible` paints a 2px clay outline. Disabled drops to 0.5 opacity, no lift.

### Tabs (signature)
Plain **text labels** with a **clay underline** marking the selected step — not buttons, no box. Selected = Ink text + 2px clay bottom-border; unselected = Muted Ink. Built as an ARIA `tablist` (arrow-key nav, one `tabpanel` visible). Used for the wizard's Step 1 / Step 2.

### Chips / Badges
- **Style:** pill (`999px`), 12px semibold, tinted fill + matching ink. Success → Green Tint/Green Ink ("✓ done", "enrolled ✓"). Neutral → Panel/Muted Ink ("● pending", "Guest"). The destination badge uses Clay Tint/Clay Ink.
- **Rule:** state is never color-only — the badge text ("done", "pending") carries the meaning; the tint reinforces it.

### Cards / Containers
- **Corner:** 12px. **Background:** Surface. **Border:** 1px `border`. **Shadow:** Card lift (interactive cards only). **Padding:** `14px 16px`.
- Install steps are a two-column card: action on the left, a "Why it's needed" + "How" panel on the right (1px divider, stacks under 760px). No nested cards.

### Inputs / Fields
- **Style:** white, 1px `border-strong`, 8px radius, `8px 10px`. Native radios/checkboxes use `accent-color` clay.
- **Focus:** border shifts to clay + a 3px clay-glow ring (`:focus-visible`). Placeholder is Muted Ink (AA, not faint gray).
- **Selected option row** (model picker): Clay Tint fill + clay border via `:has(input:checked)`.

### Navigation
The wizard's only nav is the step tablist (above). The viewer is a two-pane app shell — a warm Panel sidebar of meetings (active row = Clay Tint fill + Clay Ink title) and a content pane — collapsing to stacked panes under 860px.

## 6. Do's and Don'ts

### Do:
- **Do** keep the clay accent for action, selection, and state only — outline-secondary is the default button.
- **Do** verify every text/background pair ≥ 4.5:1 (large/bold ≥ 3:1) before shipping; muted text is `#635951`, never lighter.
- **Do** give every control a visible `:focus-visible` state and honor `prefers-reduced-motion`.
- **Do** convey depth by tonal layering (Paper → Surface → Panel) first; add a soft shadow only to lift live, interactive cards.
- **Do** write plainly and reassure ("nothing leaves the machine") — privacy is the feature, stated not buried.
- **Do** use system fonts; never fetch a webfont (the app is offline / local-first).

### Don't:
- **Don't** build SaaS-marketing furniture — no hero sections, no tiny tracked-uppercase eyebrows above sections, no gradient CTAs, no testimonial/feature-card grids.
- **Don't** drift toward enterprise-dashboard density — no cramped data-grid chrome, no border-heavy panels stacked in cold columns.
- **Don't** use gradient text (`background-clip: text`), decorative glassmorphism, or a `border-left`/`border-right` > 1px as a colored accent stripe.
- **Don't** fill a screen with clay buttons — if more than one or two are filled, the rest should be outline or neutral.
- **Don't** use `clamp()` fluid heading scales; sizes are fixed for a consistent-DPI tool.
- **Don't** convey status by color alone — pair the tint with text.

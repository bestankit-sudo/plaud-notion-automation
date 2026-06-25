# CLAUDE.md — plaudautomation

Owner: `self`. <one line: what it does>

## Stack
- —

## Run / test
- <add install / dev / test commands>

## Secrets
- Shared secrets load from the central store via `SECRETS_ENV_PATH`
  (`~/.config/env-variables/secrets.env`). Don't hardcode shared keys here; vendor
  keys are named per-org (`OPENAI_API_KEY_<ORG>`). Never put a secret behind
  `VITE_*` / `NEXT_PUBLIC_*` (those ship to the browser).

<!-- Portfolio conventions: ../portfolio-ops/registry/conventions.md -->

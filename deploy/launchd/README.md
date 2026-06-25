# Automation (launchd)

Runs the Plaud → Notion pipeline hands-free on this Mac.

`com.plaudautomation.plist` runs `worker/scripts/sync_and_reconcile.py`
**every 30 min and at login**. On a sleeping Mac, launchd defers the interval and
fires on wake — so the same job is also the boot/wake **catch-up**: it triggers a
Riffado sync (pulling anything new from Plaud), then reconciles new recordings
into Notion.

## Prerequisites

For the headless **sync trigger** (`POST /api/plaud/sync` is session-authed), add
your Riffado admin login to the shared secrets:

```
RIFFADO_ADMIN_EMAIL=...
RIFFADO_ADMIN_PASSWORD=...
```

Without these it still **reconciles** already-synced recordings — it just won't
pull new ones from Plaud itself.

## Install

```sh
cp deploy/launchd/com.plaudautomation.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.plaudautomation.plist
tail -f worker/state/automation.log
```

To stop / reload:

```sh
launchctl unload ~/Library/LaunchAgents/com.plaudautomation.plist
```

## Notes

- All localhost: the admin login is used only to call the local Riffado at
  `127.0.0.1:3000`; credentials never leave the machine.
- The reconciler is ledger-idempotent — re-runs never duplicate Notion pages.
- Real-time alternative (not required): Riffado can POST signed webhooks on
  `recording.synced` to a local receiver; the interval+wake model above already
  covers the sleeping-Mac case, so webhooks are optional.

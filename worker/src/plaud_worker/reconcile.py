"""Reconciler — process every recording that isn't in the ledger yet.

Shared by two callers:
  * back-catalog extraction (one-off catch-up over history)
  * boot/login catch-up (clear anything synced while the Mac slept)

Idempotent: a recording already marked 'processed' is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Settings
from .ledger import Ledger
from .pipeline import process_recording
from .riffado import RiffadoClient
from .voiceprints import VoiceprintStore


@dataclass
class ReconcileReport:
    processed: list[str] = field(default_factory=list)
    skipped_done: list[str] = field(default_factory=list)
    skipped_short: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"processed={len(self.processed)} "
            f"already={len(self.skipped_done)} "
            f"short={len(self.skipped_short)} "
            f"failed={len(self.failed)}"
        )


def reconcile(
    settings: Settings,
    *,
    parent_page_id: str | None = None,
    min_dur_s: int = 60,
    limit: int | None = None,
    on_event=lambda msg: None,
) -> ReconcileReport:
    store = VoiceprintStore(settings.state_dir / "voiceprints.db")
    ledger = Ledger(settings.state_dir / "ledger.db")
    report = ReconcileReport()
    skip = settings.skip_recordings()

    with RiffadoClient(settings.riffado_base_url, settings.riffado_api_key) as r:
        recordings = list(r.list_recordings())

    count = 0
    for rec in recordings:
        rid = rec["id"]
        title = rec.get("title") or rid
        if rid in skip:
            report.skipped_short.append(rid)
            continue
        existing = ledger.get(rid)
        if existing and existing.status == "processed":
            report.skipped_done.append(rid)
            continue
        if (rec.get("duration_ms") or 0) / 1000 < min_dur_s or rec.get("is_trash"):
            report.skipped_short.append(rid)
            continue
        if limit is not None and count >= limit:
            break
        count += 1
        try:
            on_event(f"processing {title[:60]}")
            process_recording(
                rid, settings, store=store, ledger=ledger,
                parent_page_id=parent_page_id, write=True,
            )
            report.processed.append(rid)
            on_event(f"  -> done: {title[:60]}")
        except Exception as e:  # noqa: BLE001 - record and continue
            ledger.upsert(rid, status="failed")
            report.failed.append((rid, str(e)))
            on_event(f"  -> FAILED {title[:50]}: {e}")

    store.close()
    ledger.close()
    return report

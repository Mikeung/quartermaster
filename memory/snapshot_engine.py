import logging
from typing import Any

from memory.store import OperationalStore

logger = logging.getLogger(__name__)


class SnapshotEngine:
    """Creates, stores, and retrieves operational snapshots.

    Snapshots are immutable once written. History is append-only.
    The engine never modifies existing records.
    """

    def __init__(self, store: OperationalStore) -> None:
        self._store = store

    def create_snapshot(
        self,
        data: dict[str, Any],
        snapshot_type: str = "full_scan",
        notes: str = "",
        target_id: str | None = None,
    ) -> int:
        snapshot_id = self._store.insert_snapshot(snapshot_type, data, notes, project_id=target_id)
        logger.info(
            "Snapshot created",
            extra={"id": snapshot_id, "type": snapshot_type, "target_id": target_id},
        )
        return snapshot_id

    def get_latest(self, snapshot_type: str = "full_scan") -> dict[str, Any] | None:
        return self._store.get_latest_snapshot(snapshot_type)

    def get_latest_for_target(
        self, target_id: str, snapshot_type: str = "full_scan"
    ) -> dict[str, Any] | None:
        """Return the most recent snapshot for a specific target.

        Only compares snapshots with the same target_id. Cross-target lookups
        must not occur — this method enforces that at the store level.
        Returns None when no prior snapshot exists for this target (first scan).
        """
        return self._store.get_latest_for_target(target_id, snapshot_type)

    def get_by_id(self, snapshot_id: int) -> dict[str, Any] | None:
        return self._store.get_snapshot_by_id(snapshot_id)

    def list_recent(
        self, snapshot_type: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self._store.list_snapshots(snapshot_type, limit)

    def get_temporal_window(
        self, days: int = 7, max_count: int = 50
    ) -> list[dict[str, Any]]:
        """Return full_scan snapshots from the last N days, oldest first."""
        return self._store.get_snapshots_in_window("full_scan", days, max_count)

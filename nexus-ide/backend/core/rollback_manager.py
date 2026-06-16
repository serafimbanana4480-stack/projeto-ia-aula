import asyncio
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4
from collections import defaultdict

logger = logging.getLogger(__name__)


def _snapshot_path(project_path: str) -> Path:
    return Path(project_path) / ".nexus" / "rollback" / "snapshots"


async def _save_json(path: Path, data: dict[str, Any]) -> None:
    def _write(p: Path, d: dict[str, Any]) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, default=str)

    await asyncio.to_thread(_write, path, data)


async def _load_json(path: Path) -> dict[str, Any]:
    def _read(p: Path) -> dict[str, Any]:
        if not p.exists():
            return {}
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    return await asyncio.to_thread(_read, path)


def _create_backup_copy(src: str, dest: str) -> None:
    src_path = Path(src)
    if src_path.exists():
        dest_path = Path(dest)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dest_path)


class RollbackManager:
    def __init__(self) -> None:
        self._snapshots: dict[str, dict[str, Any]] = {}
        self._batches: dict[str, dict[str, Any]] = {}
        self._artifact_index: dict[str, list[str]] = defaultdict(list)
        self._marker_paths: dict[str, Path] = {}

    async def record_snapshot(
        self,
        project_path: str,
        artifact_id: str,
        file_path: str,
        content_before: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        snapshot_id = str(uuid4())
        created_at = datetime.now().isoformat()
        snapshot_dir = _snapshot_path(project_path)

        snapshot: dict[str, Any] = {
            "id": snapshot_id,
            "created_at": created_at,
            "project_path": project_path,
            "artifact_id": artifact_id,
            "file_path": file_path,
            "content_before": content_before,
            "content_after": None,
            "status": "pending",
            "metadata": metadata or {},
        }

        snapshot_file = snapshot_dir / f"{snapshot_id}.json"
        try:
            await _save_json(snapshot_file, snapshot)
        except Exception as exc:
            logger.exception("Failed to persist snapshot %s: %s", snapshot_id, exc)
            raise

        self._snapshots[snapshot_id] = snapshot
        self._artifact_index[artifact_id].append(snapshot_id)
        self._marker_paths.setdefault(project_path, snapshot_dir)
        logger.info("Recorded snapshot %s for artifact %s", snapshot_id, artifact_id)
        return snapshot_id

    async def rollback_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot:
            snap_dir = self._marker_paths.values()
            marker_file = None
            for sdir in snap_dir:
                candidate = sdir / f"{snapshot_id}.json"
                if candidate.exists():
                    marker_file = candidate
                    break
            if marker_file:
                snapshot = await _load_json(marker_file)
            else:
                raise FileNotFoundError(f"Snapshot {snapshot_id} not found.")

        project_path = snapshot["project_path"]
        file_path = snapshot["file_path"]
        content_before = snapshot["content_before"]
        artifact_id = snapshot["artifact_id"]
        marker_dir = self._marker_paths.get(project_path, _snapshot_path(project_path))

        marker_file = marker_dir / f"{snapshot_id}.json"
        snapshot_path = Path(project_path) / file_path

        try:
            if snapshot_path.exists():
                await asyncio.to_thread(
                    _create_backup_copy, str(snapshot_path), str(snapshot_path) + ".bak"
                )
            await asyncio.to_thread(self._write_content, snapshot_path, content_before)
        except Exception as exc:
            logger.exception("Rollback failed for snapshot %s: %s", snapshot_id, exc)
            snapshot["status"] = "error"
            await self._persist_snapshot(marker_file, snapshot)
            raise

        snapshot["status"] = "rolled_back"
        snapshot["content_after"] = content_before
        snapshot["rolled_back_at"] = datetime.now().isoformat()
        await self._persist_snapshot(marker_file, snapshot)
        self._snapshots[snapshot_id] = snapshot
        logger.info("Rolled back snapshot %s for artifact %s", snapshot_id, artifact_id)
        return snapshot

    async def record_correction_batch(
        self,
        artifact_id: str,
        snapshot_ids: list[str],
        test_output_before: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        batch_id = str(uuid4())
        created_at = datetime.now().isoformat()
        batch_dir = _snapshot_path(artifact_id)

        unresolved = [sid for sid in snapshot_ids if sid not in self._snapshots]
        if unresolved:
            raise ValueError(
                f"Unknown snapshot ids: {unresolved}. Record snapshots before batching."
            )

        batch: dict[str, Any] = {
            "id": batch_id,
            "created_at": created_at,
            "artifact_id": artifact_id,
            "snapshot_ids": snapshot_ids,
            "test_output_before": test_output_before,
            "test_output_after": None,
            "status": "pending",
            "quality_metrics": metadata or {},
        }

        batch_file = batch_dir.parent.parent / "batches" / f"{batch_id}.json"
        try:
            await _save_json(batch_file, batch)
        except Exception as exc:
            logger.exception("Failed to persist batch %s: %s", batch_id, exc)
            raise

        self._batches[batch_id] = batch
        logger.info("Recorded correction batch %s for artifact %s", batch_id, artifact_id)
        return batch_id

    async def commit_batch(
        self,
        batch_id: str,
        test_output_after: str,
        quality_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        batch = self._batches.get(batch_id)
        if not batch:
            raise FileNotFoundError(f"Batch {batch_id} not found.")

        batch["test_output_after"] = test_output_after
        if quality_metrics:
            batch["quality_metrics"].update(quality_metrics)
        batch["status"] = "committed"
        batch["committed_at"] = datetime.now().isoformat()

        marker_dir = (
            self._marker_paths.get(batch["artifact_id"], _snapshot_path(batch["artifact_id"]))
            if "artifact_id" in batch
            else None
        )
        if marker_dir:
            for snapshot_id in batch["snapshot_ids"]:
                snap = self._snapshots.get(snapshot_id)
                if snap:
                    snap["status"] = "committed"
                    snap["content_after"] = snap.get("content_after")
                    snap["committed_at"] = datetime.now().isoformat()
                    marker_file = marker_dir / f"{snapshot_id}.json"
                    await self._persist_snapshot(marker_file, snap)

        batch_file = self._locate_batch_file(batch_id)
        if batch_file:
            try:
                await asyncio.to_thread(self._overwrite_json, batch_file, batch)
            except Exception as exc:
                logger.exception("Failed to commit batch %s: %s", batch_id, exc)
                raise

        self._batches[batch_id] = batch
        logger.info("Committed batch %s", batch_id)
        return batch

    async def auto_rollback_on_regression(
        self,
        artifact_id: str,
        quality_before: dict[str, Any],
        quality_after: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_ids = self._artifact_index.get(artifact_id, [])
        if not snapshot_ids:
            return {
                "rolled_back": False,
                "reason": "No snapshots registered for artifact.",
                "snapshot_ids": [],
            }

        regressed = self._detect_regression(quality_before, quality_after)
        if not regressed:
            return {
                "rolled_back": False,
                "reason": "No regression detected.",
                "snapshot_ids": list(snapshot_ids),
            }

        rolled: list[str] = []
        reasons: list[str] = []
        project_path = self._snapshots.get(snapshot_ids[0], {}).get("project_path")
        for snapshot_id in snapshot_ids:
            try:
                result = await self.rollback_snapshot(snapshot_id)
                status = result.get("status", "unknown")
                if status == "rolled_back":
                    rolled.append(snapshot_id)
                else:
                    reasons.append(f"Snapshot {snapshot_id} skipped with status {status}.")
            except Exception as exc:
                reasons.append(f"Failed to rollback {snapshot_id}: {exc}")

        reason = f"Regression detected: {regressed}." + (
            " Additional issues: " + "; ".join(reasons) if reasons else ""
        )
        return {
            "rolled_back": len(rolled) > 0,
            "reason": reason,
            "snapshot_ids": list(snapshot_ids),
        }

    def _detect_regression(self, before: dict[str, Any], after: dict[str, Any]) -> str | None:
        for key in ("score", "coverage", "pass_rate"):
            if key in before and key in after:
                if before[key] > after[key]:
                    return f"Metric {key} dropped from {before[key]} to {after[key]}."
        for key in ("errors", "failures", "warnings"):
            if key in before and key in after:
                if after[key] > before[key]:
                    return f"Metric {key} increased from {before[key]} to {after[key]}."
        return None

    async def _persist_snapshot(self, path: Path, data: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(self._overwrite_json, path, data)
        except Exception as exc:
            logger.exception("Failed to persist snapshot to %s: %s", path, exc)

    @staticmethod
    def _write_content(path: Path, content: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def _overwrite_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _locate_batch_file(self, batch_id: str) -> Path | None:
        for path in Path.cwd().rglob(f"{batch_id}.json"):
            return path
        return None

"""Tests for SnapshotManager (rollback.py) — snapshot safety flows."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pytest

import backend.evolution.rollback as rollback_module
from backend.evolution.rollback import (
    SnapshotCorruptedError,
    SnapshotError,
    SnapshotManager,
    SnapshotNotFoundError,
)


def _sample_files() -> dict[str, str | bytes]:
    return {
        "config/planner.md": "# planner prompt v1",
        "config/coder.md": b"# coder prompt v1",
        "notes.txt": "hello world",
    }


@pytest.fixture
def manager(tmp_path: Path) -> SnapshotManager:
    return SnapshotManager(tmp_path / "snapshots")


def _set_created_at(manager: SnapshotManager, sid: str, iso: str) -> None:
    """Rewrite created_at in an existing manifest (lets tests control ordering)."""
    mpath = manager.root / sid / "manifest.json"
    payload = json.loads(mpath.read_text(encoding="utf-8"))
    payload["created_at"] = iso
    mpath.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _make_dated(manager: SnapshotManager, n: int) -> list[str]:
    """Create n snapshots with deterministic ids and increasing created_at."""
    sids: list[str] = []
    for i in range(1, n + 1):
        sid = f"s{i:03d}"
        manager.create_snapshot(
            {"f.txt": f"content-{i}"}, reason=f"reason-{i}", snapshot_id=sid
        )
        _set_created_at(manager, sid, f"2026-01-{i:02d}T00:00:00+00:00")
        sids.append(sid)
    return sids


class TestCreateSnapshot:
    def test_manifest_records_hashes_created_at_reason(
        self, manager: SnapshotManager
    ) -> None:
        manifest = manager.create_snapshot(
            _sample_files(),
            reason="before risky refactor",
            metadata={"component_kind": "prompt", "version": "v2"},
        )
        assert manifest.reason == "before risky refactor"
        assert manifest.created_at
        datetime.fromisoformat(manifest.created_at)  # parses as ISO timestamp
        expected_hash = hashlib.sha256(b"# planner prompt v1").hexdigest()
        assert manifest.files["config/planner.md"] == expected_hash
        snap_dir = manager.root / manifest.snapshot_id
        assert (snap_dir / "manifest.json").is_file()
        assert (snap_dir / "data" / "notes.txt").read_bytes() == b"hello world"

    def test_atomic_writes_leave_no_tmp_files(self, manager: SnapshotManager) -> None:
        manifest = manager.create_snapshot(_sample_files(), reason="r")
        leftovers = list((manager.root / manifest.snapshot_id).rglob("*.tmp"))
        assert leftovers == []

    def test_empty_files_rejected(self, manager: SnapshotManager) -> None:
        with pytest.raises(ValueError):
            manager.create_snapshot({}, reason="empty")

    @pytest.mark.parametrize("bad", ["../escape.txt", "/absolute/path.txt", "a/../b.txt"])
    def test_unsafe_paths_rejected(self, manager: SnapshotManager, bad: str) -> None:
        with pytest.raises(ValueError):
            manager.create_snapshot({bad: "x"}, reason="bad")

    def test_duplicate_snapshot_id_rejected(self, manager: SnapshotManager) -> None:
        manager.create_snapshot({"f.txt": "x"}, reason="first", snapshot_id="dup")
        with pytest.raises(SnapshotError):
            manager.create_snapshot({"f.txt": "y"}, reason="second", snapshot_id="dup")


class TestVerifySnapshot:
    def test_intact_snapshot_has_no_problems(self, manager: SnapshotManager) -> None:
        manifest = manager.create_snapshot(_sample_files(), reason="ok")
        assert manager.verify_snapshot(manifest.snapshot_id) == []

    def test_tampered_content_detected(self, manager: SnapshotManager) -> None:
        manifest = manager.create_snapshot(_sample_files(), reason="ok")
        target = manager.root / manifest.snapshot_id / "data" / "notes.txt"
        target.write_bytes(b"tampered!")
        problems = manager.verify_snapshot(manifest.snapshot_id)
        assert len(problems) == 1
        assert "hash mismatch" in problems[0]
        assert "notes.txt" in problems[0]

    def test_missing_file_detected(self, manager: SnapshotManager) -> None:
        manifest = manager.create_snapshot(_sample_files(), reason="ok")
        (manager.root / manifest.snapshot_id / "data" / "notes.txt").unlink()
        problems = manager.verify_snapshot(manifest.snapshot_id)
        assert problems == ["missing file: notes.txt"]

    def test_corrupt_manifest_detected(self, manager: SnapshotManager) -> None:
        manifest = manager.create_snapshot(_sample_files(), reason="ok")
        (manager.root / manifest.snapshot_id / "manifest.json").write_bytes(
            b"{not valid json"
        )
        problems = manager.verify_snapshot(manifest.snapshot_id)
        assert len(problems) == 1
        assert "invalid manifest" in problems[0]

    def test_unknown_snapshot_reported_as_problem(self, manager: SnapshotManager) -> None:
        problems = manager.verify_snapshot("does-not-exist")
        assert problems == ["snapshot 'does-not-exist' not found"]

    def test_get_manifest_unknown_raises(self, manager: SnapshotManager) -> None:
        with pytest.raises(SnapshotNotFoundError):
            manager.get_manifest("ghost")

    def test_manifest_roundtrip_preserves_fields(self, manager: SnapshotManager) -> None:
        meta = {"component_kind": "coder", "version": "v7"}
        created = manager.create_snapshot({"a.txt": "A"}, reason="why", metadata=meta)
        loaded = manager.get_manifest(created.snapshot_id)
        assert loaded == created
        assert loaded.metadata == meta


class TestRestoreSnapshot:
    def test_restore_writes_files_into_target(
        self, manager: SnapshotManager, tmp_path: Path
    ) -> None:
        manager.create_snapshot(_sample_files(), reason="checkpoint", snapshot_id="snap-x")
        target = tmp_path / "live"
        out = manager.restore_snapshot("snap-x", target)
        assert out == target
        assert (target / "config" / "planner.md").read_text(encoding="utf-8") == (
            "# planner prompt v1"
        )
        assert (target / "config" / "coder.md").read_bytes() == b"# coder prompt v1"

    def test_restore_refuses_corrupted_snapshot(
        self, manager: SnapshotManager, tmp_path: Path
    ) -> None:
        manifest = manager.create_snapshot({"a.txt": "clean"}, reason="ok")
        (manager.root / manifest.snapshot_id / "data" / "a.txt").write_bytes(
            b"corrupted!!"
        )
        with pytest.raises(SnapshotCorruptedError, match="corrupted"):
            manager.restore_snapshot(manifest.snapshot_id, tmp_path / "out")
        assert not (tmp_path / "out").exists()

    def test_restore_is_idempotent(
        self, manager: SnapshotManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager.create_snapshot(_sample_files(), reason="ok", snapshot_id="snap-idem")
        target = tmp_path / "live"
        manager.restore_snapshot("snap-idem", target)

        calls: list[Path] = []
        real_write = rollback_module._atomic_write_bytes

        def spying_write(path: Path, data: bytes) -> None:
            calls.append(path)
            real_write(path, data)

        monkeypatch.setattr(rollback_module, "_atomic_write_bytes", spying_write)
        manager.restore_snapshot("snap-idem", target)
        assert calls == []  # second restore performed no writes: pure no-op

    def test_restore_repairs_modified_target(
        self, manager: SnapshotManager, tmp_path: Path
    ) -> None:
        manager.create_snapshot(
            {"svc.cfg": "stable-config"}, reason="pre-change", snapshot_id="snap-fix"
        )
        target = tmp_path / "live"
        manager.restore_snapshot("snap-fix", target)
        (target / "svc.cfg").write_bytes(b"drifted config")
        manager.restore_snapshot("snap-fix", target)  # converges back
        assert (target / "svc.cfg").read_bytes() == b"stable-config"


class TestPruneArchive:
    def test_prune_moves_oldest_beyond_keep_to_archive(
        self, manager: SnapshotManager
    ) -> None:
        _make_dated(manager, 5)
        archived = manager.prune_snapshots(keep=3)
        assert archived == ["s001", "s002"]
        active_ids = [m.snapshot_id for m in manager.list_snapshots()]
        assert active_ids == ["s003", "s004", "s005"]
        for sid in ("s001", "s002"):
            assert (manager.archive_dir / sid / "manifest.json").is_file()
            # Moved intact — still verifiable in its new home.
            assert manager.verify_snapshot(sid) == []

    def test_prune_never_deletes_anything(self, manager: SnapshotManager) -> None:
        sids = _make_dated(manager, 4)
        manager.prune_snapshots(keep=2)
        remaining: set[str] = set()
        for base in (manager.root, manager.archive_dir):
            remaining |= {
                p.name for p in base.iterdir() if p.is_dir() and p.name != "archive"
            }
        assert remaining == set(sids)  # nothing deleted, only relocated

    def test_prune_under_limit_is_noop(self, manager: SnapshotManager) -> None:
        _make_dated(manager, 2)
        assert manager.prune_snapshots(keep=10) == []
        active_ids = [m.snapshot_id for m in manager.list_snapshots()]
        assert active_ids == ["s001", "s002"]

    def test_default_keep_is_20(self, manager: SnapshotManager) -> None:
        _make_dated(manager, 22)
        archived = manager.prune_snapshots()  # default keep=20
        assert archived == ["s001", "s002"]
        assert len(manager.list_snapshots()) == 20

    def test_list_snapshots_archived_flag(self, manager: SnapshotManager) -> None:
        _make_dated(manager, 3)
        manager.prune_snapshots(keep=1)
        assert [m.snapshot_id for m in manager.list_snapshots()] == ["s003"]
        all_ids = [m.snapshot_id for m in manager.list_snapshots(include_archived=True)]
        assert all_ids == ["s001", "s002", "s003"]

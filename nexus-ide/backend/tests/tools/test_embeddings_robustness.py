"""Robustness regression suite for backend.tools.embeddings.

Locks in the fixes for five identified weaknesses of the global vector
store:

1. Incremental re-indexing purges chunks whose backing file was deleted
   (reported as ``stale_removed_last_index``).
2. Snapshot writes are atomic (``.tmp`` + ``os.replace``) and carry a
   ``_meta`` record ({model_name, dim, count}); the loader discards vectors
   whose dimension disagrees with the snapshot.
3. ``indexed_at`` defaults to wall-clock ``time.time()`` (was CPU time).
4. Semantic search skips vectors with a foreign dimension instead of letting
   the zip-based cosine truncate silently (``dim_mismatch_skipped``).
5. ``index_stats`` exposes ``stale_removed_last_index``, ``dim_mismatch_skipped``
   and ``model_name``.

Everything runs fully offline: the embedding provider is stubbed to fail so
search exercises the keyword fallback (same pattern as tests/stress block 7,
no Ollama). The fuzz test performs exactly 800 deterministic index+search
iterations seeded from SEED, so runs are reproducible.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any

import pytest

import backend.tools.embeddings as emb
from backend.tools.embeddings import CodeChunk

SEED = 20260825
FUZZ_CASES = 80
FUZZ_ITERS_PER_CASE = 10
assert FUZZ_CASES * FUZZ_ITERS_PER_CASE == 800


@pytest.fixture(autouse=True)
def isolated_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the global store, snapshot paths and robustness counters."""
    monkeypatch.setattr(emb, "INDEX_SNAPSHOT_PATH", tmp_path / "embeddings_index.json")
    monkeypatch.setattr(emb, "INDEX_META_PATH", tmp_path / "embeddings_index_meta.json")
    monkeypatch.setattr(emb, "_store", {})
    monkeypatch.setattr(emb, "_faiss_index", None)
    monkeypatch.setattr(emb, "_faiss_id_map", {})
    monkeypatch.setattr(emb, "_snapshot_meta", {})
    monkeypatch.setattr(emb, "_stale_removed_last_index", 0)
    monkeypatch.setattr(emb, "_dim_mismatch_skipped", 0)


@pytest.fixture()
def offline_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the no-provider path: every embed call yields no vector."""

    async def failing_embed(texts: list[str], model: str) -> list[None]:
        return [None] * len(texts)

    monkeypatch.setattr(emb, "_embed_batch_with_fallback", failing_embed)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Stale cleanup for deleted files
# ---------------------------------------------------------------------------


class TestStaleFileCleanup:
    async def test_deleted_file_chunks_removed_on_incremental_reindex(
        self, tmp_path: Path, offline_embedder: None
    ) -> None:
        root = tmp_path / "proj"
        victim = root / "victim.py"
        keeper = root / "keeper.py"
        _write(victim, "def ghost_marker():\n    return 'soon gone'\n")
        _write(keeper, "def stays():\n    return 'still here'\n")

        assert await emb.index_codebase(str(root), force_reindex=True) > 0
        victim_ids = [chunk_id for chunk_id in emb._store if "victim.py" in chunk_id]
        assert victim_ids

        victim.unlink()
        assert await emb.index_codebase(str(root)) == 0  # nothing new to embed

        remaining_ids = [chunk_id for chunk_id in emb._store if "victim.py" in chunk_id]
        assert remaining_ids == []
        assert all(Path(chunk.file).exists() for _, chunk in emb._store.values())
        assert all("ghost_marker" not in chunk.content for _, chunk in emb._store.values())

        stats = await emb.get_index_stats()
        assert stats["stale_removed_last_index"] == len(victim_ids)

        # The cleanup reached disk too: a cold reload sees no ghost chunks.
        reloaded = emb._load_index_snapshot()
        assert [chunk_id for chunk_id in reloaded if "victim.py" in chunk_id] == []
        assert reloaded

    async def test_chunks_of_existing_but_unvisited_files_are_kept(
        self, tmp_path: Path, offline_embedder: None
    ) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        _write(first / "a.txt", "alpha persistent terms\n")
        _write(second / "b.txt", "beta persistent terms\n")

        await emb.index_codebase(str(first), force_reindex=True)
        await emb.index_codebase(str(second))
        before = len(emb._store)
        assert before == 2

        # Re-walking `first` must not evict `second`'s chunks: that file
        # still exists on disk, it is simply not part of this walk.
        await emb.index_codebase(str(first))
        assert len(emb._store) == before
        assert {chunk.file for _, chunk in emb._store.values()} == {
            str(first / "a.txt"),
            str(second / "b.txt"),
        }
        stats = await emb.get_index_stats()
        assert stats["stale_removed_last_index"] == 0


# ---------------------------------------------------------------------------
# 2. Snapshot dimension guard on load + meta round-trip
# ---------------------------------------------------------------------------


class TestSnapshotDimensionGuard:
    @staticmethod
    def _entry(dim_tag: int, vec_len: int) -> dict[str, Any]:
        marker = f"marker_{dim_tag}"
        chunk = CodeChunk(
            file=f"/fake/file_{dim_tag}.py",
            start_line=1,
            end_line=1,
            content=f"# {marker}\n",
            language="python",
            symbol_type="comment",
            symbol_name=marker,
            chunk_hash=marker,
        )
        vector = [round(1.0 / (vec_len or 1), 6)] * vec_len
        return {"embedding": vector, "chunk": chunk.to_dict()}

    async def test_load_discards_foreign_dimensions_against_meta(self, caplog) -> None:
        payload = {
            "_meta": {"model_name": "nomic-embed-text", "dim": 4, "count": 3},
            "id::good_a": self._entry(1, 4),
            "id::good_b": self._entry(2, 4),
            "id::wide": self._entry(3, 8),
            "id::offline": self._entry(4, 0),  # empty vector stays (keyword-only)
        }
        emb.INDEX_SNAPSHOT_PATH.write_text(json.dumps(payload), encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="backend.tools.embeddings"):
            store = emb._load_index_snapshot()

        assert set(store) == {"id::good_a", "id::good_b", "id::offline"}
        assert emb._dim_mismatch_skipped == 1
        assert any("dimension" in record.getMessage().lower() for record in caplog.records)

        stats = await emb.get_index_stats()
        assert stats["dim_mismatch_skipped"] >= 1
        assert stats["model_name"] == "nomic-embed-text"

    async def test_legacy_snapshot_without_meta_keeps_dominant_dimension(self) -> None:
        payload = {
            "id::a": self._entry(1, 4),
            "id::b": self._entry(2, 4),
            "id::odd": self._entry(3, 3),
        }
        emb.INDEX_SNAPSHOT_PATH.write_text(json.dumps(payload), encoding="utf-8")

        store = emb._load_index_snapshot()

        assert set(store) == {"id::a", "id::b"}
        assert emb._dim_mismatch_skipped == 1

    async def test_saved_snapshot_records_model_dim_count_and_round_trips(
        self, tmp_path: Path, offline_embedder: None
    ) -> None:
        root = tmp_path / "proj"
        _write(root / "mod.py", "def alpha():\n    return 'a'\n")
        await emb.index_codebase(str(root), force_reindex=True)

        payload = json.loads(emb.INDEX_SNAPSHOT_PATH.read_text(encoding="utf-8"))
        meta = payload["_meta"]
        assert set(meta) == {"model_name", "dim", "count"}
        assert meta["model_name"] == emb._EMBED_MODELS[0]
        assert meta["count"] == len(emb._store)
        # Offline embedder stores empty vectors, so the dominant dim is 0.
        assert meta["dim"] == 0
        assert "_meta" not in emb._load_index_snapshot()

        stats = await emb.get_index_stats()
        assert stats["model_name"] == emb._EMBED_MODELS[0]


# ---------------------------------------------------------------------------
# 3. Atomic snapshot write
# ---------------------------------------------------------------------------


class TestAtomicSnapshotWrite:
    async def test_crash_during_save_leaves_previous_snapshot_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, offline_embedder: None
    ) -> None:
        root = tmp_path / "proj"
        _write(root / "one.py", "def one():\n    return 1\n")
        await emb.index_codebase(str(root), force_reindex=True)

        snapshot_before = emb.INDEX_SNAPSHOT_PATH.read_bytes()
        parsed_before = json.loads(snapshot_before)
        assert parsed_before["_meta"]["count"] == len(emb._store)

        _write(root / "two.py", "def two():\n    return 2\n")

        class CrashOnReplace:
            """os.replace stand-in that dies right before the atomic swap."""

            def __init__(self) -> None:
                self.calls = 0

            def replace(self, src: object, dst: object) -> None:
                self.calls += 1
                raise OSError("simulated crash between temp write and rename")

            def __getattr__(self, name: str) -> Any:
                return getattr(os, name)

        crasher = CrashOnReplace()
        monkeypatch.setattr(emb, "os", crasher)
        await emb.index_codebase(str(root))  # must not raise

        assert crasher.calls == 1
        # The published snapshot is byte-identical to the pre-crash version...
        assert emb.INDEX_SNAPSHOT_PATH.read_bytes() == snapshot_before
        # ...and the leftover temp file is ignored by the loader.
        tmp_sibling = emb.INDEX_SNAPSHOT_PATH.with_name(emb.INDEX_SNAPSHOT_PATH.name + ".tmp")
        assert tmp_sibling.exists()
        loaded = emb._load_index_snapshot()
        assert set(loaded) == set(parsed_before) - {emb._SNAPSHOT_META_KEY}

        # Recovery: a healthy save swaps the updated snapshot in and clears
        # the stale temp file.
        monkeypatch.setattr(emb, "os", os)
        await emb.index_codebase(str(root))
        reloaded = emb._load_index_snapshot()
        assert any("two" in chunk.content for _, chunk in reloaded.values())
        assert not tmp_sibling.exists()

    async def test_corrupt_main_snapshot_loads_empty_without_raising(self) -> None:
        emb.INDEX_SNAPSHOT_PATH.write_text("{truncated json...", encoding="utf-8")
        assert emb._load_index_snapshot() == {}


# ---------------------------------------------------------------------------
# 4. indexed_at default
# ---------------------------------------------------------------------------


class TestIndexedAtDefault:
    def test_default_is_wall_clock_not_cpu_time(self) -> None:
        before = time.time()
        chunk = CodeChunk(file="x.py", start_line=1, end_line=1, content="")
        after = time.time()
        assert before <= chunk.indexed_at <= after
        # os.times()[0] (CPU seconds since start) would be orders of
        # magnitude below epoch seconds on a fresh interpreter.
        assert chunk.indexed_at > 1_500_000_000

    def test_from_dict_without_field_still_loads_legacy_snapshots(self) -> None:
        legacy = {"file": "x.py", "start_line": 1, "end_line": 1, "content": "c"}
        assert CodeChunk.from_dict(legacy).indexed_at == 0.0


# ---------------------------------------------------------------------------
# 5. Dimension guard in search
# ---------------------------------------------------------------------------


class TestSearchDimensionGuard:
    async def test_linear_scan_ignores_foreign_dimension_vectors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "proj"
        root.mkdir()

        def make_chunk(name: str, content: str) -> CodeChunk:
            return CodeChunk(
                file=str(root / f"{name}.py"),
                start_line=1,
                end_line=2,
                content=content,
                language="python",
                symbol_type="function",
                symbol_name=name,
            )

        emb._store.update(
            {
                "match": ([0.25, 0.5, 0.75], make_chunk("handler", "def handler():\n    pass\n")),
                "wide": ([0.1] * 768, make_chunk("wide_one", "def wide_one():\n    pass\n")),
                "novector": ([], make_chunk("cold_one", "def cold_one():\n    pass\n")),
            }
        )

        async def fixed_dim_embed(texts: list[str], model: str) -> list[list[float]]:
            return [[0.5, 0.5, 0.5] for _ in texts]

        monkeypatch.setattr(emb, "_embed_batch_with_fallback", fixed_dim_embed)

        results = await emb.search_codebase("handler")
        names = [chunk.symbol_name for chunk in results]
        assert "wide_one" not in names  # foreign dimension skipped, not truncated
        assert results[0].symbol_name == "handler"
        assert results[0].score > 0.0
        assert emb._dim_mismatch_skipped == 1

        stats = await emb.get_index_stats()
        assert stats["dim_mismatch_skipped"] == 1


# ---------------------------------------------------------------------------
# 6. Offline index+search fuzz — 800 deterministic iterations
# ---------------------------------------------------------------------------

# Marker terms live INSIDE the symbol bodies on purpose: _chunk_python only
# indexes function/class spans, so trailing comments would never be embedded.
_FILES_POOL = (
    (
        "auth_svc.py",
        "def login(user):\n    # login_token_auth\n    token = issue(user)\n    return token\n",
        "login_token_auth",
    ),
    (
        "cfg_loader.py",
        "def parse_config(path):\n    # parse_yaml_config\n    return load_yaml(read(path))\n",
        "parse_yaml_config",
    ),
    (
        "retry_client.py",
        "def fetch_retry(url):\n    # retry_backoff_fetch\n    return backoff_http(url)\n",
        "retry_backoff_fetch",
    ),
    (
        "cache_store.py",
        "def cache_get(key):\n    # cache_ttl_lookup\n    return ttl_lookup(key)\n",
        "cache_ttl_lookup",
    ),
    (
        "queue_bus.py",
        "def enqueue(job):\n    # enqueue_bus_publish\n    bus_publish(job)\n    return job.id\n",
        "enqueue_bus_publish",
    ),
    (
        "NOTES.md",
        "# notes runbook_notes_contents\n\nops checklist details\n",
        "runbook_notes_contents",
    ),
)


def _result_key(chunks: list[CodeChunk]) -> list[tuple[str, int, float]]:
    return [(chunk.file, chunk.start_line, round(chunk.score, 9)) for chunk in chunks]


@pytest.mark.parametrize("case_idx", range(FUZZ_CASES))
async def test_offline_index_search_fuzz_800_iterations(
    case_idx: int, tmp_path: Path, offline_embedder: None
) -> None:
    """800 deterministic offline index+search iterations (80 cases x 10).

    Each iteration mutates a throwaway project (add/edit/delete/noop), runs
    a full incremental ``index_codebase`` plus keyword-fallback searches, and
    asserts the core robustness invariants:

    - every surviving chunk points at a file that still exists;
    - deleted files' marker terms become unreachable through search;
    - live marker terms stay findable, deterministically across repeat calls;
    - ``index_stats`` carries the new robustness fields.
    """
    rng = random.Random(SEED + case_idx)
    root = tmp_path / "proj"
    root.mkdir()
    on_disk: dict[str, str] = {}  # absolute path -> marker term
    ghosts: dict[str, str] = {}  # deleted path -> marker term

    for _ in range(FUZZ_ITERS_PER_CASE):
        action = rng.choice(("ADD", "EDIT", "DELETE", "NOOP"))
        if action in ("EDIT", "DELETE") and not on_disk:
            action = "ADD"

        if action == "ADD":
            name, body, marker = _FILES_POOL[rng.randrange(len(_FILES_POOL))]
            target = root / f"{case_idx}_{name}"
            _write(target, body)
            on_disk[str(target)] = marker
            # Re-adding a previously deleted path revives its marker, so it
            # stops counting as a ghost.
            ghosts.pop(str(target), None)
        elif action == "EDIT":
            path_str = rng.choice(sorted(on_disk))
            path = Path(path_str)
            _write(
                path,
                path.read_text(encoding="utf-8") + f"# edit{rng.randrange(10_000)} touch\n",
            )
        elif action == "DELETE":
            path_str = rng.choice(sorted(on_disk))
            Path(path_str).unlink()
            ghosts[path_str] = on_disk.pop(path_str)

        indexed = await emb.index_codebase(str(root))
        assert isinstance(indexed, int) and indexed >= 0

        # Invariant A: no chunk references a vanished file.
        for _, chunk in emb._store.values():
            assert Path(chunk.file).exists(), f"ghost chunk for {chunk.file}"

        results = await emb.search_codebase("config", project_path=str(root))
        repeat = await emb.search_codebase("config", project_path=str(root))
        assert _result_key(results) == _result_key(repeat)

        # Invariant B: deleted markers are unreachable; live ones reachable.
        for marker in ghosts.values():
            assert await emb.search_codebase(marker, project_path=str(root)) == []
        if on_disk:
            marker = next(iter(on_disk.values()))
            hits = await emb.search_codebase(marker, project_path=str(root))
            assert hits, marker
            assert marker in hits[0].content.lower()
            again = await emb.search_codebase(marker, project_path=str(root))
            assert _result_key(hits) == _result_key(again)

    # Invariant C: stats surface the robustness fields after real work.
    stats = await emb.get_index_stats()
    assert {"total_chunks", "stale_removed_last_index", "dim_mismatch_skipped"} <= set(stats)
    assert stats["model_name"] == emb._EMBED_MODELS[0]
    assert stats["stale_removed_last_index"] >= 0
    assert stats["total_chunks"] == len(emb._store)

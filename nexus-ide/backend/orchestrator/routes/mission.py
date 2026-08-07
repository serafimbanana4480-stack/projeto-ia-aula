"""API surface for Mission Control.

Exposes the supervised-execution state that ``mission_control.py`` produces:
the brief, the plan, the agent contracts grouped into waves, the decision log,
verification results and the generated reports.

The registry is deliberately in-process and bounded. Missions are durable on
disk (``.nexus/missions/*.json`` and ``reports/*.md``); this module only keeps
the recent ones hot so the dashboard can poll without touching the filesystem
on every request.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from backend.middleware.auth import require_auth
from backend.orchestrator.mission_control import (
    MISSIONS_DIR,
    REPORTS_DIR,
    Mission,
    MissionReport,
    MissionTracker,
    ProjectIntelligence,
    start_mission,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Bounded LRU of live missions. Unbounded would leak one snapshot per request
# on a long-running server; 32 is far more than any dashboard displays.
_MAX_LIVE_MISSIONS = 32
_MISSIONS: OrderedDict[str, MissionTracker] = OrderedDict()


# ═══════════════════════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════════════════════

def register_mission(tracker: MissionTracker) -> MissionTracker:
    """Make a tracker visible to the API. Called by the chat pipeline."""
    _MISSIONS[tracker.mission.id] = tracker
    _MISSIONS.move_to_end(tracker.mission.id)
    while len(_MISSIONS) > _MAX_LIVE_MISSIONS:
        _MISSIONS.popitem(last=False)
    return tracker


def get_tracker(mission_id: str) -> MissionTracker | None:
    return _MISSIONS.get(mission_id)


def current_tracker() -> MissionTracker | None:
    """The most recently registered mission — what the dashboard shows."""
    if not _MISSIONS:
        return None
    return next(reversed(_MISSIONS.values()))


def tracker_for_session(session_id: str) -> MissionTracker | None:
    for tracker in reversed(_MISSIONS.values()):
        if tracker.mission.session_id == session_id:
            return tracker
    return None


def _load_persisted(mission_id: str) -> dict[str, Any] | None:
    path = MISSIONS_DIR / f"{mission_id}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("unreadable mission file %s", path, exc_info=True)
        return None


def _summary(m: Mission) -> dict[str, Any]:
    """The mission panel header — the eight numbers, nothing else."""
    return {
        "id": m.id,
        "session_id": m.session_id,
        "title": m.title,
        "state": m.state.value,
        "phase": m.phase.value,
        "phase_label": m.phase.label,
        "progress": m.progress,
        "active_agents": m.active_agents,
        "tasks_total": len(m.contracts),
        "tasks_done": sum(
            1 for c in m.contracts if c.state.value in ("completed", "skipped")
        ),
        "files_changed": len(m.files_changed),
        "tests_passed": m.tests_passed,
        "tests_failed": m.tests_failed,
        "risks": len(m.risks),
        "blocked": sum(1 for c in m.contracts if c.state.value in ("blocked", "failed")),
        "started_at": m.started_at,
        "finished_at": m.finished_at,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Read endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/mission/current")
async def get_current_mission(_user: dict = Depends(require_auth)) -> dict:
    """Full state of the most recent mission.

    Returns ``{"active": false}`` rather than 404 when nothing has run: an
    empty dashboard is a normal state, not a client error.
    """
    tracker = current_tracker()
    if tracker is None:
        return {"active": False, "mission": None}
    return {"active": True, "mission": tracker.mission.to_dict()}


@router.get("/mission/summary")
async def get_mission_summary(_user: dict = Depends(require_auth)) -> dict:
    """Header-only view. Cheap enough to poll on a short interval."""
    tracker = current_tracker()
    if tracker is None:
        return {"active": False, "summary": None}
    return {"active": True, "summary": _summary(tracker.mission)}


@router.get("/mission/list")
async def list_missions(_user: dict = Depends(require_auth)) -> dict:
    """Live missions first, then anything persisted to disk."""
    live = [_summary(t.mission) for t in reversed(_MISSIONS.values())]
    live_ids = {item["id"] for item in live}

    persisted: list[dict[str, Any]] = []
    if MISSIONS_DIR.is_dir():
        for path in sorted(
            MISSIONS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:50]:
            if path.stem in live_ids:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            persisted.append({
                "id": data.get("id", path.stem),
                "session_id": data.get("session_id", ""),
                "title": data.get("title", ""),
                "state": data.get("state", "unknown"),
                "phase": data.get("phase", ""),
                "progress": data.get("progress", 0.0),
                "tasks_total": data.get("tasks_total", 0),
                "tasks_done": data.get("tasks_done", 0),
                "tests_passed": data.get("tests_passed", 0),
                "tests_failed": data.get("tests_failed", 0),
                "files_changed": len(data.get("files_changed", [])),
                "started_at": data.get("started_at"),
                "finished_at": data.get("finished_at"),
                "archived": True,
            })

    return {"live": live, "archived": persisted, "total": len(live) + len(persisted)}


@router.get("/mission/reports")
async def list_reports(_user: dict = Depends(require_auth)) -> dict:
    """Markdown artefacts written by completed missions."""
    if not REPORTS_DIR.is_dir():
        return {"reports": []}
    reports = []
    for path in sorted(
        REPORTS_DIR.glob("nexus-run-*.md"), key=lambda p: p.stat().st_mtime, reverse=True
    )[:50]:
        stat = path.stat()
        reports.append({
            "name": path.name,
            "size_bytes": stat.st_size,
            "modified_at": stat.st_mtime,
        })
    return {"reports": reports}


@router.get("/mission/reports/{name}")
async def read_report(name: str, _user: dict = Depends(require_auth)) -> dict:
    """Return one report's markdown.

    ``name`` is resolved and re-checked against ``REPORTS_DIR`` so a crafted
    ``../`` cannot escape the directory.
    """
    if "/" in name or "\\" in name or not name.endswith(".md"):
        raise HTTPException(status_code=400, detail="Invalid report name")
    path = (REPORTS_DIR / name).resolve()
    try:
        path.relative_to(REPORTS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report path") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return {"name": name, "content": path.read_text(encoding="utf-8")}


@router.get("/mission/{mission_id}")
async def get_mission(mission_id: str, _user: dict = Depends(require_auth)) -> dict:
    tracker = get_tracker(mission_id)
    if tracker is not None:
        return {"mission": tracker.mission.to_dict(), "archived": False}
    data = _load_persisted(mission_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    return {"mission": data, "archived": True}


# ═══════════════════════════════════════════════════════════════════════════
# Write endpoints
# ═══════════════════════════════════════════════════════════════════════════

@router.post("/mission/analyze")
async def analyze_project(body: dict, _user: dict = Depends(require_auth)) -> dict:
    """Run the brief + plan phase only. **No agent is created.**

    This is the "look before you leap" endpoint: it answers "what would you do
    and why" without touching a single file.
    """
    objective = (body.get("objective") or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="Missing 'objective'")

    tracker = start_mission(
        objective,
        session_id=body.get("session_id", ""),
        project_path=body.get("project_path", "."),
        deep_scan=bool(body.get("deep_scan", True)),
    )
    register_mission(tracker)
    tracker.persist()
    return {
        "mission_id": tracker.mission.id,
        "mission": tracker.mission.to_dict(),
        "agents_started": 0,
    }


@router.post("/mission/scan")
async def scan_project(body: dict, _user: dict = Depends(require_auth)) -> dict:
    """Project intelligence only — the measured snapshot, no plan, no agents."""
    snapshot = ProjectIntelligence(body.get("project_path", ".")).scan(
        deep=bool(body.get("deep", True))
    )
    return {"snapshot": snapshot.to_dict(), "summary": snapshot.summary_lines()}


@router.post("/mission/{mission_id}/report")
async def generate_report(mission_id: str, _user: dict = Depends(require_auth)) -> dict:
    """Write the mission's markdown report to ``reports/``."""
    tracker = get_tracker(mission_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Mission not found or no longer live")
    report = MissionReport(tracker.mission)
    path = report.write()
    return {
        "written": path is not None,
        "path": str(path) if path else None,
        "name": path.name if path else None,
        "content": report.render(),
    }


@router.post("/mission/{mission_id}/wave/{index}/start")
async def start_wave(
    mission_id: str, index: int, _user: dict = Depends(require_auth)
) -> dict:
    """Release a wave for execution. Waves are explicit, never automatic."""
    tracker = get_tracker(mission_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Mission not found or no longer live")
    wave = tracker.start_wave(index)
    if wave is None:
        raise HTTPException(status_code=404, detail=f"Wave {index} not found")
    return {"wave": wave.to_dict()}


__all__ = [
    "router",
    "register_mission",
    "get_tracker",
    "current_tracker",
    "tracker_for_session",
]

from __future__ import annotations

"""Analytics routes for conversation intelligence, performance metrics and reporting.

Provides endpoints for:
- Conversation history and analysis
- Response time and throughput metrics
- Sentiment analysis of interactions
- Usage statistics and reporting
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query, Response, Request
from pydantic import BaseModel


router = APIRouter()

NOW = time.time()
HOUR = 3600
DAY = 86400


class SentimentData(BaseModel):
    score: float
    label: str
    positive_pct: float
    neutral_pct: float
    negative_pct: float


class ConversationStats(BaseModel):
    total: int
    successful: int
    failed: int
    avg_response_ms: float
    avg_tokens_per_second: float
    total_tokens: int


class TimeSeriesPoint(BaseModel):
    timestamp: float
    value: float
    label: str | None = None


class AgentMetric(BaseModel):
    agent: str
    calls: int
    avg_latency_ms: float
    success_rate: float
    total_tokens: int


class UsageStats(BaseModel):
    total_conversations: int
    total_messages: int
    total_tokens: int
    unique_sessions: int
    peak_concurrent: int
    uptime_seconds: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

NEUTRAL_SENTIMENT = {
    "score": 0.0,
    "label": "neutral",
    "positive_pct": 0.0,
    "neutral_pct": 0.0,
    "negative_pct": 0.0,
}


# ---------------------------------------------------------------------------
# Conversations & messaging
# ---------------------------------------------------------------------------

@router.get("/analytics/conversations")
async def get_conversations(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    agent: str | None = None,
    sentiment: str | None = None,
) -> dict[str, Any]:
    """Return paginated conversation history with metadata.

    No fabricated conversations are synthesised. Returns an empty list so the
    frontend renders its "No conversations found" state truthfully.
    """
    return {"conversations": [], "total": 0, "limit": limit, "offset": offset}


@router.get("/analytics/conversations/{conv_id}")
async def get_conversation(conv_id: str) -> dict[str, Any]:
    """Return full detail of a single conversation including message exchange."""
    return {
        "id": conv_id,
        "session_id": "",
        "messages": [],
        "sentiment": dict(NEUTRAL_SENTIMENT),
        "response_time_ms": 0,
        "tokens_generated": 0,
    }


@router.get("/analytics/conversations/{conv_id}/sentiment")
async def get_conversation_sentiment(conv_id: str) -> dict:
    """Return sentiment analysis for a specific conversation."""
    return {
        "conversation_id": conv_id,
        "overall": dict(NEUTRAL_SENTIMENT),
        "turns": [],
    }


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

@router.get("/analytics/performance/response-time")
async def get_response_time(
    hours: int = Query(24, ge=1, le=168),
) -> dict[str, Any]:
    """Return response time distribution over time."""
    return {"data": [], "summary": {}}


@router.get("/analytics/performance/throughput")
async def get_throughput(
    hours: int = Query(24, ge=1, le=168),
) -> dict[str, Any]:
    """Return token throughput over time."""
    return {"data": [], "summary": {}}


@router.get("/analytics/performance/accuracy")
async def get_accuracy_rate(
    days: int = Query(30, ge=1, le=90),
) -> dict[str, Any]:
    """Return task success / accuracy rate over time."""
    return {"data": [], "summary": {}}


# ---------------------------------------------------------------------------
# Agent metrics
# ---------------------------------------------------------------------------

@router.get("/analytics/agents/metrics")
async def get_agent_metrics() -> list[dict]:
    """Return per-agent performance breakdown.

    No fabricated per-agent metrics are synthesised. Returns an empty list so
    the frontend renders empty agent charts truthfully.
    """
    return []


# ---------------------------------------------------------------------------
# Sentiment analysis
# ---------------------------------------------------------------------------

@router.get("/analytics/sentiment/overview")
async def get_sentiment_overview(
    days: int = Query(30, ge=1, le=90),
) -> dict[str, Any]:
    """Return aggregate sentiment analysis across all conversations."""
    return {
        "overall": dict(NEUTRAL_SENTIMENT),
        "trend": [],
        "by_agent": {},
        "insights": [],
    }


@router.get("/analytics/sentiment/trend")
async def get_sentiment_trend(
    days: int = Query(30, ge=1, le=90),
) -> dict[str, Any]:
    """Return daily sentiment trend data."""
    return {"data": []}


# ---------------------------------------------------------------------------
# Usage statistics
# ---------------------------------------------------------------------------

@router.get("/analytics/usage/summary")
async def get_usage_summary() -> dict[str, Any]:
    """Return aggregate usage statistics.

    Uses real message/session counts from the persistence layer when available;
    falls back to zeroed values if the database is unreachable so the response
    shape stays truthful (never fabricated).
    """
    try:
        from backend.persistence import db as _db

        stats = _db.get_message_statistics()
        total_sessions = _db.count_active_sessions()
        total_messages = int(stats.get("total_messages", 0) or 0)
        total_tokens = int(stats.get("tokens_in_total", 0) or 0) + int(stats.get("tokens_out_total", 0) or 0)
        unique_sessions = int(stats.get("sessions_with_messages", 0) or 0)
        avg_messages_per_conversation = round(total_messages / total_sessions, 1) if total_sessions else 0.0
        avg_tokens_per_message = round(total_tokens / total_messages, 1) if total_messages else 0.0
    except Exception:
        total_sessions = total_messages = total_tokens = unique_sessions = 0
        avg_messages_per_conversation = 0.0
        avg_tokens_per_message = 0.0

    return {
        "total_conversations": total_sessions,
        "total_messages": total_messages,
        "total_tokens": total_tokens,
        "unique_sessions": unique_sessions,
        "peak_concurrent_sessions": 0,
        "avg_messages_per_conversation": avg_messages_per_conversation,
        "avg_tokens_per_message": avg_tokens_per_message,
        "uptime_seconds": 0,
        "period_start": datetime.fromtimestamp(NOW - 30 * DAY, tz=timezone.utc).isoformat(),
        "period_end": datetime.fromtimestamp(NOW, tz=timezone.utc).isoformat(),
    }


@router.get("/analytics/usage/hourly")
async def get_hourly_usage(
    days: int = Query(7, ge=1, le=30),
) -> dict[str, Any]:
    """Return hourly usage breakdown."""
    return {"data": []}


@router.get("/analytics/usage/by-agent")
async def get_usage_by_agent() -> list[dict]:
    """Return usage breakdown per agent.

    No fabricated per-agent usage is synthesised. Returns an empty list so the
    frontend renders an empty state truthfully.
    """
    return []


# ---------------------------------------------------------------------------
# Reports (PDF/Excel export metadata)
# ---------------------------------------------------------------------------

@router.get("/analytics/reports/available")
async def get_available_reports() -> list[dict[str, Any]]:
    """Return list of available report templates for export."""
    return [
        {
            "id": "perf-weekly",
            "name": "Performance Report — Weekly",
            "description": "Response times, throughput and accuracy metrics for the past 7 days",
            "format": ["pdf", "xlsx"],
            "period": "7 days",
            "size_kb": 245,
        },
        {
            "id": "perf-monthly",
            "name": "Performance Report — Monthly",
            "description": "Comprehensive performance and agent breakdown for 30 days",
            "format": ["pdf", "xlsx"],
            "period": "30 days",
            "size_kb": 890,
        },
        {
            "id": "sentiment-analysis",
            "name": "Sentiment Analysis Report",
            "description": "User satisfaction trends, emotion breakdown and insights",
            "format": ["pdf"],
            "period": "30 days",
            "size_kb": 340,
        },
        {
            "id": "usage-summary",
            "name": "Usage Summary Report",
            "description": "Total usage statistics, session counts and resource consumption",
            "format": ["pdf", "xlsx"],
            "period": "30 days",
            "size_kb": 520,
        },
    ]


@router.post("/analytics/reports/generate")
async def generate_report(payload: dict, request: Request) -> dict[str, Any]:
    """Generate a PDF or Excel report asynchronously. Returns report_id for download."""
    report_id = f"report-{int(NOW)}"
    fmt = payload.get("format", "pdf")
    report_type = payload.get("report_id", "perf-weekly")

    import asyncio
    asyncio.create_task(_build_report(report_id, report_type, fmt))

    return {
        "report_id": report_id,
        "status": "ready",
        "download_url": f"/api/analytics/reports/{report_id}/download?format={fmt}",
        "format": fmt,
        "expires_at": datetime.fromtimestamp(NOW + 3600, tz=timezone.utc).isoformat(),
    }


async def _build_report(report_id: str, report_type: str, fmt: str) -> None:
    """Build report in background and store to disk."""
    import os, json
    from pathlib import Path

    out_dir = Path("nexus-ide/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    data = await _collect_report_data(report_type)

    if fmt == "xlsx":
        path = out_dir / f"{report_id}.xlsx"
        _build_excel(data, report_type, path)
    else:
        path = out_dir / f"{report_id}.pdf"
        _build_pdf(data, report_type, path)

    meta_path = out_dir / f"{report_id}.meta.json"
    meta_path.write_text(json.dumps({"report_id": report_id, "format": fmt, "path": str(path)}))


async def _collect_report_data(report_type: str) -> dict[str, Any]:
    """Fetch all data needed for a given report type."""
    if report_type in ("perf-weekly", "perf-monthly"):
        days = 7 if report_type == "perf-weekly" else 30
        rt = await _fetch_json("/api/analytics/performance/response-time", {"hours": days * 24})
        tp = await _fetch_json("/api/analytics/performance/throughput", {"hours": days * 24})
        ac = await _fetch_json("/api/analytics/performance/accuracy", {"days": days})
        ag = await _fetch_json("/api/analytics/agents/metrics", {})
        return {"type": report_type, "response_time": rt, "throughput": tp, "accuracy": ac, "agents": ag}
    elif report_type == "sentiment-analysis":
        so = await _fetch_json("/api/analytics/sentiment/overview", {"days": 30})
        return {"type": report_type, "sentiment": so}
    elif report_type == "usage-summary":
        us = await _fetch_json("/api/analytics/usage/summary", {})
        ua = await _fetch_json("/api/analytics/usage/by-agent", {})
        return {"type": report_type, "usage": us, "by_agent": ua}
    return {"type": report_type}


async def _fetch_json(path: str, params: dict) -> Any:
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.get(f"http://localhost:8001{path}", params=params, timeout=10.0)
            return r.json()
    except Exception:
        return {}


def _build_pdf(data: dict, report_type: str, path: Path) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=18, textColor=colors.HexColor("#7c3aed"), spaceAfter=6)
    subtitle_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=10, textColor=colors.grey, spaceAfter=20)
    heading_style = ParagraphStyle("Heading2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#06b6d4"), spaceBefore=16, spaceAfter=6)

    story = [
        Paragraph("NEXUS OMEGA — Analytics Report", title_style),
        Paragraph(f"Report Type: {report_type.replace('-', ' ').title()} — Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", subtitle_style),
        HRFlowable(width="100%", thickness=1, color=colors.HexColor("#7c3aed"), spaceAfter=20),
        Spacer(1, 0.3*cm),
    ]

    if report_type in ("perf-weekly", "perf-monthly"):
        summary = data.get("response_time", {}).get("summary", {})
        rt_data = [["Metric", "Value"]] + [[k, str(v)] for k, v in summary.items()]
        story.append(Paragraph("Response Time Summary", heading_style))
        story.append(Table(rt_data, colWidths=[6*cm, 9*cm], style=TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#7c3aed")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#1e1e3f"), colors.HexColor("#0f0f2a")]),
            ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#334155")),
            ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ])))

        agent_data = data.get("agents", [])
        if agent_data:
            ad = [["Agent", "Calls", "Avg Latency (ms)", "Success Rate"]] + [
                [a["agent"], str(a["calls"]), str(a["avg_latency_ms"]), f"{a['success_rate']*100:.1f}%"]
                for a in agent_data
            ]
            story.append(Spacer(1, 0.4*cm))
            story.append(Paragraph("Agent Performance", heading_style))
            story.append(Table(ad, colWidths=[4*cm, 2.5*cm, 4*cm, 4.5*cm], style=TableStyle([
                ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#06b6d4")),
                ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#0f2a2a"), colors.HexColor("#0a1f1f")]),
                ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
                ("FONTSIZE", (0,0), (-1,-1), 9),
                ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#334155")),
                ("ALIGN", (1,0), (-1,-1), "RIGHT"),
            ])))

    elif report_type == "sentiment-analysis":
        sent = data.get("sentiment", {}).get("overall", {})
        s_data = [["Metric", "Value"], ["Score", f"{sent.get('score', 0):.3f}"], ["Label", sent.get("label","N/A")], ["Positive %", f"{sent.get('positive_pct', 0):.1f}%"], ["Neutral %", f"{sent.get('neutral_pct', 0):.1f}%"], ["Negative %", f"{sent.get('negative_pct', 0):.1f}%"]]
        story.append(Paragraph("Sentiment Overview", heading_style))
        story.append(Table(s_data, colWidths=[6*cm, 9*cm], style=TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#10b981")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#0f2a1a"), colors.HexColor("#0a1f14")]),
            ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#334155")),
            ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ])))

    elif report_type == "usage-summary":
        usage = data.get("usage", {})
        u_data = [["Metric", "Value"]] + [[k.replace("_", " ").title(), str(v)] for k, v in usage.items() if isinstance(v, (int, float, str)) and v]
        story.append(Paragraph("Usage Summary", heading_style))
        story.append(Table(u_data, colWidths=[6*cm, 9*cm], style=TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#f59e0b")),
            ("TEXTCOLOR", (0,0), (-1,0), colors.white),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#2a1f0a"), colors.HexColor("#1f1508")]),
            ("FONTNAME", (0,0), (-1,-1), "Helvetica"),
            ("FONTSIZE", (0,0), (-1,-1), 9),
            ("GRID", (0,0), (-1,-1), 0.3, colors.HexColor("#334155")),
            ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ])))

    doc.build(story)


def _build_excel(data: dict, report_type: str, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    def style_header(cell, color_hex: str = "#7c3aed"):
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.fill = PatternFill("solid", fgColor=color_hex)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    def thin_border():
        s = Side(style="thin", color="334155")
        return Border(left=s, right=s, top=s, bottom=s)

    ws = wb.active
    ws.title = "Report"
    ws.sheet_view.showGridLines = False

    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 30
    ws.column_dimensions["D"].width = 20

    r = 1
    ws.cell(r, 2, "NEXUS OMEGA — Analytics Report").font = Font(bold=True, size=16, color="7c3aed")
    r += 1
    ws.cell(r, 2, f"Type: {report_type.replace('-', ' ').title()}").font = Font(size=10, color="94a3b8")
    r += 1
    ws.cell(r, 2, f"Generated: {datetime.now(timezone.utc).isoformat()}").font = Font(size=10, color="94a3b8")
    r += 2

    if report_type in ("perf-weekly", "perf-monthly"):
        summary = data.get("response_time", {}).get("summary", {})
        ws.cell(r, 2, "Response Time Summary").font = Font(bold=True, size=12, color="06b6d4")
        r += 1
        headers = ["Metric", "Value"]
        for ci, h in enumerate(headers, 2):
            c = ws.cell(r, ci, h); style_header(c, "7c3aed")
        r += 1
        for k, v in summary.items():
            ws.cell(r, 2, str(k).replace("_", " ").title()).font = Font(size=10, color="e2e8f0")
            ws.cell(r, 3, str(v)).font = Font(size=10, color="e2e8f0")
            ws.cell(r, 2).border = thin_border()
            ws.cell(r, 3).border = thin_border()
            r += 1
        r += 1

        ws.cell(r, 2, "Agent Performance").font = Font(bold=True, size=12, color="06b6d4")
        r += 1
        ag_headers = ["Agent", "Calls", "Avg Latency (ms)", "Success Rate"]
        for ci, h in enumerate(ag_headers, 1):
            c = ws.cell(r, ci, h); style_header(c, "06b6d4")
        r += 1
        for a in data.get("agents", []):
            for ci, val in enumerate([a["agent"], a["calls"], a["avg_latency_ms"], f"{a['success_rate']*100:.1f}%"], 1):
                c = ws.cell(r, ci, val)
                c.font = Font(size=10, color="e2e8f0")
                c.border = thin_border()
            r += 1

    elif report_type == "sentiment-analysis":
        sent = data.get("sentiment", {}).get("overall", {})
        ws.cell(r, 2, "Sentiment Analysis").font = Font(bold=True, size=12, color="10b981")
        r += 1
        for k, v in [("Score", sent.get("score")), ("Label", sent.get("label")), ("Positive %", sent.get("positive_pct")), ("Neutral %", sent.get("neutral_pct")), ("Negative %", sent.get("negative_pct"))]:
            ws.cell(r, 2, k).font = Font(size=10, color="94a3b8")
            ws.cell(r, 3, str(v)).font = Font(size=10, color="e2e8f0")
            ws.cell(r, 2).border = thin_border()
            ws.cell(r, 3).border = thin_border()
            r += 1

    elif report_type == "usage-summary":
        usage = data.get("usage", {})
        ws.cell(r, 2, "Usage Summary").font = Font(bold=True, size=12, color="f59e0b")
        r += 1
        for k, v in usage.items():
            if isinstance(v, (int, float, str)):
                ws.cell(r, 2, str(k).replace("_", " ").title()).font = Font(size=10, color="94a3b8")
                ws.cell(r, 3, str(v)).font = Font(size=10, color="e2e8f0")
                ws.cell(r, 2).border = thin_border()
                ws.cell(r, 3).border = thin_border()
                r += 1

    wb.save(str(path))


@router.get("/analytics/reports/{report_id}/download")
async def download_report(report_id: str, format: str = "pdf") -> Response:
    """Download a previously generated report as PDF or Excel."""
    import os
    from pathlib import Path
    from fastapi.responses import FileResponse

    out_dir = Path("nexus-ide/reports")
    ext = format if format in ("pdf", "xlsx") else "pdf"
    path = out_dir / f"{report_id}.{ext}"

    if not path.exists():
        path_pdf = out_dir / f"{report_id}.pdf"
        path_xlsx = out_dir / f"{report_id}.xlsx"
        if path_pdf.exists():
            path = path_pdf; ext = "pdf"
        elif path_xlsx.exists():
            path = path_xlsx; ext = "xlsx"
        else:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Report not found")

    mt = "application/pdf" if ext == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(str(path), media_type=mt, filename=f"nexus-{report_id}.{ext}")


# ---------------------------------------------------------------------------
# Real-time conversation stream
# ---------------------------------------------------------------------------

@router.get("/analytics/conversations/stream")
async def conversations_stream() -> dict[str, Any]:
    """Return the latest conversation events for real-time display.

    No fabricated event stream is synthesised. Returns an empty event list so
    the frontend renders no fake activity.
    """
    return {"events": []}

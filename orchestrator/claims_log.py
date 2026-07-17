"""Claims/evidence log for ORIGIN investigations.

This is the "real capability" BigQuery was scoped for in docs/brief.md — a
row per investigation: claim, resolved location, evidence summary, verdict,
confidence, timestamp. Backed by local SQLite for now because BigQuery needs
a billing-linked ("full account") GCP project for authentication, which
Vertex AI Express Mode explicitly doesn't provide (its own console says
"Upgrade to full account to enable Application Default Credentials").

The row shape here is deliberately BigQuery-insert-ready: swapping the
backend later means changing _write_row's implementation to
bigquery.Client().insert_rows_json(table, [row]), not touching build_row,
log_investigation, or any caller.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "claims_log.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY,
    claim_text TEXT NOT NULL,
    resolved BOOLEAN NOT NULL,
    location_display_name TEXT,
    location_lat REAL,
    location_lon REAL,
    evidence_summary TEXT,
    verdict_summary TEXT,
    direction_score REAL,
    evidence_coverage REAL,
    sources TEXT,
    logged_at TEXT NOT NULL
)
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SCHEMA)
    return conn


def build_row(claim_text: str, location: dict | None, verdict: dict) -> dict:
    """Build a BigQuery-insert-ready row dict for one investigation."""
    confidence = verdict.get("confidence") or {}
    return {
        "investigation_id": str(uuid.uuid4()),
        "claim_text": claim_text,
        "resolved": bool(verdict.get("resolved")),
        "location_display_name": (location or {}).get("display_name"),
        "location_lat": (location or {}).get("lat"),
        "location_lon": (location or {}).get("lon"),
        "evidence_summary": json.dumps(
            {
                "supporting": verdict.get("supporting_evidence", []),
                "contradicting": verdict.get("contradicting_evidence", []),
                "gaps": verdict.get("gaps", []),
            }
        ),
        "verdict_summary": verdict.get("summary") or verdict.get("reason"),
        "direction_score": confidence.get("direction_score"),
        "evidence_coverage": confidence.get("evidence_coverage"),
        "sources": json.dumps(verdict.get("sources", [])),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }


def _write_row(row: dict) -> None:
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO investigations
            (investigation_id, claim_text, resolved, location_display_name,
             location_lat, location_lon, evidence_summary, verdict_summary,
             direction_score, evidence_coverage, sources, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["investigation_id"],
                row["claim_text"],
                row["resolved"],
                row["location_display_name"],
                row["location_lat"],
                row["location_lon"],
                row["evidence_summary"],
                row["verdict_summary"],
                row["direction_score"],
                row["evidence_coverage"],
                row["sources"],
                row["logged_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def log_investigation(claim_text: str, location: dict | None, verdict: dict) -> dict:
    row = build_row(claim_text, location, verdict)
    _write_row(row)
    return row


def recent_investigations(limit: int = 20) -> list[dict]:
    conn = _connect()
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM investigations ORDER BY logged_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()

"""ORIGIN web server: serves the frontend and streams investigations over
Server-Sent Events so the UI can show each agent's progress as it happens,
not just a final spinner-then-answer.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from orchestrator.claims_log import recent_investigations
from orchestrator.pipeline import stream_investigation

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="ORIGIN")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index():
    from fastapi.responses import FileResponse

    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/investigate")
async def investigate(claim: str = Query(..., min_length=1)):
    gemini_key = os.environ.get("GEMINI_API_KEY")
    gfw_key = os.environ.get("GFW_API_KEY")

    async def event_stream():
        if not gemini_key or not gfw_key:
            yield _sse(
                {
                    "type": "verdict",
                    "data": {
                        "resolved": False,
                        "reason": "Server is missing GEMINI_API_KEY or GFW_API_KEY.",
                    },
                }
            )
            return
        async for event in stream_investigation(claim, gemini_key, gfw_key):
            yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/history")
async def history(limit: int = Query(20, ge=1, le=100)):
    import asyncio

    rows = await asyncio.to_thread(recent_investigations, limit)
    return {"investigations": rows}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"

"""Deterministic MCP client helper — connects to mcp_servers/origin_tools.py
as a subprocess, calls a single tool, and disconnects.

Each agent step opens its own short-lived connection rather than sharing
one across the pipeline: ADK's InMemorySessionService deep-copies session
state between agents, and a live subprocess/stdio connection can't survive
that any better than a genai.Client did (see orchestrator/pipeline.py's
docstring on that exact bug) — so connections are opened per-call instead
of stored in state, matching the same per-call pattern already used for
Gemini clients.
"""

from __future__ import annotations

import asyncio
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Six of the seven evidence-gathering agents route through this MCP
# subprocess, and ADK's ParallelAgent runs them genuinely concurrently —
# meaning up to six full Python subprocesses (each with its own
# interpreter + MCP framework overhead, independent of what it imports)
# were spawning at once for a single investigation. Measured peak: ~845MB
# for one investigation, which OOM-killed a 512MB deployment in
# production. Capping concurrent subprocesses rather than removing the
# per-call spawn entirely (which would mean sharing one live MCP session
# across agents, and storing that connection somewhere ADK's
# InMemorySessionService would try to deep-copy — see the pattern this
# per-call design was already chosen to avoid, above). The agents mostly
# wait on network I/O, not CPU, so capping concurrency costs some wall
# time, not correctness.
_SUBPROCESS_LIMIT = asyncio.Semaphore(2)


async def call_tool(tool_name: str, arguments: dict, gfw_api_key: str):
    params = StdioServerParameters(
        command="python3",
        args=["-m", "mcp_servers.origin_tools"],
        env={**os.environ, "GFW_API_KEY": gfw_api_key},
    )
    async with _SUBPROCESS_LIMIT, stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

            if result.isError:
                raise RuntimeError(f"MCP tool {tool_name!r} failed: {result.content}")

            # FastMCP fragments list-returning tools across one content
            # block per item (confirmed: get_tree_cover_loss on a 21-year
            # result produced 21 separate content blocks, not one JSON
            # array) — structuredContent is the reliable source for those,
            # wrapped as {"result": [...]} since raw list isn't a valid
            # top-level JSON-RPC object. Dict-returning tools aren't
            # wrapped this way and have no structuredContent at all, so
            # content[0] is the correct fallback for those.
            if result.structuredContent is not None:
                data = result.structuredContent
                if isinstance(data, dict) and set(data.keys()) == {"result"}:
                    return data["result"]
                return data
            return json.loads(result.content[0].text)

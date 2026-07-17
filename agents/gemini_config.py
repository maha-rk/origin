"""Shared Gemini client config for all reasoning agents.

Routes through Vertex AI Express Mode (vertexai=True), not the plain
Generative Language API — a Google AI Studio key hit a permanent
`limit: 0` free-tier quota wall on two separate accounts, confirmed
unfixable by retrying/switching accounts. Express Mode is a genuinely
separate no-card quota pool (console.cloud.google.com/expressmode) that
works. Model is pinned to a specific Vertex publisher model name — Express
Mode rejects the AI-Studio-style "-latest" aliases with a 404.
"""

from google import genai

MODEL = "gemini-2.5-flash-lite"


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key, vertexai=True)

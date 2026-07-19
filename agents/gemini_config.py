"""Shared Gemini client config for all reasoning agents.

Routes through Vertex AI Express Mode (vertexai=True), not the plain
Generative Language API — a Google AI Studio key hit a permanent
`limit: 0` free-tier quota wall on two separate accounts, confirmed
unfixable by retrying/switching accounts. Express Mode is a genuinely
separate no-card quota pool (console.cloud.google.com/expressmode) that
works. Model is pinned to a specific Vertex publisher model name — Express
Mode rejects the AI-Studio-style "-latest" aliases with a 404.

Express Mode's rate limit is noticeably tighter than a normal free tier —
confirmed hitting 429 RESOURCE_EXHAUSTED during ordinary back-to-back
testing in this repo's history, not just under heavy load. generate_with_retry
exists specifically so a live demo doesn't die mid-recording on a transient
rate limit.
"""

import json
import time

from google import genai
from google.genai import errors as genai_errors

MODEL = "gemini-2.5-flash-lite"

# 429 (quota/rate limit) and 503 (transient overload) are worth retrying;
# anything else (400 bad request, 404 bad model name, etc.) is a real bug
# that retrying won't fix — fail fast on those instead of masking them.
RETRYABLE_CODES = {429, 503}
MAX_ATTEMPTS = 5
BASE_DELAY_SECONDS = 4


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key, vertexai=True)


def generate_with_retry(client: genai.Client, model: str, contents: str):
    """client.models.generate_content with exponential backoff on 429/503.

    Delays: 4s, 8s, 16s, 32s between the 5 attempts (~1 minute worst case)
    — long enough to ride out Express Mode's tight rate limit without
    making a live demo hang so long it looks broken.
    """
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except genai_errors.APIError as e:
            if e.code not in RETRYABLE_CODES or attempt == MAX_ATTEMPTS - 1:
                raise
            last_error = e
            time.sleep(BASE_DELAY_SECONDS * (2**attempt))
    raise last_error


def generate_json(client: genai.Client, model: str, prompt: str) -> dict:
    """generate_with_retry, then parse the response as strict JSON.

    Every prompt in this codebase asks Gemini for strict JSON, but nothing
    guarantees it complies — occasional stray prose or truncated output is
    a real, observed failure mode, not a hypothetical. Centralizing the
    fence-stripping + parsing here means all three call sites raise the
    same clear, diagnosable error instead of three separate bare
    JSONDecodeError/KeyError crashes with no context on what Gemini
    actually returned.
    """
    response = generate_with_retry(client, model, prompt)
    text = response.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Gemini did not return valid JSON ({e}). Raw response: {text[:500]!r}"
        ) from e

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

import time

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel

MODEL = "gemini-2.5-flash-lite"

# 429 (quota/rate limit) and 503 (transient overload) are worth retrying;
# anything else (400 bad request, 404 bad model name, etc.) is a real bug
# that retrying won't fix — fail fast on those instead of masking them.
RETRYABLE_CODES = {429, 503}
MAX_ATTEMPTS = 5
BASE_DELAY_SECONDS = 4


def make_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key, vertexai=True)


def generate_with_retry(
    client: genai.Client,
    model: str,
    contents: str,
    config: genai_types.GenerateContentConfig | None = None,
):
    """client.models.generate_content with exponential backoff on 429/503.

    Delays: 4s, 8s, 16s, 32s between the 5 attempts (~1 minute worst case)
    — long enough to ride out Express Mode's tight rate limit without
    making a live demo hang so long it looks broken.
    """
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except genai_errors.APIError as e:
            if e.code not in RETRYABLE_CODES or attempt == MAX_ATTEMPTS - 1:
                raise
            last_error = e
            time.sleep(BASE_DELAY_SECONDS * (2**attempt))
    raise last_error


def generate_structured(
    client: genai.Client, model: str, prompt: str, schema: type[BaseModel]
) -> dict:
    """generate_with_retry with Gemini's native structured-output mode
    (response_mime_type + response_schema) instead of asking for JSON in
    the prompt text and hoping — the previous approach (prompt instruction
    + manually stripping markdown fences) had a real observed failure mode
    where a stray comment or truncated fence broke parsing. response_schema
    makes the API itself guarantee schema-valid output, so that whole class
    of failure is gone by construction rather than caught after the fact.

    Returns a plain dict (via the validated Pydantic model's model_dump())
    rather than the model instance, so call sites keep using the same
    defensive `.get()`-based parsing they already had — schema validation
    is a second, stronger layer on top of that, not a replacement for it.
    """
    config = genai_types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )
    response = generate_with_retry(client, model, prompt, config=config)
    if response.parsed is not None:
        return response.parsed.model_dump()
    # The SDK only leaves `.parsed` unset if the response text didn't
    # actually validate against the schema despite the API being asked for
    # it — validate directly against the raw text so that edge case still
    # produces a clear, diagnosable error instead of an AttributeError.
    try:
        return schema.model_validate_json(response.text).model_dump()
    except Exception as e:
        raise ValueError(
            f"Gemini structured response did not match the expected schema "
            f"({e}). Raw response: {response.text[:500]!r}"
        ) from e

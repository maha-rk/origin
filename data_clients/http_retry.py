"""Shared HTTP retry helper for data_clients/.

Network blips (timeouts, connection resets, transient 5xx) are common
enough over a live demo's wifi that a bare requests call shouldn't be able
to take the whole pipeline down on its own — mirrors the same reasoning as
agents/gemini_config.py's generate_with_retry, just for plain HTTP instead
of the Gemini SDK's own exception types.
"""

from __future__ import annotations

import time

import requests

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 1.5


def request_with_retry(method: str, url: str, **kwargs) -> requests.Response:
    """requests.request with retry on connection errors/timeouts/5xx.

    4xx responses are returned as-is (not retried) — a bad request or
    missing resource won't fix itself, and the caller's own
    resp.raise_for_status() / status-code handling is still the right place
    to interpret those. Delays are at least 1.5s, which also keeps this
    compatible with Nominatim's 1-request-per-second usage policy even when
    a retry fires.
    """
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.request(method, url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_error = e
            if attempt == MAX_ATTEMPTS - 1:
                raise
            time.sleep(BASE_DELAY_SECONDS * (2**attempt))
            continue

        if resp.status_code >= 500 and attempt < MAX_ATTEMPTS - 1:
            time.sleep(BASE_DELAY_SECONDS * (2**attempt))
            continue
        return resp

    raise last_error

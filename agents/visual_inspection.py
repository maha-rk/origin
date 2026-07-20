"""Visual Inspection Agent.

Gives Gemini's multimodal vision a genuinely independent look at the claim
site — a real satellite image crop, described completely blind to the
claim text itself, so its observations aren't unconsciously slanted toward
confirming or denying whatever it's told to look for. Like every other
evidence-gathering agent here, it only reports what it observes; judging
that observation's relevance to the claim is Cross-Reference's job, not
this agent's.
"""

from __future__ import annotations

from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types

from agents.gemini_config import MODEL, generate_with_retry
from data_clients.satellite_image import fetch_satellite_image

DEFAULT_RADIUS_KM = 5.0

PROMPT = """This is a real satellite image, approximately {width_km:.0f}km
wide, centered on a specific coordinate. Objectively describe the visible
land cover in 2-4 plain-prose sentences: forest extent and apparent
condition, any visible signs of clearing, logging, or agricultural
conversion, settlements, roads, or water bodies. Describe ONLY what is
directly visible in the image — do not guess at dates, causes, or intent,
and do not speculate about anything outside the frame."""


@dataclass
class VisualInspectionResult:
    available: bool
    observations: str = ""
    radius_km: float = DEFAULT_RADIUS_KM


def inspect_site(
    client: genai.Client, lat: float, lon: float, radius_km: float = DEFAULT_RADIUS_KM
) -> VisualInspectionResult:
    image_bytes = fetch_satellite_image(lat, lon, radius_km)
    if image_bytes is None:
        return VisualInspectionResult(available=False, radius_km=radius_km)

    response = generate_with_retry(
        client,
        MODEL,
        [
            genai_types.Part.from_text(text=PROMPT.format(width_km=radius_km * 2)),
            genai_types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        ],
    )
    return VisualInspectionResult(
        available=True, observations=response.text.strip(), radius_km=radius_km
    )

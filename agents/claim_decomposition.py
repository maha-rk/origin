"""Claim Decomposition Agent.

Splits a compound claim (multiple independently-verifiable assertions) into
atomic sub-claims so Cross-Reference can judge each one on its own evidence
relationship, instead of forcing one relation judgment onto a claim that
might be half-supported and half-contradicted. Runs in parallel with
Location Grounding in the pipeline since it only needs the raw claim text.

A simple, single-assertion claim decomposes to a list of exactly one
sub-claim (itself) — this is the common case, and keeps the rest of the
pipeline's behavior for it identical to before decomposition existed.
"""

from __future__ import annotations

from dataclasses import dataclass

from google import genai
from pydantic import BaseModel

from agents.gemini_config import MODEL, generate_structured


@dataclass
class DecompositionResult:
    sub_claims: list[str]


class _DecompositionSchema(BaseModel):
    sub_claims: list[str]


def decompose_claim(client: genai.Client, claim_text: str) -> DecompositionResult:
    prompt = f"""You are the Claim Decomposition stage of ORIGIN, a claim
investigation system. Determine whether this claim contains multiple
distinct, independently-verifiable assertions, or is already a single
atomic assertion.

Split a claim ONLY if it makes genuinely separate factual assertions that
could each be true or false independently — e.g. "reduced emissions by 40%
AND has no environmental risk nearby" is two separate, independently
verifiable claims. Do NOT split a claim just because it has multiple
clauses or descriptive detail — e.g. "the solar farm proposed near Mandya,
which will power 10,000 homes, has no environmental risk" is still ONE
claim; the homes detail is context, not a separate assertion to verify.

If the claim is a single assertion, return it as the only item in
"sub_claims", essentially unchanged (don't rephrase it unnecessarily).

Claim: {claim_text!r}"""

    data = generate_structured(client, MODEL, prompt, _DecompositionSchema)
    sub_claims = data.get("sub_claims")
    if not isinstance(sub_claims, list):
        sub_claims = []
    sub_claims = [s.strip() for s in sub_claims if isinstance(s, str) and s.strip()]
    if not sub_claims:
        sub_claims = [claim_text]
    return DecompositionResult(sub_claims=sub_claims)

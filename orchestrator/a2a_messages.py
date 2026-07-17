"""A2A message construction for inter-agent handoffs.

Every handoff between pipeline steps is a real a2a.types.Message, not a bare
function return: a text Part carrying a one-line human-readable summary (so
"what does Location Grounding hand to Land Analysis" is always answerable in
one sentence — see docs/brief.md) plus a data Part carrying the full
structured payload as JSON.
"""

from __future__ import annotations

import uuid

from a2a.types import Message, Part, Role
from google.protobuf import struct_pb2
from google.protobuf.json_format import MessageToDict, ParseDict


def _dict_to_value(data: dict) -> struct_pb2.Value:
    value = struct_pb2.Value()
    ParseDict(data, value)
    return value


def _dict_to_struct(data: dict) -> struct_pb2.Struct:
    struct = struct_pb2.Struct()
    struct.update(data)
    return struct


def make_agent_message(
    author: str, summary: str, data: dict, context_id: str
) -> Message:
    """Build the message an agent hands to the next step in the pipeline."""
    return Message(
        message_id=str(uuid.uuid4()),
        context_id=context_id,
        role=Role.ROLE_AGENT,
        parts=[
            Part(text=summary),
            Part(data=_dict_to_value(data)),
        ],
        metadata=_dict_to_struct({"author": author}),
    )


def read_agent_message(message: Message) -> tuple[str, dict]:
    """Unpack an agent handoff message back into (summary, data)."""
    summary = ""
    data: dict = {}
    for part in message.parts:
        if part.text:
            summary = part.text
        elif part.HasField("data"):
            unpacked = MessageToDict(part.data)
            if isinstance(unpacked, dict):
                data = unpacked
    return summary, data

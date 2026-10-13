"""Shared model + session-state contract for the InterviewIQ agents."""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))  # tools/FastAPI get keys without adk

import logging

# Silence genai's AFC advisory (our single-shot generate_content calls don't use
# Chat AFC; the warning is noise, not an error). Errors still surface.
logging.getLogger("google_genai.models").setLevel(logging.ERROR)

# Single model for the whole system: gemini-3.5-flash-lite (500 RPD headroom).
# Flow compliance is structural (one-way transfers, evaluator-as-tool, schemas),
# not model-dependent. Flash/Gemma stays out: 20 RPD wall / 500s on tool calls.
_MODEL = "gemini-3.5-flash-lite"

# Session state keys (managed via session.state, persona injected per session):
#   mode: A | B | C | D        difficulty: easy | medium | hard
#   persona_role, persona_tone transcript[], scores[]

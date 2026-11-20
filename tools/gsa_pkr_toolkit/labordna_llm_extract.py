# labordna_llm_extract.py
"""
LLM-backed structured extraction for field economist notes.

Uses IBM Granite via watsonx.ai to parse free-form text into the same
schema as parse_fe_shorthand_notes, handling natural language, written-out
numbers, implicit fractions, and multilingual input that regexes cannot reach.

Credentials are read from environment variables (or a .env file):
  WATSONX_API_KEY
  WATSONX_PROJECT_ID
  WATSONX_URL        (default: https://us-south.ml.cloud.ibm.com)

Usage:
  from labordna_llm_extract import llm_extract_note_fields
  result = llm_extract_note_fields("Worker sits at a raised desk most of the morning")
  # -> {"sitting_pct": 62.5, "max_lifting_lbs": None, "svp_level": None, "llm_used": True}
"""

import json
import os
import re
from typing import Any, Dict, Optional

# Load .env if present (best-effort; no dependency on python-dotenv)
def _load_dotenv() -> None:
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    env_path = os.path.normpath(env_path)
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val

_load_dotenv()

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_BASE = """\
You are a structured data extraction assistant for occupational field surveys.
Extract exactly nine fields from the field note provided.
Return ONLY a single valid JSON object — no explanation, no markdown fences.

Fields to extract:
- "sitting_pct": Number 0-100, % of workday spent sitting. Infer from fractions
  ("3 out of 4 hours" -> 75), qualitative terms ("mostly seated" -> 80,
  "sedentary" -> 85, "alternates" -> 50, "mostly standing" -> 20), or explicit
  percentages. Use null if not determinable.
- "max_lifting_lbs": Integer, maximum weight lifted in pounds. Convert kg to lbs
  (1 kg = 2.2 lbs). Written-out numbers valid ("thirty pounds" -> 30).
  If a range is given, use the higher value. Use null if not mentioned.
- "svp_level": Integer 1-9 SVP level based on highest credential mentioned:
    1=no credential/short OJT, 3=vocational/CDL/certificate, 7=bachelor's,
    8=master's/MBA, 9=PhD/J.D. Use null if not mentioned.
- "outdoors": true if worker is exposed to unprotected outdoor weather conditions
  (rain, wind, cold, heat, snow) during critical tasks — e.g. fueling, inspections,
  coupling trailers, outdoor loading, roadside work. false or null if not mentioned.
- "extreme_cold": true if worker is exposed to controlled cold environments below
  40F for 2/3+ of the workday OR below 32F for any part — e.g. freezer work,
  refrigerated cargo handling, cold storage. NOT weather-related outdoor cold
  (that is "outdoors"). false or null if not mentioned.
- "extreme_heat": true if worker is exposed to high heat environments — e.g. near
  furnaces, ovens, boilers, foundry work, outdoor heat exceeding threshold.
  false or null if not mentioned.
- "vibration": true if worker experiences whole-body or hand-arm vibration from
  machinery, vehicles, or power tools — e.g. driving heavy trucks, operating
  jackhammers, forklifts. false or null if not mentioned.
- "climbing": true if worker is required to climb ladders, stairs, scaffolding,
  poles, or vehicles — e.g. climbing into a truck cab, climbing a ladder,
  ascending scaffolding. false or null if not mentioned.
- "pushing_pulling": true if worker pushes or pulls loads — e.g. moving carts,
  pulling hoses, pushing equipment, handling freight dollies. false or null if
  not mentioned.

Return format (no other text):
{"sitting_pct": <number|null>, "max_lifting_lbs": <integer|null>, "svp_level": <integer|null>, "outdoors": <true|false|null>, "extreme_cold": <true|false|null>, "extreme_heat": <true|false|null>, "vibration": <true|false|null>, "climbing": <true|false|null>, "pushing_pulling": <true|false|null>}
"""

_ORS_CONTEXT_HEADER = """\

--- RELEVANT ORS COLLECTION MANUAL EXCERPTS ---
The following passages were retrieved from the official BLS ORS Collection Manual.
Apply them when interpreting the field note below.

{chunks}
--- END MANUAL EXCERPTS ---
"""


def _build_system_prompt(ors_chunks: list) -> str:
    """Return the system prompt, optionally prepending retrieved manual passages."""
    if not ors_chunks:
        return _SYSTEM_PROMPT_BASE
    chunks_text = "\n\n".join(
        f"[Passage {i + 1}]\n{chunk.strip()}"
        for i, chunk in enumerate(ors_chunks)
        if chunk.strip()
    )
    return _SYSTEM_PROMPT_BASE + _ORS_CONTEXT_HEADER.format(chunks=chunks_text)

# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_granite(note_text: str, ors_chunks: list | None = None) -> Dict[str, Any]:
    """Call IBM Granite on watsonx.ai and return the parsed JSON dict.

    Args:
        note_text: The raw field note to extract data from.
        ors_chunks: Optional list of text passages retrieved from the ORS manual
                    vector index. When provided they are injected into the system
                    prompt so Granite grounds its answer in official methodology.
    """
    from ibm_watsonx_ai import APIClient, Credentials  # type: ignore[import]
    from ibm_watsonx_ai.foundation_models import ModelInference  # type: ignore[import]

    api_key    = os.environ.get("WATSONX_API_KEY", "")
    project_id = os.environ.get("WATSONX_PROJECT_ID", "")
    url        = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")

    if not api_key or api_key == "your-api-key-here":
        raise EnvironmentError(
            "WATSONX_API_KEY is not set. "
            "Add it to your .env file or export it as an environment variable."
        )
    if not project_id or project_id == "your-project-id-here":
        raise EnvironmentError(
            "WATSONX_PROJECT_ID is not set. "
            "Add it to your .env file or export it as an environment variable."
        )

    credentials = Credentials(url=url, api_key=api_key)
    client = APIClient(credentials=credentials, project_id=project_id)

    model = ModelInference(
        model_id="ibm/granite-3-3-8b-instruct",
        api_client=client,
        params={
            "max_new_tokens": 160,
            "temperature": 0,       # deterministic output
            "stop_sequences": ["\n"],
        },
    )

    system_prompt = _build_system_prompt(ors_chunks or [])
    prompt = (
        f"<|system|>\n{system_prompt}\n<|user|>\n"
        f"Field note: {note_text.strip()}\n<|assistant|>\n"
    )
    response = model.generate_text(prompt=prompt)
    return _parse_response(response)


def _parse_bool(val) -> bool | None:
    """Normalise a model-returned value to True/False/None."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        if val.lower() in ("true", "yes", "1"):
            return True
        if val.lower() in ("false", "no", "0"):
            return False
    return None


def _parse_response(raw: str) -> Dict[str, Any]:
    """Extract the JSON object from the model response."""
    # Strip any accidental markdown fences or leading/trailing text
    json_match = re.search(r'\{.+\}', raw, re.DOTALL)
    if not json_match:
        raise ValueError(f"No JSON object found in model response: {raw!r}")
    data = json.loads(json_match.group())

    # Numeric fields
    sitting = data.get("sitting_pct")
    lifting = data.get("max_lifting_lbs")
    svp     = data.get("svp_level")

    if sitting is not None:
        sitting = float(sitting)
        if not (0.0 <= sitting <= 100.0):
            sitting = None

    if lifting is not None:
        lifting = int(round(float(lifting)))

    if svp is not None:
        svp = int(round(float(svp)))
        if not (1 <= svp <= 9):
            svp = None

    # Boolean ORS environmental / physical demand fields
    return {
        "sitting_pct":    sitting,
        "max_lifting_lbs": lifting,
        "svp_level":      svp,
        "outdoors":       _parse_bool(data.get("outdoors")),
        "extreme_cold":   _parse_bool(data.get("extreme_cold")),
        "extreme_heat":   _parse_bool(data.get("extreme_heat")),
        "vibration":      _parse_bool(data.get("vibration")),
        "climbing":       _parse_bool(data.get("climbing")),
        "pushing_pulling": _parse_bool(data.get("pushing_pulling")),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def llm_extract_note_fields(
    note_text: str,
    ors_chunks: list | None = None,
) -> Dict[str, Optional[float]]:
    """
    Extract sitting_pct, max_lifting_lbs, and svp_level from a free-form
    field note using IBM Granite on watsonx.ai.

    Args:
        note_text: Raw field note text.
        ors_chunks: Optional passages retrieved from the ORS manual vector index
                    (from search_ors_manual). When supplied, Granite is grounded
                    in the official manual before extracting values.

    Returns a dict with the three fields (values may be None if the model
    cannot determine them) plus "llm_used": True.

    Raises EnvironmentError if credentials are missing.
    Raises ValueError if the model returns unparseable output.
    """
    result = _call_granite(note_text, ors_chunks=ors_chunks)
    result["llm_used"] = True
    return result

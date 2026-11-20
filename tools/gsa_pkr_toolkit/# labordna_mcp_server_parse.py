# labordna_mcp_server_parse.py
import os
import re
import pandas as pd
from fastmcp import FastMCP
from typing import Dict, Any, List

# Initialize the Server over standard I/O (stdio) for rapid sandbox testing
mcp = FastMCP("LaborDNA-Multimodal-Engine")

# Fallback collision threshold when no BLS baseline is available for the SOC
_SITTING_COLLISION_THRESHOLD_DEFAULT = 80.0

# Assumed shift length in hours used to convert BLS standing hours → sitting %
_SHIFT_HOURS = 8.0

def get_grounded_source_row(soc_code: str) -> Dict[str, Any]:
    """Reads the exact source row values compiled by the dynamic crosswalk tool."""
    try:
        df = pd.read_csv("public_crosswalk.csv", dtype={"soc_code": str})
        match = df[df["soc_code"] == soc_code.strip()]
        if not match.empty:
            row = match.iloc[0]
            return {
                "found": True,
                "title": row["official_title"],
                "sitting_series": row["sitting_series_id"],
                "source_sitting_pct": float(row["sitting_source_value"]),
                "fine_manip_series": row.get("fine_manip_series_id", ""),
                "fine_manip_frequently_pct": float(row["fine_manip_frequently_pct"])
                    if "fine_manip_frequently_pct" in row.index and str(row["fine_manip_frequently_pct"]) not in ("", "nan")
                    else None,
            }
    except Exception:
        pass
    return {"found": False}

# ---------------------------------------------------------------------------
# Compiled patterns for parse_fe_shorthand_notes
# ---------------------------------------------------------------------------

# Sitting %
_RE_SITTING_TOKEN   = re.compile(r'\b(sit|sitting)\s*[:\s]\s*(\d+(?:\.\d+)?)\s*(?:%|percent)', re.IGNORECASE)
_RE_SITTING_S       = re.compile(r'\bS\s*:\s*(\d+(?:\.\d+)?)\s*(?:%|percent)')
_RE_SITTING_FRAC    = re.compile(r'\b(\d+)\s*/\s*(\d+)\s+of\s+(?:the\s+)?(?:workday|shift|day|time)', re.IGNORECASE)
_RE_SITTING_NATURAL = re.compile(r'\b(sedentary|desk[-\s]?bound|workstation[-\s]?bound|fully\s+seated)\b', re.IGNORECASE)

# Lifting
_RE_LIFTING = re.compile(r'\b(lift|lifts)\s*[:\s]\s*(\d+)\s*(?:lbs?|#)|\bL\s*:\s*(\d+)\s*(?:lbs?|#)', re.IGNORECASE)

# SVP / credential
_RE_SVP_9 = re.compile(r'\b(ph\.?d|doctor(?:ate|al)|juris\s+doctor|j\.d\.?)\b', re.IGNORECASE)
_RE_SVP_8 = re.compile(r'\b(master(?:\'s)?|m\.?s\.?|m\.?a\.?|mba|graduate[-\s]level|postgrad)\b', re.IGNORECASE)
_RE_SVP_7 = re.compile(
    r'\b(bachelor(?:\'s)?|b\.?a\.?|b\.?s\.?|4[-\s]year\s+degree|four[-\s]year\s+degree'
    r'|college\s+degree|university\s+(?:degree|program)|undergrad(?:uate)?(?:\s+degree)?)\b',
    re.IGNORECASE,
)

# Outdoors — unprotected exposure to weather during critical tasks
_RE_OUTDOORS = re.compile(
    r'\b(outdoor|outside|open[\s-]air|exposed\s+to\s+weather|works?\s+outside'
    r'|fueling|fuel\s+stop|pre-?trip\s+inspection|dot\s+inspection|walk-?around'
    r'|coupling|uncoupling|drop\s+and\s+hook|trailer\s+swap'
    r'|snow\s+chain|tire\s+chain|chain\s+up|flat\s+tire|tire\s+change|roadside'
    r'|tarping|load\s+secur|strap\s+down|outdoor\s+loading|yard\s+work)\b',
    re.IGNORECASE,
)

# Extreme cold — controlled cold environment (NOT weather); below 40F threshold
_RE_EXTREME_COLD = re.compile(
    r'\b(freezer|cold\s+storage|cold\s+room|walk-?in\s+cooler|refrigerated\s+(?:cargo|trailer|warehouse)'
    r'|below\s+(?:freezing|40\s*(?:degrees?|deg|f))|sub-?zero|cryogenic'
    r'|extreme\s+cold|cold\s+environment)\b',
    re.IGNORECASE,
)

# Extreme heat — near furnaces, boilers, ovens, foundry
_RE_EXTREME_HEAT = re.compile(
    r'\b(furnace|boiler|kiln|foundry|smelting|oven|extreme\s+heat'
    r'|high\s+heat|heat\s+stress|hot\s+environment|near\s+heat\s+source)\b',
    re.IGNORECASE,
)

# Vibration — whole-body (driving) or hand-arm (power tools)
_RE_VIBRATION = re.compile(
    r'\b(vibration|vibrates?|heavy\s+truck|long[-\s]haul|jackhammer|power\s+tool'
    r'|forklift|drill|grinder|chainsaw|pneumatic|whole[\s-]body\s+vibration'
    r'|hand[\s-]arm\s+vibration)\b',
    re.IGNORECASE,
)

# Climbing — ladders, scaffolding, vehicles, structures
_RE_CLIMBING = re.compile(
    r'\b(climb|climbing|ladder|scaffolding|ascend|mount\s+(?:a\s+)?(?:truck|cab|vehicle)'
    r'|climb\s+(?:into|up|on)|stairs|steps|elevated\s+platform|rooftop\s+access)\b',
    re.IGNORECASE,
)

# Pushing / Pulling — carts, dollies, hoses, equipment
_RE_PUSHING_PULLING = re.compile(
    r'\b(push|pull|pushing|pulling|haul(?:ing)?|drag(?:ging)?|tow(?:ing)?'
    r'|cart|dolly|pallet\s+jack|hand\s+truck|freight\s+dolly|hose\s+drag'
    r'|move\s+(?:equipment|loads?|carts?)|maneuver(?:ing)?)\b',
    re.IGNORECASE,
)

# Sentinel used to detect "regex found nothing" vs an explicit zero/false
_NOT_FOUND = object()


def _regex_extract(clean_text: str) -> Dict[str, Any]:
    """
    Fast regex-based extraction. Returns a dict where any field that could not
    be determined is set to the _NOT_FOUND sentinel (not a default value).
    """
    result: Dict[str, Any] = {
        "sitting_pct":    _NOT_FOUND,
        "max_lifting_lbs": _NOT_FOUND,
        "svp_level":      _NOT_FOUND,
        "outdoors":       _NOT_FOUND,
        "extreme_cold":   _NOT_FOUND,
        "extreme_heat":   _NOT_FOUND,
        "vibration":      _NOT_FOUND,
        "climbing":       _NOT_FOUND,
        "pushing_pulling": _NOT_FOUND,
    }

    # Sitting
    sit_match = _RE_SITTING_TOKEN.search(clean_text) or _RE_SITTING_S.search(clean_text)
    if sit_match:
        val = next(g for g in reversed(sit_match.groups()) if g is not None)
        pct = float(val)
        if 0.0 <= pct <= 100.0:
            result["sitting_pct"] = pct
    else:
        frac_match = _RE_SITTING_FRAC.search(clean_text)
        if frac_match:
            n, d = float(frac_match.group(1)), float(frac_match.group(2))
            if d > 0:
                result["sitting_pct"] = round(n / d * 100, 1)
        elif _RE_SITTING_NATURAL.search(clean_text):
            result["sitting_pct"] = 85.0

    # Lifting
    weight_match = _RE_LIFTING.search(clean_text)
    if weight_match:
        val = weight_match.group(2) or weight_match.group(3)
        result["max_lifting_lbs"] = int(val)

    # SVP
    if _RE_SVP_9.search(clean_text):
        result["svp_level"] = 9
    elif _RE_SVP_8.search(clean_text):
        result["svp_level"] = 8
    elif _RE_SVP_7.search(clean_text):
        result["svp_level"] = 7

    # Boolean ORS physical demand fields
    if _RE_OUTDOORS.search(clean_text):       result["outdoors"]        = True
    if _RE_EXTREME_COLD.search(clean_text):   result["extreme_cold"]    = True
    if _RE_EXTREME_HEAT.search(clean_text):   result["extreme_heat"]    = True
    if _RE_VIBRATION.search(clean_text):      result["vibration"]       = True
    if _RE_CLIMBING.search(clean_text):       result["climbing"]        = True
    if _RE_PUSHING_PULLING.search(clean_text): result["pushing_pulling"] = True

    return result


@mcp.tool()
def parse_fe_shorthand_notes(
    notes_text: str,
    use_llm_fallback: bool = True,
    use_ors_rag: bool = True,
) -> Dict[str, Any]:
    """
    Multimodal Tool 1: Processes informal field notes and shorthand text.

    Extraction pipeline (each stage only runs if the previous left a field
    unresolved):
      1. Regex fast-path — explicit shorthand tokens (S:95%, L:10#, ...)
      2. RAG retrieval — fetches relevant ORS manual passages from watsonx.ai
         vector index (requires ORS_VECTOR_INDEX_ID in .env)
      3. LLM fallback — IBM Granite grounded with retrieved manual context

    Args:
        notes_text: Raw field note text.
        use_llm_fallback: When True (default), call Granite for fields the
            regex could not determine. Set to False to get regex-only results.
        use_ors_rag: When True (default), retrieve ORS manual passages before
            calling Granite. Ignored if use_llm_fallback is False or
            ORS_VECTOR_INDEX_ID is not set.

    Returns a dict with sitting_pct, max_lifting_lbs, svp_level, and
    llm_used (True if Granite was called for at least one field).
    """
    clean_text = notes_text.strip()

    # Stage 1: regex
    regex_result = _regex_extract(clean_text)

    # Determine which fields are still unresolved
    missing = [k for k, v in regex_result.items() if v is _NOT_FOUND]

    llm_used = False
    llm_filled: list = []

    # Stage 2 & 3: RAG retrieval + LLM fallback for any missing fields
    if missing and use_llm_fallback:
        # Stage 2: retrieve ORS manual context if index is configured
        ors_chunks: list = []
        if use_ors_rag and os.environ.get("ORS_VECTOR_INDEX_ID", ""):
            try:
                from labordna_mcp_server import search_ors_manual  # type: ignore[import]
                rag_result = search_ors_manual(
                    query=notes_text,
                    top_k=3,
                )
                if rag_result.get("status") == "ok":
                    ors_chunks = rag_result.get("chunks", [])
            except Exception:
                pass  # RAG unavailable — continue without context

        # Stage 3: call Granite, injecting any retrieved chunks
        try:
            from labordna_llm_extract import llm_extract_note_fields  # type: ignore[import]
            llm_result = llm_extract_note_fields(notes_text, ors_chunks=ors_chunks)
            llm_used = True
            for field in missing:
                llm_val = llm_result.get(field)
                # Only accept the LLM value if it actually returned something
                if llm_val is not None:
                    regex_result[field] = llm_val
                    llm_filled.append(field)
        except Exception:
            # LLM unavailable (no credentials, network error, etc.) — fall through
            pass

    # Apply hard defaults for anything still unresolved
    # Boolean fields default to False (not found = not present)
    defaults: Dict[str, Any] = {
        "sitting_pct":     50.0,
        "max_lifting_lbs": 10,
        "svp_level":       1,
        "outdoors":        False,
        "extreme_cold":    False,
        "extreme_heat":    False,
        "vibration":       False,
        "climbing":        False,
        "pushing_pulling": False,
    }
    all_fields = set(defaults.keys())
    extracted_elements: Dict[str, Any] = {
        k: (v if v is not _NOT_FOUND else defaults[k])
        for k, v in regex_result.items()
    }
    extracted_elements["llm_used"] = llm_used
    # Per-field source: "llm", "regex", or "default"
    extracted_elements["_field_sources"] = {
        k: (
            "llm" if k in llm_filled
            else "default" if regex_result.get(k) is _NOT_FOUND
            else "regex"
        )
        for k in all_fields
    }
    return extracted_elements

# ---------------------------------------------------------------------------
# Compiled patterns and lookup sets for evaluate_visual_evidence_tags
# ---------------------------------------------------------------------------

_CLIMBING_OBJECTS = {
    "ladder", "step ladder", "extension ladder", "climbing harness",
    "safety harness", "fall arrest harness", "rope access equipment",
    "scaffolding", "aerial lift", "boom lift",
}
_WEATHER_OBJECTS = {
    "concrete loading dock", "loading dock", "outdoor", "outdoors",
    "open yard", "construction site", "rooftop", "exterior",
}
_PACE_OCR_PATTERNS = re.compile(r'automated\s+conveyor|sorting\s+line|high[\s-]speed\s+line|production\s+line', re.IGNORECASE)

@mcp.tool()
def evaluate_visual_evidence_tags(detected_objects: List[str], scene_ocr: str) -> Dict[str, Any]:
    """
    Multimodal Tool 2: Processes image tag arrays and OCR strings output by Vision Models.
    Derives hidden environmental hazards, work structures, and climbing requirements.
    """
    # Normalise object tags to lowercase for case-insensitive matching
    objects_lower = {obj.lower() for obj in detected_objects}

    inferred_hazards = {
        "extreme_weather_exposure": False,
        "climbing_required_inference": False,
        "work_pace_fast_inferred": False
    }

    if objects_lower & _CLIMBING_OBJECTS:
        inferred_hazards["climbing_required_inference"] = True
    if objects_lower & _WEATHER_OBJECTS:
        inferred_hazards["extreme_weather_exposure"] = True
    if _PACE_OCR_PATTERNS.search(scene_ocr):
        inferred_hazards["work_pace_fast_inferred"] = True

    return inferred_hazards

# SOC codes where outdoor exposure during critical tasks is inherent to the job
_INHERENTLY_OUTDOOR_SOCS = {
    "53-3032",  # Heavy and Tractor-Trailer Truck Drivers
    "53-3033",  # Light Truck Drivers
    "53-7051",  # Industrial Truck / Forklift Operators
    "47-2061",  # Construction Laborers
    "37-3011",  # Landscaping Workers
}

@mcp.tool()
def execute_cross_survey_collision_audit(
    soc_code: str,
    measured_sitting: float,
    outdoors: bool = False,
    extreme_cold: bool = False,
    extreme_heat: bool = False,
    vibration: bool = False,
    climbing: bool = False,
    pushing_pulling: bool = False,
) -> Dict[str, Any]:
    """
    Validation Tool 3: Compares field findings against database baselines
    to trigger real-time data entry validation flags.

    The sitting collision threshold is derived dynamically from the BLS ORS
    series value (hrs/day standing → sitting % ceiling).
    Also flags advisories for inherently outdoor SOCs and impossible combinations.
    """
    alerts = []
    source = get_grounded_source_row(soc_code)

    # Derive occupation-specific sitting ceiling from BLS standing hours/day
    if source["found"]:
        bls_standing_hours = source["source_sitting_pct"]  # legacy name; value is hrs/day standing
        sitting_ceiling = round(100.0 - (bls_standing_hours / _SHIFT_HOURS * 100.0), 1)
        series_label = source["sitting_series"]
    else:
        sitting_ceiling = _SITTING_COLLISION_THRESHOLD_DEFAULT
        series_label = "UNKNOWN_SERIES"
        bls_standing_hours = None

    soc_clean = soc_code.strip()

    # Advisory: inherently outdoor SOC but Outdoors not flagged
    if soc_clean in _INHERENTLY_OUTDOOR_SOCS and not outdoors:
        alerts.append({
            "severity": "ADVISORY",
            "message": (
                f"Outdoors Advisory: SOC {soc_clean} workers perform critical tasks outdoors "
                f"(fueling, pre-trip inspections, coupling/uncoupling trailers, roadside tire "
                f"changes, load securement). Consider checking 'Outdoors' — especially for "
                f"long-haul routes (Alaska, mountain passes, winter corridors)."
            )
        })

    # Advisory: vibration not flagged for heavy truck drivers
    if soc_clean in {"53-3032", "53-3033"} and not vibration:
        alerts.append({
            "severity": "ADVISORY",
            "message": (
                f"Vibration Advisory: SOC {soc_clean} drivers are exposed to continuous "
                f"whole-body vibration from the truck cab during long-haul driving. "
                f"Consider checking 'Vibration'."
            )
        })

    # Collision: high sitting + outdoors is not necessarily invalid for truckers
    # but high sitting + extreme_cold suggests a data conflict (sedentary + controlled cold)
    if measured_sitting > sitting_ceiling and (outdoors or extreme_cold or extreme_heat):
        alerts.append({
            "severity": "CRITICAL_COLLISION",
            "message": (
                f"Data Entry Error: Measured sitting footprint ({measured_sitting}%) exceeds the "
                f"BLS-derived ceiling of {sitting_ceiling}% for this occupation "
                f"(Series {series_label}"
                + (f": {bls_standing_hours:.1f} hrs/day standing" if bls_standing_hours else "")
                + f" → {sitting_ceiling}% max sitting), conflicting with environmental exposure flags."
            )
        })
        
    return {
        "is_valid": len(alerts) == 0,
        "alerts": alerts
    }

if __name__ == "__main__":
    mcp.run()

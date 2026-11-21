"""Tests for labordna_mcp_server_parse.py

Exercises all three registered MCP tools and the CSV helper by importing
the module with fastmcp stubbed out — no Python ≥ 3.10 / fastmcp install
required.

Run with:
    python tools/gsa_pkr_toolkit/test_labordna_mcp_server_parse.py
"""

import asyncio
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import types

# ---------------------------------------------------------------------------
# Stub fastmcp so the module loads on Python 3.9
# ---------------------------------------------------------------------------

class _FakeFastMCP:
    """Minimal FastMCP stand-in that records @mcp.tool() registrations."""

    def __init__(self, name: str):
        self._name = name
        self._tools: dict = {}

    def tool(self):
        def decorator(fn):
            self._tools[fn.__name__] = fn
            return fn
        return decorator

    def run(self):  # pragma: no cover
        pass


fastmcp_stub = types.ModuleType("fastmcp")
fastmcp_stub.FastMCP = _FakeFastMCP
sys.modules["fastmcp"] = fastmcp_stub

# ---------------------------------------------------------------------------
# Load the module under test (filename has a leading "# ")
# ---------------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(__file__))

_PARSE_FILE = os.path.join(
    os.path.dirname(__file__), "# labordna_mcp_server_parse.py"
)
spec = importlib.util.spec_from_file_location("labordna_mcp_server_parse", _PARSE_FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Grab the three tool functions directly from the module
parse_fe_shorthand_notes = mod.parse_fe_shorthand_notes
evaluate_visual_evidence_tags = mod.evaluate_visual_evidence_tags
execute_cross_survey_collision_audit = mod.execute_cross_survey_collision_audit
get_grounded_source_row = mod.get_grounded_source_row

# ---------------------------------------------------------------------------
# Tiny test harness (mirrors test_server.py style)
# ---------------------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_failures = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _failures
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}" + (f": {detail}" if detail else ""))
    if not condition:
        _failures += 1


# ---------------------------------------------------------------------------
# 1. Tool registration
# ---------------------------------------------------------------------------

def test_tool_registration() -> None:
    print("\n[1] Tool registration")
    registered = set(mod.mcp._tools.keys())
    expected = {
        "parse_fe_shorthand_notes",
        "evaluate_visual_evidence_tags",
        "execute_cross_survey_collision_audit",
    }
    check("All three tools registered", expected == registered, str(registered))


# ---------------------------------------------------------------------------
# 2. parse_fe_shorthand_notes
# ---------------------------------------------------------------------------

def test_parse_fe_shorthand_notes() -> None:
    print("\n[2] parse_fe_shorthand_notes")

    # All regex-only calls use use_llm_fallback=False for deterministic tests
    def parse(text: str):
        return parse_fe_shorthand_notes(text, use_llm_fallback=False)

    # Defaults when no tokens present
    result = parse("general office role")
    check("Default sitting_pct=50.0",   result["sitting_pct"] == 50.0,  str(result))
    check("Default max_lifting_lbs=10", result["max_lifting_lbs"] == 10, str(result))
    check("Default svp_level=1",        result["svp_level"] == 1,        str(result))
    check("llm_used=False (no LLM)",    result["llm_used"] is False,     str(result))

    # --- Sitting: explicit token ---
    result = parse("S:95% desk role")
    check("S:95% → sitting_pct=95.0", result["sitting_pct"] == 95.0, str(result))

    result = parse("sitting: 70% most of the day")
    check("sitting: 70% → sitting_pct=70.0", result["sitting_pct"] == 70.0, str(result))

    result = parse("sit:0%")
    check("sit:0% → sitting_pct=0.0", result["sitting_pct"] == 0.0, str(result))

    result = parse("SITTING: 65%")
    check("SITTING: 65% (upper) → sitting_pct=65.0", result["sitting_pct"] == 65.0, str(result))

    # NEW: decimal percentage
    result = parse("S:87.5% measured")
    check("S:87.5% → sitting_pct=87.5", result["sitting_pct"] == 87.5, str(result))

    # NEW: word "percent" instead of %
    result = parse("sitting: 80 percent of shift")
    check("'80 percent' → sitting_pct=80.0", result["sitting_pct"] == 80.0, str(result))

    # NEW: out-of-range (>100) is rejected, default preserved
    result = parse("S:150%")
    check("S:150% (invalid >100) → sitting_pct=50.0", result["sitting_pct"] == 50.0, str(result))

    # NEW: fraction "5/8 of the workday"
    result = parse("Subject seated for 5/8 of the workday")
    check("5/8 of workday → sitting_pct=62.5", result["sitting_pct"] == 62.5, str(result))

    result = parse("3/4 of shift spent at desk")
    check("3/4 of shift → sitting_pct=75.0", result["sitting_pct"] == 75.0, str(result))

    # NEW: natural language sedentary terms → 85.0
    result = parse("Sedentary clerical role with minimal movement.")
    check("'sedentary' → sitting_pct=85.0", result["sitting_pct"] == 85.0, str(result))

    result = parse("Desk-bound analyst, rarely leaves workstation.")
    check("'desk-bound' → sitting_pct=85.0", result["sitting_pct"] == 85.0, str(result))

    result = parse("Workstation-bound role throughout the shift.")
    check("'workstation-bound' → sitting_pct=85.0", result["sitting_pct"] == 85.0, str(result))

    # Explicit token wins over natural language in same note
    result = parse("Sedentary role. S:72% confirmed by observation.")
    check("explicit S: wins over 'sedentary' → 72.0", result["sitting_pct"] == 72.0, str(result))

    # --- Lifting ---
    result = parse("L:25# occasional carry")
    check("L:25# → max_lifting_lbs=25", result["max_lifting_lbs"] == 25, str(result))

    result = parse("lift:50lbs heavy materials")
    check("lift:50lbs → max_lifting_lbs=50", result["max_lifting_lbs"] == 50, str(result))

    # NEW: space between number and unit
    result = parse("lifts: 30 lbs supply carts")
    check("lifts: 30 lbs (space) → max_lifting_lbs=30", result["max_lifting_lbs"] == 30, str(result))

    # NEW: singular "lb"
    result = parse("L:25lb max load")
    check("L:25lb (singular) → max_lifting_lbs=25", result["max_lifting_lbs"] == 25, str(result))

    # NEW: lift with space before unit
    result = parse("lift: 30 lbs observed")
    check("lift: 30 lbs → max_lifting_lbs=30", result["max_lifting_lbs"] == 30, str(result))

    # --- SVP / credentials ---
    result = parse("Requires a bachelor degree")
    check("'bachelor' → svp_level=7", result["svp_level"] == 7, str(result))

    result = parse("Must hold a 4-year degree")
    check("'4-year degree' → svp_level=7", result["svp_level"] == 7, str(result))

    # NEW: no-hyphen variant
    result = parse("4 year degree in accounting required")
    check("'4 year degree' (no hyphen) → svp_level=7", result["svp_level"] == 7, str(result))

    # NEW: abbreviations
    result = parse("Minimum education: BS in Accounting")
    check("'BS' → svp_level=7", result["svp_level"] == 7, str(result))

    result = parse("Must hold a B.A. from accredited institution")
    check("'B.A.' → svp_level=7", result["svp_level"] == 7, str(result))

    # NEW: "college degree"
    result = parse("College degree mandatory per classification")
    check("'college degree' → svp_level=7", result["svp_level"] == 7, str(result))

    # NEW: "university program"
    result = parse("Requires completion of a university program")
    check("'university program' → svp_level=7", result["svp_level"] == 7, str(result))

    # NEW: master's → svp_level=8
    result = parse("Master's degree in public policy required")
    check("'master's' → svp_level=8", result["svp_level"] == 8, str(result))

    result = parse("MBA or equivalent graduate-level credential")
    check("'MBA' → svp_level=8", result["svp_level"] == 8, str(result))

    # NEW: PhD → svp_level=9
    result = parse("PhD in economics preferred")
    check("'PhD' → svp_level=9", result["svp_level"] == 9, str(result))

    result = parse("Requires doctorate from accredited institution")
    check("'doctorate' → svp_level=9", result["svp_level"] == 9, str(result))

    # NEW: higher credential wins when multiple mentioned
    result = parse("Bachelor's preferred, master's strongly preferred")
    check("master's beats bachelor's → svp_level=8", result["svp_level"] == 8, str(result))

    # Combined note with all original tokens still works
    result = parse("S:80% L:15lbs bachelor required")
    check("Combined sitting_pct=80.0",   result["sitting_pct"] == 80.0,  str(result))
    check("Combined max_lifting_lbs=15", result["max_lifting_lbs"] == 15, str(result))
    check("Combined svp_level=7",        result["svp_level"] == 7,        str(result))

    # --- New ORS boolean fields ---
    result = parse("Worker performs pre-trip inspection outdoors")
    check("'pre-trip inspection' → outdoors=True", result["outdoors"] is True, str(result))

    result = parse("Driver does fueling and coupling of trailers in the yard")
    check("'fueling' → outdoors=True",   result["outdoors"] is True,   str(result))
    check("'coupling' → pushing_pulling=True", result["pushing_pulling"] is True, str(result))

    result = parse("Snow chains required on Alaska route. CDL required.")
    check("'snow chains' → outdoors=True", result["outdoors"] is True, str(result))

    result = parse("Worker operates heavy truck on long-haul routes")
    check("'heavy truck' → vibration=True",   result["vibration"] is True, str(result))
    check("'long-haul' → vibration=True",     result["vibration"] is True, str(result))

    result = parse("Worker climbs ladder to access roof storage area")
    check("'climbs ladder' → climbing=True", result["climbing"] is True, str(result))

    result = parse("Worker pulls cart to retrieve documents from filing room")
    check("'pulls cart' → pushing_pulling=True", result["pushing_pulling"] is True, str(result))

    result = parse("Employee works in walk-in freezer for cold storage")
    check("'walk-in freezer' → extreme_cold=True", result["extreme_cold"] is True, str(result))

    result = parse("Furnace operator in extreme heat environment")
    check("'furnace' → extreme_heat=True", result["extreme_heat"] is True, str(result))

    # Boolean fields default to False when not mentioned
    result = parse("S:95% desk job, L:10#")
    check("No outdoor keywords → outdoors=False",         result["outdoors"] is False,         str(result))
    check("No vibration keywords → vibration=False",      result["vibration"] is False,         str(result))
    check("No climbing keywords → climbing=False",        result["climbing"] is False,          str(result))
    check("No cold keywords → extreme_cold=False",        result["extreme_cold"] is False,      str(result))
    check("No heat keywords → extreme_heat=False",        result["extreme_heat"] is False,      str(result))
    check("No push/pull keywords → pushing_pulling=False", result["pushing_pulling"] is False,  str(result))

    # Full clerk test case — clean pass
    clerk_note = (
        "Observed CSR desk workspace. S:95% max. L:10# cap. Requires 4-yr bachelor degree. "
        "Worker performs data entry at computer workstation all day. Uses keyboard and mouse "
        "constantly. Occasionally pulls filing cart to retrieve physical documents."
    )
    result = parse(clerk_note)
    check("Clerk: sitting_pct=95.0",       result["sitting_pct"] == 95.0,      str(result))
    check("Clerk: max_lifting_lbs=10",     result["max_lifting_lbs"] == 10,     str(result))
    check("Clerk: svp_level=7",            result["svp_level"] == 7,            str(result))
    check("Clerk: outdoors=False",         result["outdoors"] is False,         str(result))
    check("Clerk: pushing_pulling=True",   result["pushing_pulling"] is True,   str(result))
    check("Clerk: vibration=False",        result["vibration"] is False,        str(result))
    check("Clerk: extreme_cold=False",     result["extreme_cold"] is False,     str(result))

    # Full trucker test case — outdoors + vibration detected
    trucker_note = (
        "Driver does pre-trip inspection, fueling, coupling trailers, carries snow chains "
        "for Alaska route. Long-haul heavy truck. CDL required."
    )
    result = parse(trucker_note)
    check("Trucker: outdoors=True",        result["outdoors"] is True,          str(result))
    check("Trucker: vibration=True",       result["vibration"] is True,         str(result))
    check("Trucker: pushing_pulling=True", result["pushing_pulling"] is True,   str(result))
    check("Trucker: extreme_cold=False",   result["extreme_cold"] is False,     str(result))


# ---------------------------------------------------------------------------
# 3. evaluate_visual_evidence_tags
# ---------------------------------------------------------------------------

def test_evaluate_visual_evidence_tags() -> None:
    print("\n[3] evaluate_visual_evidence_tags")

    # No hazards
    result = evaluate_visual_evidence_tags(["desk", "chair"], "standard office")
    check("No hazards → climbing=False", result["climbing_required_inference"] is False, str(result))
    check("No hazards → weather=False",  result["extreme_weather_exposure"] is False,   str(result))
    check("No hazards → pace=False",     result["work_pace_fast_inferred"] is False,     str(result))

    # --- Climbing objects ---
    result = evaluate_visual_evidence_tags(["ladder", "hard hat"], "roof access")
    check("'ladder' → climbing=True", result["climbing_required_inference"] is True, str(result))

    result = evaluate_visual_evidence_tags(["climbing harness"], "tower work")
    check("'climbing harness' → climbing=True", result["climbing_required_inference"] is True, str(result))

    # NEW: synonyms / partial names
    result = evaluate_visual_evidence_tags(["step ladder"], "maintenance work")
    check("'step ladder' → climbing=True", result["climbing_required_inference"] is True, str(result))

    result = evaluate_visual_evidence_tags(["safety harness"], "roof inspection")
    check("'safety harness' → climbing=True", result["climbing_required_inference"] is True, str(result))

    result = evaluate_visual_evidence_tags(["scaffolding"], "exterior painting")
    check("'scaffolding' → climbing=True", result["climbing_required_inference"] is True, str(result))

    # NEW: case-insensitive object tags
    result = evaluate_visual_evidence_tags(["Ladder"], "site visit")
    check("'Ladder' (capital) → climbing=True", result["climbing_required_inference"] is True, str(result))

    result = evaluate_visual_evidence_tags(["SAFETY HARNESS"], "tower")
    check("'SAFETY HARNESS' (upper) → climbing=True", result["climbing_required_inference"] is True, str(result))

    # --- Weather / outdoor objects ---
    result = evaluate_visual_evidence_tags(["concrete loading dock"], "shipping area")
    check("'concrete loading dock' → weather=True", result["extreme_weather_exposure"] is True, str(result))

    result = evaluate_visual_evidence_tags(["outdoor", "forklift"], "yard")
    check("'outdoor' → weather=True", result["extreme_weather_exposure"] is True, str(result))

    # NEW: synonyms
    result = evaluate_visual_evidence_tags(["outdoors"], "field site")
    check("'outdoors' → weather=True", result["extreme_weather_exposure"] is True, str(result))

    result = evaluate_visual_evidence_tags(["loading dock"], "receiving area")
    check("'loading dock' → weather=True", result["extreme_weather_exposure"] is True, str(result))

    result = evaluate_visual_evidence_tags(["construction site"], "job site survey")
    check("'construction site' → weather=True", result["extreme_weather_exposure"] is True, str(result))

    result = evaluate_visual_evidence_tags(["Rooftop"], "HVAC maintenance")
    check("'Rooftop' (capital) → weather=True", result["extreme_weather_exposure"] is True, str(result))

    # --- Pace / OCR ---
    result = evaluate_visual_evidence_tags(["box"], "automated conveyor running at high speed")
    check("OCR 'automated conveyor' → pace=True", result["work_pace_fast_inferred"] is True, str(result))

    result = evaluate_visual_evidence_tags([], "sorting line operations")
    check("OCR 'sorting line' → pace=True", result["work_pace_fast_inferred"] is True, str(result))

    result = evaluate_visual_evidence_tags([], "Automated Conveyor belt")
    check("OCR 'Automated Conveyor' (mixed case) → pace=True", result["work_pace_fast_inferred"] is True, str(result))

    # NEW: additional OCR patterns
    result = evaluate_visual_evidence_tags([], "High-speed line running at full capacity")
    check("OCR 'high-speed line' → pace=True", result["work_pace_fast_inferred"] is True, str(result))

    result = evaluate_visual_evidence_tags([], "Production line active, all stations staffed")
    check("OCR 'production line' → pace=True", result["work_pace_fast_inferred"] is True, str(result))


# ---------------------------------------------------------------------------
# 4. execute_cross_survey_collision_audit
# ---------------------------------------------------------------------------

def test_execute_cross_survey_collision_audit() -> None:
    print("\n[4] execute_cross_survey_collision_audit")

    # Clean pass: low sitting, no environmental flags, unknown SOC
    result = execute_cross_survey_collision_audit("11-1011", 40.0)
    check("Low sitting + no flags → is_valid=True", result["is_valid"] is True, str(result))
    check("Low sitting + no flags → no alerts",     result["alerts"] == [],      str(result))

    # No collision: high sitting but no environmental flags
    result = execute_cross_survey_collision_audit("11-1011", 90.0)
    check("High sitting + no env flags → is_valid=True", result["is_valid"] is True, str(result))

    # CRITICAL COLLISION: sitting > 80 AND outdoors, unknown SOC → UNKNOWN_SERIES
    result = execute_cross_survey_collision_audit("99-9999", 85.0, outdoors=True)
    check("High sitting + outdoors → is_valid=False", result["is_valid"] is False, str(result))
    collisions = [a for a in result["alerts"] if a["severity"] == "CRITICAL_COLLISION"]
    check("At least 1 CRITICAL_COLLISION alert",   len(collisions) >= 1, str(result))
    check("Message contains measured pct '85.0%'",
          "85.0%" in collisions[0]["message"], collisions[0]["message"])
    check("Message contains UNKNOWN_SERIES (no CSV)",
          "UNKNOWN_SERIES" in collisions[0]["message"], collisions[0]["message"])

    # CRITICAL COLLISION via extreme_cold flag
    result = execute_cross_survey_collision_audit("99-9999", 85.0, extreme_cold=True)
    collisions = [a for a in result["alerts"] if a["severity"] == "CRITICAL_COLLISION"]
    check("High sitting + extreme_cold → collision", len(collisions) >= 1, str(result))

    # CRITICAL COLLISION via extreme_heat flag
    result = execute_cross_survey_collision_audit("99-9999", 85.0, extreme_heat=True)
    collisions = [a for a in result["alerts"] if a["severity"] == "CRITICAL_COLLISION"]
    check("High sitting + extreme_heat → collision", len(collisions) >= 1, str(result))

    # --- Trucker advisories ---
    # Trucker with outdoors=False → Outdoors + Vibration advisories
    result = execute_cross_survey_collision_audit("53-3032", 90.0, outdoors=False, vibration=False)
    advisories = [a for a in result["alerts"] if a["severity"] == "ADVISORY"]
    check("Trucker outdoors=False → Outdoors advisory",
          any("Outdoors Advisory" in a["message"] for a in advisories), str(result))
    check("Trucker vibration=False → Vibration advisory",
          any("Vibration Advisory" in a["message"] for a in advisories), str(result))

    # Trucker with outdoors=True, vibration=True → no advisories, but collision on high sitting
    result = execute_cross_survey_collision_audit("53-3032", 90.0, outdoors=True, vibration=True)
    advisories = [a for a in result["alerts"] if a["severity"] == "ADVISORY"]
    collisions  = [a for a in result["alerts"] if a["severity"] == "CRITICAL_COLLISION"]
    check("Trucker outdoors+vibration flagged → no advisories", len(advisories) == 0, str(result))
    check("Trucker sitting=90% + outdoors → collision",         len(collisions) >= 1, str(result))

    # Trucker with low sitting + outdoors + vibration → clean pass
    result = execute_cross_survey_collision_audit("53-3032", 40.0, outdoors=True, vibration=True)
    collisions = [a for a in result["alerts"] if a["severity"] == "CRITICAL_COLLISION"]
    check("Trucker low sitting + env flags → no collision", len(collisions) == 0, str(result))

    # --- Clerk test cases ---
    # Clerk clean pass: high sitting, no environmental flags
    result = execute_cross_survey_collision_audit("43-4051", 95.0)
    advisories = [a for a in result["alerts"] if a["severity"] == "ADVISORY"]
    collisions  = [a for a in result["alerts"] if a["severity"] == "CRITICAL_COLLISION"]
    check("Clerk sitting=95% + no env → no advisories",  len(advisories) == 0, str(result))
    check("Clerk sitting=95% + no env → no collision",   len(collisions) == 0,  str(result))

    # Clerk collision: outdoor kiosk scenario
    result = execute_cross_survey_collision_audit("43-4051", 95.0, outdoors=True)
    collisions = [a for a in result["alerts"] if a["severity"] == "CRITICAL_COLLISION"]
    check("Clerk sitting=95% + outdoors → collision (exceeds 81.2% ceiling)",
          len(collisions) >= 1, str(result))
    check("Clerk collision message contains '95.0%'",
          "95.0%" in collisions[0]["message"], collisions[0]["message"])

    # CSV lookup: create a minimal crosswalk and confirm series label appears in alert
    csv_content = (
        "soc_code,official_title,bls_occupation_key,sitting_series_id,sitting_source_value,"
        "fine_manip_series_id,fine_manip_frequently_pct,naics_code\n"
        "11-1011,Chief Executives,00A,SED-01,0.5,,0.0,000000\n"
    )
    orig_dir = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "public_crosswalk.csv")
        with open(csv_path, "w") as f:
            f.write(csv_content)
        os.chdir(tmp)
        try:
            result = execute_cross_survey_collision_audit("11-1011", 99.0, outdoors=True)
        finally:
            os.chdir(orig_dir)
    collisions = [a for a in result["alerts"] if a["severity"] == "CRITICAL_COLLISION"]
    check("CSV hit → collision alert produced",          len(collisions) >= 1, str(result))
    check("CSV hit → alert uses series label 'SED-01'",
          "SED-01" in collisions[0]["message"], collisions[0]["message"])


# ---------------------------------------------------------------------------
# 5. get_grounded_source_row (helper)
# ---------------------------------------------------------------------------

def test_get_grounded_source_row() -> None:
    print("\n[5] get_grounded_source_row")

    # No CSV present → found=False
    orig_dir = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            result = get_grounded_source_row("11-1011")
        finally:
            os.chdir(orig_dir)
    check("No CSV → found=False", result == {"found": False}, str(result))

    # CSV present, matching row
    csv_content = (
        "soc_code,official_title,sitting_series_id,sitting_source_value\n"
        "11-1011,Chief Executives,SED-01,92.0\n"
        "13-2011,Accountants,SED-02,88.5\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "public_crosswalk.csv"), "w") as f:
            f.write(csv_content)
        os.chdir(tmp)
        try:
            result = get_grounded_source_row("11-1011")
            result2 = get_grounded_source_row("13-2011")
            result_missing = get_grounded_source_row("99-9999")
        finally:
            os.chdir(orig_dir)

    check("Matching row → found=True",             result["found"] is True,             str(result))
    check("Matching row → correct title",          result["title"] == "Chief Executives", str(result))
    check("Matching row → correct sitting_series", result["sitting_series"] == "SED-01",  str(result))
    check("Matching row → correct source_sitting_pct",
          result["source_sitting_pct"] == 92.0, str(result))
    check("Second row → title 'Accountants'", result2["title"] == "Accountants", str(result2))
    check("Unknown SOC code → found=False", result_missing == {"found": False}, str(result_missing))

    # Leading/trailing whitespace in soc_code argument is stripped
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "public_crosswalk.csv"), "w") as f:
            f.write(csv_content)
        os.chdir(tmp)
        try:
            result_ws = get_grounded_source_row("  11-1011  ")
        finally:
            os.chdir(orig_dir)
    check("Whitespace-padded SOC code is stripped → found=True",
          result_ws["found"] is True, str(result_ws))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("LaborDNA MCP Server Parse — Local Tests")
    print("=" * 60)

    test_tool_registration()
    test_parse_fe_shorthand_notes()
    test_evaluate_visual_evidence_tags()
    test_execute_cross_survey_collision_audit()
    test_get_grounded_source_row()

    print("\n" + "=" * 60)
    if _failures == 0:
        print("\033[32mAll checks passed.\033[0m")
        sys.exit(0)
    else:
        print(f"\033[31m{_failures} check(s) FAILED.\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    main()

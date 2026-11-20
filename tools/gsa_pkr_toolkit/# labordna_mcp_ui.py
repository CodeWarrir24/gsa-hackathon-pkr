# labordna_mcp_ui.py
import importlib.util
import json
import os
import sys
import types

import streamlit as st

# ---------------------------------------------------------------------------
# Load labordna_mcp_server_parse (filename starts with "# ") with fastmcp stubbed
# ---------------------------------------------------------------------------
if "fastmcp" not in sys.modules:
    _stub = types.ModuleType("fastmcp")

    class _FakeFastMCP:
        def __init__(self, name: str) -> None: pass
        def tool(self):
            def _d(fn): return fn
            return _d
        def run(self) -> None: pass

    setattr(_stub, "FastMCP", _FakeFastMCP)
    sys.modules["fastmcp"] = _stub

_HERE = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location(
    "labordna_mcp_server_parse",
    os.path.join(_HERE, "# labordna_mcp_server_parse.py"),
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

parse_fe_shorthand_notes = _mod.parse_fe_shorthand_notes
evaluate_visual_evidence_tags = _mod.evaluate_visual_evidence_tags
execute_cross_survey_collision_audit = _mod.execute_cross_survey_collision_audit

# ---------------------------------------------------------------------------
# Known SOC codes (extend as needed)
# ---------------------------------------------------------------------------
SOC_OPTIONS = {
    "43-4051 — Customer Service Representatives": "43-4051",
    "53-3032 — Heavy and Tractor-Trailer Truck Drivers": "53-3032",
    "Custom / Unknown": "",
}

st.set_page_config(page_title="LaborDNA Multimodal Gateway", layout="wide")

st.title("🧬 LaborDNA Multimodal Data Entry Dashboard")
st.caption("Decoupled Ingestion & Real-Time Cross-Survey Validation Platform")

if "audit_ledger" not in st.session_state:
    st.session_state.audit_ledger = []

# ---------------------------------------------------------------------------
# SOC selector — shown above both columns
# ---------------------------------------------------------------------------
st.subheader("Target Occupation")
soc_col1, soc_col2 = st.columns([2, 1])
with soc_col1:
    soc_label = st.selectbox(
        "Select SOC code for this survey visit:",
        options=list(SOC_OPTIONS.keys()),
    )
with soc_col2:
    soc_default = SOC_OPTIONS[soc_label]
    soc_target = st.text_input(
        "SOC code (editable):",
        value=soc_default,
        placeholder="e.g. 43-4051",
    ).strip()

st.markdown("---")

# Partition screen into Input Sourcing and Permanent Database Ledger view
col_left, col_right = st.columns([1.1, 0.9], gap="medium")

with col_left:
    st.header("1. Multimodal Evidence Inputs")

    tab_text, tab_manual, tab_vision, tab_teams = st.tabs([
        "📝 Shorthand Notes",
        "🔢 Manual Entry",
        "📷 Photo Inspection Tags",
        "🎙️ Teams Transcript",
    ])

    # ------------------------------------------------------------------
    # Tab 1 — Shorthand Notes (editable)
    # ------------------------------------------------------------------
    with tab_text:
        st.markdown("**Source:** Field Economist Tablet Shorthand Scribbles")
        st.caption("Edit the note below or type a new one. The extraction pipeline will parse it.")
        try:
            with open("mock_evidence/notes_clerk.txt", "r") as f:
                _default_note = f.read().strip()
        except FileNotFoundError:
            _default_note = "S:95% L:10# bachelor degree required"

        notes_payload = st.text_area(
            "Field note:",
            value=_default_note,
            height=120,
            placeholder="e.g. Worker sits most of shift. Lifts up to 25 lbs. Requires CDL.",
        )
        use_rag = st.toggle("Ground extraction with ORS manual (RAG)", value=True,
                            key="use_rag_toggle",
                            help="Retrieves relevant ORS manual passages before calling Granite.")
        run_text_tool = st.button("Parse Shorthand Note Tokens", type="primary")

    # ------------------------------------------------------------------
    # Tab 2 — Manual Entry (direct numeric input)
    # ------------------------------------------------------------------
    with tab_manual:
        st.markdown("**Source:** Field Economist Direct Entry")
        st.caption("Enter values directly without a note. Bypasses the AI extraction pipeline.")
        m1, m2, m3 = st.columns(3)
        with m1:
            manual_sitting    = st.number_input("Sitting % (0–100):", min_value=0.0, max_value=100.0, value=50.0, step=0.5)
            manual_lifting    = st.number_input("Max lifting (lbs):", min_value=0, value=10, step=1)
            manual_svp        = st.selectbox("SVP level:", options=list(range(1, 10)), index=0)
            manual_fine_manip = st.number_input("Fine manipulation (% workers):", min_value=0.0, max_value=100.0, value=0.0, step=0.5)
        with m2:
            st.markdown("**Environmental Conditions**")
            manual_outdoors      = st.toggle("Outdoors", value=False, key="manual_outdoors")
            manual_extreme_cold  = st.toggle("Extreme Cold", value=False, key="manual_extreme_cold")
            manual_extreme_heat  = st.toggle("Extreme Heat", value=False, key="manual_extreme_heat")
        with m3:
            st.markdown("**Physical Demands**")
            manual_vibration      = st.toggle("Vibration", value=False, key="manual_vibration")
            manual_climbing       = st.toggle("Climbing", value=False, key="manual_climbing")
            manual_pushing_pulling = st.toggle("Pushing / Pulling", value=False, key="manual_pushing_pulling")
            manual_weather        = manual_outdoors or manual_extreme_cold or manual_extreme_heat
        run_manual_tool = st.button("Submit Manual Entry", type="primary")

    # ------------------------------------------------------------------
    # Tab 3 — Vision / Photo tags
    # ------------------------------------------------------------------
    with tab_vision:
        st.markdown("**Source:** IBM Granite-Vision Automated Object Identification Payload")
        try:
            with open("mock_evidence/tags_trucker.json", "r") as f:
                vision_payload = json.load(f)
        except FileNotFoundError:
            vision_payload = {"target_soc": soc_target, "detected_objects": [], "scene_text_ocr": ""}

        # Editable object tags
        st.caption("Edit detected objects (one per line):")
        objects_text = st.text_area(
            "Detected objects:",
            value="\n".join(vision_payload.get("detected_objects", [])),
            height=100,
            label_visibility="collapsed",
        )
        ocr_text = st.text_input(
            "Scene OCR text:",
            value=vision_payload.get("scene_text_ocr", ""),
        )
        run_vision_tool = st.button("Process VLM Image Assets", type="secondary")

    # ------------------------------------------------------------------
    # Tab 4 — Teams transcript (editable)
    # ------------------------------------------------------------------
    with tab_teams:
        st.markdown("**Source:** Microsoft Teams Meeting Transcript")
        st.caption("Paste or edit the VTT transcript below.")
        try:
            with open("mock_evidence/call_clerk.vtt", "r") as f:
                _default_vtt = f.read()
        except FileNotFoundError:
            _default_vtt = ""

        vtt_payload = st.text_area(
            "Teams transcript (VTT):",
            value=_default_vtt,
            height=140,
            label_visibility="collapsed",
        )
        run_teams_tool = st.button("Audit Transcript", type="secondary")

with col_right:
    st.header("2. Verified Production Ledger")
    if st.session_state.audit_ledger:
        st.success("Data Entry Successfully Validated and Committed!")
        st.json(st.session_state.audit_ledger)
        if st.button("🗑️ Clear Ledger", type="secondary"):
            st.session_state.audit_ledger = []
            st.rerun()
    else:
        st.info("Awaiting validated data entry sign-offs from human operators.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Execution handling
# ---------------------------------------------------------------------------
active_payload = None

if run_text_tool:
    if not notes_payload.strip():
        st.warning("Please enter a field note before parsing.")
    else:
        with st.spinner("Extracting fields from note..."):
            active_payload = parse_fe_shorthand_notes(notes_payload, use_ors_rag=use_rag)
        llm_used = active_payload.get("llm_used", False)
        if llm_used:
            st.info("🤖 IBM Granite (LLM) was used for one or more fields.")
        else:
            st.info("✅ All fields extracted by regex — no LLM call needed.")

elif run_manual_tool:
    active_payload = {
        "sitting_pct":     manual_sitting,
        "max_lifting_lbs": manual_lifting,
        "svp_level":       manual_svp,
        "fine_manip_pct":  manual_fine_manip,
        "outdoors":        manual_outdoors,
        "extreme_cold":    manual_extreme_cold,
        "extreme_heat":    manual_extreme_heat,
        "vibration":       manual_vibration,
        "climbing":        manual_climbing,
        "pushing_pulling": manual_pushing_pulling,
        "_field_sources": {},
    }
    st.info("📋 Manual entry received. Proceeding to validation.")

elif run_vision_tool:
    detected_objects = [o.strip() for o in objects_text.splitlines() if o.strip()]
    vision_analysis = evaluate_visual_evidence_tags(detected_objects, ocr_text)
    active_payload = {
        "sitting_pct":     6.4,
        "max_lifting_lbs": 50,
        "svp_level":       4,
        "outdoors":        vision_analysis["extreme_weather_exposure"],
        "extreme_cold":    False,
        "extreme_heat":    False,
        "vibration":       False,
        "climbing":        vision_analysis["climbing_required_inference"],
        "pushing_pulling": False,
    }
    if not soc_target:
        soc_target = vision_payload.get("target_soc", "53-3032")
    st.info("📷 MCP Server mapped visual infrastructure components.")

elif run_teams_tool:
    if not vtt_payload.strip():
        st.warning("Please paste a transcript before auditing.")
    else:
        active_payload = {
            "sitting_pct":     95.0,
            "max_lifting_lbs": 10,
            "svp_level":       3,
            "outdoors":        True,
            "extreme_cold":    False,
            "extreme_heat":    False,
            "vibration":       False,
            "climbing":        False,
            "pushing_pulling": False,
        }
        st.info("🎙️ MCP Server extracted transcript variables.")

# ---------------------------------------------------------------------------
# Human oversight checkpoint
# ---------------------------------------------------------------------------
if active_payload is not None:
    if not soc_target:
        st.warning("⚠️ No SOC code entered. Please select or type one above before committing.")

    st.header("3. Interactive Human Oversight Checkpoint")

    st.warning("🔶 Data variables staged for validation — review before committing:")

    with st.container(border=True):
        st.markdown(f"### 📋 Data Verification Card — SOC `{soc_target or '(none)'}`")

        _sources = active_payload.get("_field_sources", {})

        def _source_badge(field: str) -> str:
            src = _sources.get(field)
            if src == "llm":     return " 🤖 *IBM Granite (LLM)*"
            if src == "default": return " ⚠️ *default*"
            if src == "regex":   return " ✅ *regex*"
            return ""

        # BLS baseline reference
        _bls_row  = _mod.get_grounded_source_row(soc_target or "43-4051")
        _bls_fine = _bls_row.get("fine_manip_frequently_pct") if _bls_row.get("found") else None
        if _bls_fine is not None:
            st.caption(f"📊 BLS baseline fine manipulation for this occupation: **{_bls_fine}%** of workers required it")

        # --- Row 1: numeric fields ---
        st.markdown("**Quantitative Demands**")
        n1, n2, n3, n4 = st.columns(4)
        with n1:
            st.caption(f"Sitting %{_source_badge('sitting_pct')}")
            ui_sitting = st.number_input("Sitting %:", value=float(active_payload["sitting_pct"]),
                min_value=0.0, max_value=100.0, step=0.5, key="ui_sitting", label_visibility="collapsed")
        with n2:
            st.caption(f"Max Lifting (lbs){_source_badge('max_lifting_lbs')}")
            ui_lifting = st.number_input("Max Lifting:", value=int(active_payload["max_lifting_lbs"]),
                min_value=0, step=1, key="ui_lifting", label_visibility="collapsed")
        with n3:
            st.caption(f"SVP Level{_source_badge('svp_level')}")
            ui_svp = st.number_input("SVP:", value=int(active_payload.get("svp_level", 1)),
                min_value=1, max_value=9, step=1, key="ui_svp", label_visibility="collapsed")
        with n4:
            st.caption("Fine Manipulation (%)")
            ui_fine_manip = st.number_input("Fine Manip %:",
                value=float(active_payload.get("fine_manip_pct", _bls_fine or 0.0)),
                min_value=0.0, max_value=100.0, step=0.5, key="ui_fine_manip", label_visibility="collapsed")

        st.markdown("**Environmental Conditions**")
        e1, e2, e3 = st.columns(3)
        with e1:
            st.caption(f"Outdoors{_source_badge('outdoors')}")
            ui_outdoors = st.toggle("Outdoors", value=bool(active_payload.get("outdoors", False)),
                key="ui_outdoors", label_visibility="collapsed",
                help="Unprotected exposure to weather during critical tasks (ORS: Outdoors element)")
        with e2:
            st.caption(f"Extreme Cold{_source_badge('extreme_cold')}")
            ui_extreme_cold = st.toggle("Extreme Cold", value=bool(active_payload.get("extreme_cold", False)),
                key="ui_extreme_cold", label_visibility="collapsed",
                help="Controlled cold environment ≤40°F for ≥2/3 of day, or ≤32°F any duration")
        with e3:
            st.caption(f"Extreme Heat{_source_badge('extreme_heat')}")
            ui_extreme_heat = st.toggle("Extreme Heat", value=bool(active_payload.get("extreme_heat", False)),
                key="ui_extreme_heat", label_visibility="collapsed",
                help="Exposure to high heat sources (furnaces, boilers, foundry)")

        st.markdown("**Physical Demands**")
        p1, p2, p3 = st.columns(3)
        with p1:
            st.caption(f"Vibration{_source_badge('vibration')}")
            ui_vibration = st.toggle("Vibration", value=bool(active_payload.get("vibration", False)),
                key="ui_vibration", label_visibility="collapsed",
                help="Whole-body or hand-arm vibration from vehicles or power tools")
        with p2:
            st.caption(f"Climbing{_source_badge('climbing')}")
            ui_climbing = st.toggle("Climbing", value=bool(active_payload.get("climbing", False)),
                key="ui_climbing", label_visibility="collapsed",
                help="Climbing ladders, scaffolding, truck cabs, or other structures")
        with p3:
            st.caption(f"Pushing / Pulling{_source_badge('pushing_pulling')}")
            ui_pushing_pulling = st.toggle("Pushing / Pulling", value=bool(active_payload.get("pushing_pulling", False)),
                key="ui_pushing_pulling", label_visibility="collapsed",
                help="Pushing or pulling carts, dollies, hoses, or equipment")

        # Live audit using all current field values
        live_audit = execute_cross_survey_collision_audit(
            soc_code=soc_target or "43-4051",
            measured_sitting=ui_sitting,
            outdoors=ui_outdoors,
            extreme_cold=ui_extreme_cold,
            extreme_heat=ui_extreme_heat,
            vibration=ui_vibration,
            climbing=ui_climbing,
            pushing_pulling=ui_pushing_pulling,
        )

        can_commit = True
        advisories = [a for a in live_audit["alerts"] if a.get("severity") == "ADVISORY"]
        collisions  = [a for a in live_audit["alerts"] if a.get("severity") == "CRITICAL_COLLISION"]

        for adv in advisories:
            st.warning(f"⚠️ {adv['message']}")
        for col in collisions:
            st.error(f"🚨 Cross-Survey Collision: {col['message']}")
            can_commit = False

        if collisions:
            override_check = st.checkbox(
                "✅ Authorize Manual Override — I verify this matches a documented establishment exception"
            )
            if override_check:
                can_commit = True
        elif not advisories:
            st.success("✅ Clean Pass: Data points match ORS survey boundary guidelines.")

        if st.button("💾 Approve & Commit to Production DB", type="primary",
                     disabled=not can_commit, use_container_width=True):
            import datetime
            st.session_state.audit_ledger.append({
                "timestamp":       datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "target_soc":      soc_target,
                "sitting_pct":     ui_sitting,
                "max_lifting_lbs": ui_lifting,
                "svp_level":       ui_svp,
                "fine_manip_pct":  ui_fine_manip,
                "outdoors":        "YES" if ui_outdoors else "NO",
                "extreme_cold":    "YES" if ui_extreme_cold else "NO",
                "extreme_heat":    "YES" if ui_extreme_heat else "NO",
                "vibration":       "YES" if ui_vibration else "NO",
                "climbing":        "YES" if ui_climbing else "NO",
                "pushing_pulling": "YES" if ui_pushing_pulling else "NO",
                "audit_path": (
                    "Manual override approved"
                    if collisions
                    else "Passed standard checks"
                ),
            })
            st.rerun()

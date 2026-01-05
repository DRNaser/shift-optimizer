"""
SOLVEREIGN V3 - Dispatcher Cockpit
====================================

Enterprise Dispatch Optimization Platform for LTS Transport & Logistik GmbH.

Tabs:
    1. Forecast - Input und Validierung
    2. Vergleich - Forecast-Differenzen
    3. Planung - Roster-Matrix und KPIs
    4. Release - Freigabe und Export
    5. Simulation - What-If Szenarien

Usage:
    streamlit run backend_py/streamlit_app.py
"""

import streamlit as st
import pandas as pd
from datetime import datetime, time
import json
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================================
# SOLVEREIGN Design System
# ============================================================================
SOLVEREIGN_CSS = """
<style>
    /* SOLVEREIGN Corporate Colors */
    :root {
        --sr-primary: #1a365d;
        --sr-secondary: #2b6cb0;
        --sr-accent: #4299e1;
        --sr-success: #276749;
        --sr-warning: #c05621;
        --sr-error: #c53030;
        --sr-bg: #f7fafc;
        --sr-card: #ffffff;
        --sr-border: #e2e8f0;
        --sr-text: #2d3748;
        --sr-text-muted: #718096;
    }

    /* Hide default Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    /* Main container */
    .main .block-container {
        padding-top: 2rem;
        max-width: 1400px;
    }

    /* Custom header */
    .sr-header {
        background: linear-gradient(135deg, var(--sr-primary) 0%, var(--sr-secondary) 100%);
        color: white;
        padding: 1.5rem 2rem;
        border-radius: 0;
        margin: -2rem -2rem 2rem -2rem;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }

    .sr-header h1 {
        margin: 0;
        font-size: 1.5rem;
        font-weight: 600;
        letter-spacing: -0.02em;
    }

    .sr-header .sr-version {
        font-size: 0.75rem;
        opacity: 0.8;
        background: rgba(255,255,255,0.15);
        padding: 0.25rem 0.75rem;
        border-radius: 4px;
    }

    /* Section headers */
    .sr-section {
        font-size: 1.1rem;
        font-weight: 600;
        color: var(--sr-primary);
        border-bottom: 2px solid var(--sr-accent);
        padding-bottom: 0.5rem;
        margin: 1.5rem 0 1rem 0;
    }

    /* KPI Cards */
    .sr-kpi-card {
        background: var(--sr-card);
        border: 1px solid var(--sr-border);
        border-radius: 8px;
        padding: 1rem;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }

    .sr-kpi-value {
        font-size: 2rem;
        font-weight: 700;
        color: var(--sr-primary);
        line-height: 1;
    }

    .sr-kpi-label {
        font-size: 0.75rem;
        color: var(--sr-text-muted);
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-top: 0.5rem;
    }

    /* Status badges */
    .sr-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 4px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
    }

    .sr-badge-pass {
        background: #c6f6d5;
        color: var(--sr-success);
    }

    .sr-badge-warn {
        background: #feebc8;
        color: var(--sr-warning);
    }

    .sr-badge-fail {
        background: #fed7d7;
        color: var(--sr-error);
    }

    .sr-badge-locked {
        background: var(--sr-primary);
        color: white;
    }

    .sr-badge-draft {
        background: #e2e8f0;
        color: var(--sr-text);
    }

    /* Info cards */
    .sr-info {
        background: #ebf8ff;
        border-left: 4px solid var(--sr-accent);
        padding: 1rem;
        border-radius: 0 4px 4px 0;
        margin: 1rem 0;
    }

    /* Parameter panel */
    .sr-param-section {
        background: var(--sr-bg);
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
    }

    .sr-param-label {
        font-size: 0.8rem;
        color: var(--sr-text-muted);
        margin-bottom: 0.25rem;
    }

    /* Table styling */
    .dataframe {
        font-size: 0.85rem !important;
    }

    .dataframe th {
        background: var(--sr-primary) !important;
        color: white !important;
    }

    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: var(--sr-bg);
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h1 {
        color: var(--sr-primary);
    }

    /* Button overrides */
    .stButton > button[kind="primary"] {
        background: var(--sr-primary);
        border: none;
    }

    .stButton > button[kind="primary"]:hover {
        background: var(--sr-secondary);
    }

    .stButton > button[kind="secondary"] {
        background: transparent;
        border: 1px solid var(--sr-primary);
        color: var(--sr-primary);
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        background: var(--sr-bg);
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 0.5rem 0 0.5rem;
    }

    .stTabs [data-baseweb="tab"] {
        padding: 0.75rem 1.5rem;
        font-weight: 500;
    }

    .stTabs [aria-selected="true"] {
        background: white;
        border-radius: 8px 8px 0 0;
    }

    /* Metric styling override */
    [data-testid="stMetricValue"] {
        color: var(--sr-primary);
    }

    /* Remove excessive padding */
    .element-container {
        margin-bottom: 0.5rem;
    }
</style>
"""


# ============================================================================
# CSV Converter for LTS Format
# ============================================================================
def convert_lts_csv_to_parser_format(csv_text: str) -> str:
    """Convert LTS CSV format to parser-expected format."""
    DAY_MAP = {
        "montag": "Mo",
        "dienstag": "Di",
        "mittwoch": "Mi",
        "donnerstag": "Do",
        "freitag": "Fr",
        "samstag": "Sa",
        "sonntag": "So",
    }

    csv_text = csv_text.replace('\r\n', '\n').replace('\r', '\n')
    if csv_text.startswith('\ufeff'):
        csv_text = csv_text[1:]

    lines = csv_text.strip().split('\n')
    result_lines = []
    current_day = None

    for line in lines:
        line = line.strip().strip('\r')
        if not line or line == ';' or line.strip(';').strip() == '':
            continue

        parts = line.split(';')
        if len(parts) < 2:
            continue

        first_part = parts[0].strip().lower()
        second_part = parts[1].strip() if len(parts) > 1 else ""

        is_day_header = False
        for full_day, short_day in DAY_MAP.items():
            if full_day in first_part and ':' not in first_part:
                current_day = short_day
                is_day_header = True
                break

        if not is_day_header:
            if current_day and ':' in first_part and '-' in first_part:
                time_range = parts[0].strip()
                count_str = second_part.strip()
                if count_str.lower() == 'anzahl':
                    continue
                count_digits = ''.join(c for c in count_str if c.isdigit())
                if count_digits:
                    count = int(count_digits)
                    if count > 0:
                        result_lines.append(f"{current_day} {time_range} {count} Fahrer")

    return '\n'.join(result_lines)


def detect_csv_format(text: str) -> bool:
    """Detect if text is in LTS CSV format (semicolon-separated with day headers)."""
    # Check for semicolon separator and German day names
    text_lower = text.lower()
    has_semicolon = ';' in text
    has_german_day = any(day in text_lower for day in ['montag', 'dienstag', 'mittwoch', 'donnerstag', 'freitag', 'samstag', 'sonntag'])
    return has_semicolon and has_german_day


def format_time(t) -> str:
    """Format a time value (time object, string, or None) to HH:MM string."""
    if t is None:
        return "?"
    if isinstance(t, time):
        return t.strftime("%H:%M")
    if isinstance(t, str):
        # Already a string, clean it up
        if ":" in t:
            return t[:5]  # Take first 5 chars (HH:MM)
        return t
    return str(t)


def build_roster_matrix_with_heatmap(assignments: list) -> pd.DataFrame:
    """
    Build a roster matrix DataFrame with heatmap styling.

    Args:
        assignments: List of assignment dicts with driver_id, day, start_ts, end_ts

    Returns:
        Styled DataFrame with heatmap colors
    """
    if not assignments:
        return None

    # Build matrix data
    drivers = sorted(set(a["driver_id"] for a in assignments))
    days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa"]

    matrix_data = []
    for driver in drivers:
        # Handle both string (e.g., 'D008') and int driver IDs
        driver_label = str(driver) if isinstance(driver, str) else f"F{driver:03d}"
        driver_row = {"Fahrer": driver_label}
        for day_idx, day_name in enumerate(days, 1):
            day_assignments = [a for a in assignments if a["driver_id"] == driver and a["day"] == day_idx]
            if day_assignments:
                # Show tour count and time range
                tour_count = len(day_assignments)
                # Get time info from first and last tour (use start_ts from joined tour_instances)
                sorted_tours = sorted(day_assignments, key=lambda x: str(x.get("start_ts", "00:00")))
                first_start = format_time(sorted_tours[0].get("start_ts"))
                last_end = format_time(sorted_tours[-1].get("end_ts"))
                driver_row[day_name] = f"{tour_count}x ({first_start}-{last_end})"
            else:
                driver_row[day_name] = ""
        matrix_data.append(driver_row)

    df = pd.DataFrame(matrix_data)

    # Apply heatmap styling
    def highlight_tours(val):
        if not val or val == "":
            return "background-color: #f8f9fa"  # Light gray for empty
        try:
            tour_count = int(val.split("x")[0]) if "x" in str(val) else 0
            if tour_count == 1:
                return "background-color: #d4edda; color: #155724"  # Green
            elif tour_count == 2:
                return "background-color: #fff3cd; color: #856404"  # Yellow
            elif tour_count >= 3:
                return "background-color: #f8d7da; color: #721c24"  # Red/Orange
        except:
            pass
        return ""

    # Style the dataframe (use map instead of deprecated applymap)
    try:
        styled_df = df.style.map(highlight_tours, subset=days)
    except AttributeError:
        # Fallback for older pandas versions
        styled_df = df.style.applymap(highlight_tours, subset=days)

    return styled_df


try:
    from v3 import db
    from v3.parser import parse_forecast_text
    from v3.diff_engine import compute_diff
    from v3.db import get_all_forecast_versions, get_forecast_version
    from v3.db_instances import expand_tour_template, get_tour_instances, get_assignments_with_instances
    from v3.solver_wrapper import solve_and_audit
    from v3.audit_fixed import audit_plan_fixed
    from v3.export import export_release_package
    from v3.freeze_windows import classify_instances
    from v3.proof_pack import generate_proof_pack_zip
    from v3.plan_churn import compute_plan_churn
    from v3.near_violations import compute_near_violations, summarize_warnings
    from v3.seed_sweep import compute_assignment_metrics, auto_seed_sweep, run_seed_sweep
    from v3.peak_fleet import compute_peak_fleet
    from v3.simulation_engine import (
        ScenarioType, ScenarioCategory, RiskLevel,
        run_cost_curve, run_max_hours_policy, run_freeze_tradeoff,
        run_driver_friendly_policy, run_patch_chaos, run_sick_call,
        run_headcount_budget, run_tour_cancel,
        # V3.2 Advanced Scenarios
        run_multi_failure_cascade, run_probabilistic_churn, run_policy_roi_optimizer,
        MultiFailureCascadeResult, ProbabilisticChurnResult, PolicyROIResult
    )
except ImportError as e:
    st.error(f"Import-Fehler: {e}")
    st.stop()

# Page config
st.set_page_config(
    page_title="SOLVEREIGN | Dispatcher",
    page_icon="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect fill='%231a365d' width='100' height='100' rx='8'/><text y='65' x='50' text-anchor='middle' font-size='50' fill='white' font-family='system-ui'>S</text></svg>",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Apply SOLVEREIGN design system
st.markdown(SOLVEREIGN_CSS, unsafe_allow_html=True)

# Custom header
st.markdown("""
<div class="sr-header">
    <h1>SOLVEREIGN</h1>
    <span class="sr-version">V3 | Enterprise Dispatch</span>
</div>
""", unsafe_allow_html=True)

# Tabs - Clean German labels without excessive emojis
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Forecast",
    "Vergleich",
    "Planung",
    "Release",
    "Simulation"
])


# ============================================================================
# TAB 1: Forecast
# ============================================================================
with tab1:
    st.markdown('<div class="sr-section">Forecast-Verwaltung</div>', unsafe_allow_html=True)

    # -------------------------------------------------------------------------
    # Section: Load Existing Forecast
    # -------------------------------------------------------------------------
    st.markdown("**Gespeicherte Forecasts**")

    try:
        forecasts = get_all_forecast_versions(limit=20)
        if forecasts:
            forecast_options = {}
            for f in forecasts:
                date_str = f['created_at'].strftime('%d.%m.%Y %H:%M')
                source = f.get('source', 'manual').upper()
                status = f['status']
                tours = f.get('instance_count', 0) or f.get('tour_count', 0)
                week = f.get('week_key', '')
                week_str = f" | KW {week}" if week else ""

                # Clean status indicator
                status_mark = "[OK]" if status == 'PASS' else ("[!]" if status == 'WARN' else "[X]")
                label = f"{status_mark} #{f['id']} | {date_str} | {source}{week_str} | {tours} Touren"
                forecast_options[label] = f['id']

            selected_label = st.selectbox(
                "Forecast auswählen",
                options=["-- Neuen Forecast erstellen --"] + list(forecast_options.keys()),
                help="Gespeicherten Forecast laden oder neuen erstellen"
            )

            if selected_label != "-- Neuen Forecast erstellen --":
                selected_id = forecast_options[selected_label]
                forecast_info = get_forecast_version(selected_id)

                col_info, col_action = st.columns([2, 1])

                with col_info:
                    status_class = "sr-badge-pass" if forecast_info['status'] == 'PASS' else ("sr-badge-warn" if forecast_info['status'] == 'WARN' else "sr-badge-fail")
                    st.markdown(f"""
                    <div class="sr-info">
                        <strong>Forecast #{selected_id}</strong> |
                        <span class="sr-badge {status_class}">{forecast_info['status']}</span> |
                        Hash: <code>{forecast_info['input_hash'][:12]}...</code>
                    </div>
                    """, unsafe_allow_html=True)

                with col_action:
                    if st.button("Optimieren", type="primary", key="solve_existing"):
                        with st.spinner("Berechnung läuft..."):
                            try:
                                instances = get_tour_instances(selected_id)
                                if not instances:
                                    st.info("Expandiere Tour-Templates...")
                                    expand_tour_template(selected_id)

                                solve_result = solve_and_audit(selected_id, seed=st.session_state.get("solver_seed", 94))
                                plan_id = solve_result.get("plan_version_id")
                                st.session_state["last_plan_id"] = plan_id
                                st.session_state["last_forecast_id"] = selected_id

                                kpis = solve_result.get("kpis", {})
                                audit = solve_result.get("audit_results", {})

                                st.success(f"Plan #{plan_id} erstellt")

                                kpi_cols = st.columns(4)
                                with kpi_cols[0]:
                                    st.metric("Fahrer", kpis.get("total_drivers", "-"))
                                with kpi_cols[1]:
                                    st.metric("FTE", kpis.get("fte_drivers", "-"))
                                with kpi_cols[2]:
                                    st.metric("Teilzeit", kpis.get("pt_drivers", "-"))
                                with kpi_cols[3]:
                                    st.metric("Audits", f"{audit.get('checks_passed', 0)}/{audit.get('checks_run', 0)}")

                                if audit.get("all_passed"):
                                    st.success("Alle Audit-Checks bestanden")
                                else:
                                    st.warning("Audit-Verstöße gefunden")
                                    for check_name, check_result in audit.get("results", {}).items():
                                        if check_result.get("status") == "FAIL":
                                            violation_count = check_result.get('violation_count', 0)
                                            st.error(f"{check_name}: {violation_count} Verstöße")

                                            details = check_result.get('details', {})
                                            violations = details.get('violations', [])
                                            if violations:
                                                with st.expander(f"Details: {check_name} ({len(violations)} Verstöße)"):
                                                    for i, v in enumerate(violations[:50], 1):
                                                        if isinstance(v, dict):
                                                            driver = v.get('driver_id', '-')
                                                            day = v.get('day', v.get('day_from', '-'))
                                                            span = v.get('span_minutes', '')
                                                            tours = v.get('tour_count', '')
                                                            max_span = v.get('max_span_minutes', '')
                                                            if span and max_span:
                                                                st.text(f"{i}. Fahrer {driver}, Tag {day}: {tours}x Touren, Span {span}min > Max {max_span}min")
                                                            else:
                                                                st.text(f"{i}. Fahrer {driver}, Tag {day}: {v}")
                                                        else:
                                                            st.text(f"{i}. {v}")
                                                    if len(violations) > 50:
                                                        st.text(f"... und {len(violations) - 50} weitere")

                                st.session_state["solve_result"] = solve_result

                                st.divider()
                                st.markdown("**Roster-Matrix**")
                                assignments = get_assignments_with_instances(plan_id)
                                if assignments:
                                    styled_df = build_roster_matrix_with_heatmap(assignments)
                                    if styled_df is not None:
                                        st.dataframe(styled_df, use_container_width=True, height=500)
                                        st.caption("Legende: 1 Tour (grün) | 2 Touren (gelb) | 3+ Touren (rot)")
                                else:
                                    st.warning("Keine Assignments gefunden")

                            except Exception as e:
                                st.error(f"Fehler: {e}")
                                import traceback
                                st.code(traceback.format_exc())
        else:
            st.info("Keine gespeicherten Forecasts vorhanden")

    except Exception as e:
        st.warning(f"Fehler beim Laden: {e}")

    st.divider()

    # -------------------------------------------------------------------------
    # Section: New Forecast Input
    # -------------------------------------------------------------------------
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("**Neuer Forecast**")

        input_method = st.radio(
            "Eingabemethode",
            ["Text einfügen", "CSV hochladen"],
            horizontal=True,
            label_visibility="collapsed"
        )

        if input_method == "Text einfügen":
            raw_text = st.text_area(
                "Forecast-Daten",
                height=250,
                placeholder="""Mo 06:00-14:00 3 Fahrer Depot Nord
Di 07:00-15:00 2 Fahrer
Mi 14:00-22:00
Do 22:00-06:00
Fr 06:00-10:00 + 15:00-19:00""",
                label_visibility="collapsed"
            )
        else:
            uploaded_file = st.file_uploader("CSV-Datei", type=["csv", "txt"], label_visibility="collapsed")
            if uploaded_file:
                file_content = uploaded_file.read().decode("utf-8")

                if detect_csv_format(file_content):
                    st.info("LTS CSV-Format erkannt - automatische Konvertierung")
                    raw_text = convert_lts_csv_to_parser_format(file_content)

                    with st.expander("Konvertiertes Format"):
                        preview_lines = raw_text.split('\n')[:10]
                        st.code('\n'.join(preview_lines) + f"\n... ({len(raw_text.split(chr(10)))} Zeilen)")
                else:
                    raw_text = file_content
            else:
                raw_text = ""

        if st.button("Validieren", type="primary"):
            if raw_text.strip():
                with st.spinner("Validierung..."):
                    try:
                        result = parse_forecast_text(
                            raw_text=raw_text,
                            source="streamlit",
                            save_to_db=False
                        )

                        st.session_state["parse_result"] = result
                        st.session_state["raw_text"] = raw_text
                    except Exception as e:
                        st.error(f"Fehler: {e}")
            else:
                st.warning("Bitte Forecast-Daten eingeben")

    with col2:
        st.markdown("**Validierungsstatus**")

        if "parse_result" in st.session_state:
            result = st.session_state["parse_result"]

            status = result.get("status", "UNKNOWN")
            status_class = "sr-badge-pass" if status == "PASS" else ("sr-badge-warn" if status == "WARN" else "sr-badge-fail")
            st.markdown(f'<span class="sr-badge {status_class}">{status}</span>', unsafe_allow_html=True)

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Touren", result.get("tours_count", 0))
            with col_b:
                st.metric("Zeilen", result.get("lines_with_tours", result.get("lines_total", 0)))
            with col_c:
                hash_val = result.get("input_hash", "")[:8]
                st.metric("Hash", hash_val if hash_val else "-")

            st.markdown("**Details**")
            if "parse_results" in result:
                for idx, pr in enumerate(result["parse_results"], start=1):
                    pr_status = pr.parse_status.value if hasattr(pr, 'parse_status') else str(pr.parse_status)
                    pr_canonical = pr.canonical_text if hasattr(pr, 'canonical_text') else ""
                    pr_issues = pr.issues if hasattr(pr, 'issues') else []

                    status_mark = "[OK]" if pr_status == "PASS" else "[!]" if pr_status == "WARN" else "[X]"
                    display_text = pr_canonical[:40] if pr_canonical else f"Zeile {idx}"

                    with st.expander(f"{status_mark} Zeile {idx}: {display_text}"):
                        st.text(f"Status: {pr_status}")
                        if pr_canonical:
                            st.text(f"Kanonisch: {pr_canonical}")
                        if pr_issues:
                            issues_data = [{"code": i.code, "message": i.message, "severity": i.severity} for i in pr_issues]
                            st.json(issues_data)

            # Save & Solve buttons
            if result.get("status") in ["PASS", "WARN"]:
                col_save, col_solve = st.columns(2)

                with col_save:
                    if st.button("Speichern", type="secondary"):
                        with st.spinner("Speichern..."):
                            saved_result = parse_forecast_text(
                                raw_text=st.session_state["raw_text"],
                                source="streamlit",
                                save_to_db=True
                            )
                            forecast_id = saved_result.get("forecast_version_id")
                            st.session_state["last_forecast_id"] = forecast_id
                            if saved_result.get("duplicate"):
                                st.info(f"Bereits vorhanden (ID: {forecast_id})")
                            else:
                                st.success(f"Gespeichert: ID {forecast_id}")

                with col_solve:
                    if st.button("Speichern & Optimieren", type="primary"):
                        with st.spinner("Berechnung..."):
                            try:
                                saved_result = parse_forecast_text(
                                    raw_text=st.session_state["raw_text"],
                                    source="streamlit",
                                    save_to_db=True
                                )
                                forecast_id = saved_result.get("forecast_version_id")
                                st.session_state["last_forecast_id"] = forecast_id
                                if saved_result.get("duplicate"):
                                    st.info(f"Forecast vorhanden (ID: {forecast_id})")
                                else:
                                    st.info(f"Forecast gespeichert (ID: {forecast_id})")

                                expand_tour_template(forecast_id)

                                solve_result = solve_and_audit(forecast_id, seed=st.session_state.get("solver_seed", 94))
                                plan_id = solve_result.get("plan_version_id")
                                st.session_state["last_plan_id"] = plan_id

                                kpis = solve_result.get("kpis", {})
                                audit = solve_result.get("audit_results", {})

                                st.success(f"Plan #{plan_id} erstellt")

                                kpi_cols = st.columns(4)
                                with kpi_cols[0]:
                                    st.metric("Fahrer", kpis.get("total_drivers", "-"))
                                with kpi_cols[1]:
                                    st.metric("FTE", kpis.get("fte_drivers", "-"))
                                with kpi_cols[2]:
                                    st.metric("Teilzeit", kpis.get("pt_drivers", "-"))
                                with kpi_cols[3]:
                                    st.metric("Audits", f"{audit.get('checks_passed', 0)}/{audit.get('checks_run', 0)}")

                                if audit.get("all_passed"):
                                    st.success("Alle Audit-Checks bestanden")
                                else:
                                    st.warning("Audit-Verstöße gefunden")
                                    for check_name, check_result in audit.get("results", {}).items():
                                        if check_result.get("status") == "FAIL":
                                            violation_count = check_result.get('violation_count', 0)
                                            st.error(f"{check_name}: {violation_count} Verstöße")

                                            details = check_result.get('details', {})
                                            violations = details.get('violations', [])
                                            if violations:
                                                with st.expander(f"Details: {check_name} ({len(violations)} Verstöße)"):
                                                    for i, v in enumerate(violations[:50], 1):
                                                        if isinstance(v, dict):
                                                            driver = v.get('driver_id', '-')
                                                            day = v.get('day', v.get('day_from', '-'))
                                                            span = v.get('span_minutes', '')
                                                            tours = v.get('tour_count', '')
                                                            max_span = v.get('max_span_minutes', '')
                                                            if span and max_span:
                                                                st.text(f"{i}. Fahrer {driver}, Tag {day}: {tours}x Touren, Span {span}min > Max {max_span}min")
                                                            else:
                                                                st.text(f"{i}. Fahrer {driver}, Tag {day}: {v}")
                                                        else:
                                                            st.text(f"{i}. {v}")
                                                    if len(violations) > 50:
                                                        st.text(f"... und {len(violations) - 50} weitere")

                                st.session_state["solve_result"] = solve_result

                                st.divider()
                                st.markdown("**Roster-Matrix**")
                                assignments = get_assignments_with_instances(plan_id)
                                if assignments:
                                    styled_df = build_roster_matrix_with_heatmap(assignments)
                                    if styled_df is not None:
                                        st.dataframe(styled_df, use_container_width=True, height=500)
                                        st.caption("Legende: 1 Tour (grün) | 2 Touren (gelb) | 3+ Touren (rot)")
                                else:
                                    st.warning("Keine Assignments gefunden")

                            except Exception as e:
                                st.error(f"Fehler: {e}")
                                import traceback
                                st.code(traceback.format_exc())

    # Seed Sweep Section
    st.divider()
    st.markdown('<div class="sr-section">Seed-Optimierung</div>', unsafe_allow_html=True)
    st.caption("Mehrere Seeds testen für optimale Konfiguration")

    # Get forecasts for seed sweep
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT fv.id, fv.created_at, fv.source, fv.week_key,
                           (SELECT COUNT(*) FROM tour_instances ti WHERE ti.forecast_version_id = fv.id) as tour_count
                    FROM forecast_versions fv
                    WHERE fv.status = 'PASS'
                    ORDER BY fv.created_at DESC
                    LIMIT 10
                """)
                sweep_forecasts = cur.fetchall()
    except Exception as e:
        st.error(f"Database error: {e}")
        sweep_forecasts = []

    if sweep_forecasts:
        sweep_options = {
            f"Forecast #{f['id']} | {f['created_at'].strftime('%d.%m.%Y %H:%M')} | {f.get('week_key', '')} | {f.get('tour_count', 0)} Touren": f
            for f in sweep_forecasts
        }

        col_sw1, col_sw2 = st.columns([2, 1])

        with col_sw1:
            selected_sweep = st.selectbox(
                "Forecast für Seed Sweep",
                options=list(sweep_options.keys()),
                key="seed_sweep_forecast"
            )

        with col_sw2:
            num_seeds = st.slider("Anzahl Seeds", min_value=3, max_value=20, value=10, key="num_seeds")

        if st.button("Seed-Sweep starten", type="secondary"):
            forecast = sweep_options[selected_sweep]
            forecast_id = forecast["id"]

            with st.spinner(f"Lade Tour-Instanzen für Forecast #{forecast_id}..."):
                try:
                    instances = get_tour_instances(forecast_id)

                    if not instances:
                        st.warning("Keine Tour-Instanzen gefunden. Bitte erst Forecast parsen und Instanzen expandieren.")
                    else:
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        st.info(f"Starte Seed Sweep mit {num_seeds} Seeds für {len(instance_list)} Touren...")

                        # Generate seeds
                        base_seeds = [94, 42, 17, 23, 31, 47, 53, 67, 71, 89, 97, 101, 127, 131, 137, 149, 157, 163, 173, 179]
                        seeds = base_seeds[:num_seeds]

                        # Progress bar
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        results_container = st.empty()

                        results = []

                        for i, seed in enumerate(seeds):
                            status_text.text(f"Testing seed {seed} ({i+1}/{num_seeds})...")
                            progress_bar.progress((i + 1) / num_seeds)

                            try:
                                from v3.solver_v2_integration import solve_with_v2_solver
                                assignments = solve_with_v2_solver(instance_list, seed=seed)
                                metrics = compute_assignment_metrics(assignments, instance_list)
                                metrics["seed"] = seed
                                metrics["success"] = True
                                results.append(metrics)
                            except Exception as e:
                                results.append({
                                    "seed": seed,
                                    "success": False,
                                    "error": str(e),
                                    "total_drivers": 9999,
                                    "pt_ratio": 100.0,
                                })

                        # Sort by quality
                        results.sort(key=lambda r: (
                            r.get("total_drivers", 9999),
                            r.get("pt_ratio", 100),
                            -r.get("block_3er", 0),
                            r.get("block_1er", 9999),
                        ))

                        # Add rank
                        for i, r in enumerate(results):
                            r["rank"] = i + 1

                        status_text.text("Seed-Sweep abgeschlossen")

                        # Display results
                        st.markdown("**Ergebnisse**")

                        # Create DataFrame for display
                        import pandas as pd
                        df_results = pd.DataFrame([
                            {
                                "Rang": r["rank"],
                                "Seed": r["seed"],
                                "Fahrer": r.get("total_drivers", "-"),
                                "FTE": r.get("fte_drivers", "-"),
                                "PT%": f"{r.get('pt_ratio', 0):.1f}%",
                                "3er": r.get("block_3er", 0),
                                "2er": r.get("block_2er_reg", 0) + r.get("block_2er_split", 0),
                                "1er": r.get("block_1er", 0),
                                "Status": "OK" if r.get("success") else "FEHLER"
                            }
                            for r in results
                        ])

                        st.dataframe(df_results, use_container_width=True, hide_index=True)

                        # Highlight best
                        best = results[0]
                        if best.get("success"):
                            st.success(f"Bester Seed: {best['seed']} | {best['total_drivers']} Fahrer ({best.get('fte_drivers', 0)} FTE, {best.get('pt_ratio', 0):.1f}% PT)")

                            # Option to use best seed
                            if st.button(f"Plan mit Seed {best['seed']} erstellen"):
                                with st.spinner(f"Erstelle Plan mit Seed {best['seed']}..."):
                                    try:
                                        solve_result = solve_and_audit(forecast_id, seed=best['seed'])
                                        st.success(f"Plan #{solve_result['plan_version_id']} erstellt")
                                    except Exception as e:
                                        st.error(f"Fehler: {e}")
                        else:
                            st.error("Alle Seeds fehlgeschlagen!")

                except Exception as e:
                    st.error(f"Seed Sweep Fehler: {e}")
                    import traceback
                    st.code(traceback.format_exc())
    else:
        st.info("Keine Forecasts mit Status PASS gefunden. Bitte erst einen Forecast parsen!")


# ============================================================================
# TAB 2: Vergleich
# ============================================================================
with tab2:
    st.markdown('<div class="sr-section">Forecast-Vergleich</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Versionen auswählen**")

        # Get available forecast versions
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, created_at, source, status, input_hash
                        FROM forecast_versions
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                    forecasts = cur.fetchall()
        except Exception as e:
            st.error(f"Database error: {e}")
            forecasts = []

        if forecasts:
            forecast_options = {
                f"v{f['id']} ({f['created_at'].strftime('%Y-%m-%d %H:%M')}) - {f['status']}": f["id"]
                for f in forecasts
            }

            old_version = st.selectbox(
                "Basis-Version",
                options=list(forecast_options.keys()),
                index=1 if len(forecast_options) > 1 else 0
            )
            new_version = st.selectbox(
                "Vergleichs-Version",
                options=list(forecast_options.keys()),
                index=0
            )

            if st.button("Vergleichen", type="primary"):
                old_id = forecast_options[old_version]
                new_id = forecast_options[new_version]

                if old_id == new_id:
                    st.warning("Bitte verschiedene Versionen auswählen")
                else:
                    with st.spinner("Berechne Diff..."):
                        try:
                            diff = compute_diff(old_id, new_id)
                            st.session_state["diff_result"] = diff
                        except Exception as e:
                            st.error(f"Fehler: {e}")
        else:
            st.info("Keine Forecast-Versionen gefunden")

    with col2:
        st.markdown("**Diff-Ergebnis**")

        if "diff_result" in st.session_state:
            diff = st.session_state["diff_result"]

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Hinzugefügt", diff.added, delta_color="normal")
            with col_b:
                st.metric("Entfernt", diff.removed, delta_color="inverse")
            with col_c:
                st.metric("Geändert", diff.changed)

            if diff.details:
                st.markdown("**Änderungsdetails**")

                filter_type = st.multiselect(
                    "Filter",
                    ["ADDED", "REMOVED", "CHANGED"],
                    default=["ADDED", "REMOVED", "CHANGED"],
                    label_visibility="collapsed"
                )

                for detail in diff.details:
                    if detail.diff_type.value in filter_type:
                        if detail.diff_type.value == "ADDED":
                            st.markdown(f"[+] **NEU**: {detail.fingerprint[:20]}...")
                        elif detail.diff_type.value == "REMOVED":
                            st.markdown(f"[-] **ENTFERNT**: {detail.fingerprint[:20]}...")
                        else:
                            st.markdown(f"[~] **GEÄNDERT**: {detail.fingerprint[:20]}...")
                            if detail.changed_fields:
                                st.text(f"   Felder: {', '.join(detail.changed_fields)}")

    # Plan Churn Section
    st.divider()
    st.markdown('<div class="sr-section">Plan-Churn Analyse</div>', unsafe_allow_html=True)
    st.caption("Planstabilität zwischen zwei Versionen vergleichen")

    col_p1, col_p2 = st.columns(2)

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT pv.id, pv.status, pv.created_at, pv.seed,
                           fv.week_key,
                           (SELECT COUNT(DISTINCT a.driver_id) FROM assignments a WHERE a.plan_version_id = pv.id) as driver_count
                    FROM plan_versions pv
                    JOIN forecast_versions fv ON pv.forecast_version_id = fv.id
                    ORDER BY pv.created_at DESC
                    LIMIT 20
                """)
                churn_plans = cur.fetchall()
    except Exception as e:
        st.error(f"Datenbankfehler: {e}")
        churn_plans = []

    if churn_plans and len(churn_plans) >= 2:
        churn_plan_options = {
            f"Plan #{p['id']} | {p['created_at'].strftime('%d.%m.%Y %H:%M')} | {p.get('week_key', '')} | {p.get('driver_count', 0)} Fahrer | Seed {p['seed']}": p["id"]
            for p in churn_plans
        }

        with col_p1:
            old_plan_label = st.selectbox(
                "Basis-Plan",
                options=list(churn_plan_options.keys()),
                index=1 if len(churn_plan_options) > 1 else 0,
                key="churn_old_plan"
            )

        with col_p2:
            new_plan_label = st.selectbox(
                "Vergleichs-Plan",
                options=list(churn_plan_options.keys()),
                index=0,
                key="churn_new_plan"
            )

        if st.button("Churn berechnen", type="secondary"):
            old_plan_id = churn_plan_options[old_plan_label]
            new_plan_id = churn_plan_options[new_plan_label]

            if old_plan_id == new_plan_id:
                st.warning("Bitte verschiedene Pläne auswählen")
            else:
                with st.spinner("Berechne Plan-Churn..."):
                    try:
                        old_assignments = get_assignments_with_instances(old_plan_id)
                        new_assignments = get_assignments_with_instances(new_plan_id)

                        churn = compute_plan_churn(old_assignments, new_assignments)
                        st.session_state["churn_result"] = churn

                    except Exception as e:
                        st.error(f"Churn-Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        # Display churn results
        if "churn_result" in st.session_state:
            churn = st.session_state["churn_result"]

            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Stabilität", f"{churn['stability_percent']:.1f}%")
            with m2:
                st.metric("Churn Rate", f"{churn['churn_rate']:.1f}%")
            with m3:
                st.metric("Betroffene Fahrer", churn['affected_drivers_count'])
            with m4:
                st.metric("Betroffene Touren", churn['affected_tours_count'])

            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric("Unverändert", churn['unchanged'])
            with c2:
                st.metric("Geändert", churn['changed'])
            with c3:
                st.metric("Neu", churn['added'])
            with c4:
                st.metric("Entfernt", churn['removed'])

            stability = churn['stability_percent']
            if stability >= 90:
                st.success(f"Hohe Stabilität ({stability:.1f}%) - Minimale Änderungen")
            elif stability >= 70:
                st.warning(f"Mittlere Stabilität ({stability:.1f}%) - Einige Fahrer betroffen")
            else:
                st.error(f"Niedrige Stabilität ({stability:.1f}%) - Viele Änderungen")

            if churn['changed_details']:
                with st.expander(f"Fahrer-Änderungen ({len(churn['changed_details'])} Umzuweisungen)"):
                    for detail in churn['changed_details'][:50]:
                        st.text(f"Tour {detail['tour_instance_id']} (Tag {detail.get('day', '?')}): {detail['old_driver']} → {detail['new_driver']}")
                    if len(churn['changed_details']) > 50:
                        st.text(f"... und {len(churn['changed_details']) - 50} weitere")

    elif churn_plans:
        st.info("Mindestens 2 Pläne erforderlich für Churn-Analyse")
    else:
        st.info("Keine Pläne gefunden. Erst einen Plan erstellen!")


# ============================================================================
# TAB 3: Planung
# ============================================================================
with tab3:
    st.markdown('<div class="sr-section">Planungsübersicht</div>', unsafe_allow_html=True)

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("**Plan auswählen**")

        # Get available plan versions with more details
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pv.id, pv.status, pv.created_at, pv.seed,
                               pv.output_hash,
                               fv.id as forecast_id,
                               fv.source as forecast_source,
                               fv.week_key,
                               (SELECT COUNT(*) FROM tour_instances ti WHERE ti.forecast_version_id = fv.id) as tour_count,
                               (SELECT COUNT(*) FROM assignments a WHERE a.plan_version_id = pv.id) as assignment_count,
                               (SELECT COUNT(DISTINCT a.driver_id) FROM assignments a WHERE a.plan_version_id = pv.id) as driver_count
                        FROM plan_versions pv
                        JOIN forecast_versions fv ON pv.forecast_version_id = fv.id
                        ORDER BY pv.created_at DESC
                        LIMIT 20
                    """)
                    plans = cur.fetchall()
        except Exception as e:
            st.error(f"Database error: {e}")
            plans = []

        if plans:
            plan_options = {}
            for p in plans:
                date_str = p['created_at'].strftime('%d.%m.%Y %H:%M')
                status = p['status']
                status_mark = "[LOCKED]" if status == "LOCKED" else "[DRAFT]"
                source = (p.get('forecast_source') or 'manual').upper()
                week = p.get('week_key', '')
                week_str = f"KW {week} | " if week else ""
                drivers = p.get('driver_count', 0)
                tours = p.get('tour_count', 0)

                label = f"{status_mark} Plan #{p['id']} | {date_str} | {week_str}{source} | {drivers} Fahrer / {tours} Touren | Seed {p['seed']}"
                plan_options[label] = p["id"]

            selected_plan = st.selectbox(
                "Plan",
                options=list(plan_options.keys()),
                help="Plan zur Vorschau auswählen",
                label_visibility="collapsed"
            )

            plan_id = plan_options[selected_plan]

            if st.button("Plan laden", type="primary"):
                with st.spinner("Laden..."):
                    try:
                        assignments = get_assignments_with_instances(plan_id)
                        plan = db.get_plan_version(plan_id)
                        audits = db.get_audit_logs(plan_id)

                        st.session_state["plan_data"] = {
                            "plan": plan,
                            "assignments": assignments,
                            "audits": audits
                        }
                    except Exception as e:
                        st.error(f"Fehler: {e}")
        else:
            st.info("Keine Pläne vorhanden")

            if "last_forecast_id" in st.session_state:
                if st.button("Letzten Forecast optimieren"):
                    with st.spinner("Berechnung..."):
                        try:
                            expand_tour_template(st.session_state["last_forecast_id"])
                            result = solve_and_audit(
                                st.session_state["last_forecast_id"],
                                seed=st.session_state.get("solver_seed", 94)
                            )
                            st.success(f"Plan #{result['plan_version_id']} erstellt")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fehler: {e}")

    with col2:
        st.markdown("**Plan-Details**")

        if "plan_data" in st.session_state:
            data = st.session_state["plan_data"]
            plan = data["plan"]
            assignments = data["assignments"]
            audits = data["audits"]

            status = plan.get("status", "UNKNOWN")
            status_class = "sr-badge-locked" if status == "LOCKED" else "sr-badge-draft"
            st.markdown(f'<span class="sr-badge {status_class}">{status}</span>', unsafe_allow_html=True)

            st.metric("Assignments", len(assignments))
            st.metric("Seed", plan.get("seed"))

            st.markdown("**Audit-Status**")
            for audit in audits:
                status_mark = "[OK]" if audit["status"] == "PASS" else "[X]"
                st.text(f"{status_mark} {audit['check_name']}")

    # Near-Violation Warnings Section
    if "plan_data" in st.session_state:
        st.divider()
        st.markdown('<div class="sr-section">Grenzwert-Warnungen</div>', unsafe_allow_html=True)
        st.caption("Situationen nahe am Limit (Gelbe Zone)")

        try:
            assignments = st.session_state["plan_data"]["assignments"]
            plan = st.session_state["plan_data"]["plan"]
            forecast_id = plan.get("forecast_version_id")

            if forecast_id:
                instances = get_tour_instances(forecast_id)
                instance_list = [
                    {
                        "id": inst["id"],
                        "day": inst["day"],
                        "start_ts": inst.get("start_ts"),
                        "end_ts": inst.get("end_ts"),
                        "work_hours": float(inst.get("work_hours", 0)),
                    }
                    for inst in instances
                ]

                warnings = compute_near_violations(assignments, instance_list)
                summary = summarize_warnings(warnings)

                if warnings:
                    w1, w2, w3, w4 = st.columns(4)
                    with w1:
                        st.metric("Warnungen", summary["total"])
                    with w2:
                        st.metric("Ruhezeit", summary["types"].get("REST", 0))
                    with w3:
                        st.metric("Span", summary["types"].get("SPAN", 0))
                    with w4:
                        st.metric("Betroffene Fahrer", summary["affected_drivers"])

                    with st.expander(f"Details ({len(warnings)} Warnungen)", expanded=False):
                        for w in warnings[:100]:
                            st.warning(f"[{w['type']}] {w['message']}")
                        if len(warnings) > 100:
                            st.text(f"... und {len(warnings) - 100} weitere")
                else:
                    st.success("Keine Warnungen - Alle Limits haben ausreichend Puffer")
        except Exception as e:
            st.error(f"Warning check error: {e}")

    # Roster Matrix
    if "plan_data" in st.session_state:
        st.markdown('<div class="sr-section">Roster-Matrix</div>', unsafe_allow_html=True)

        assignments = st.session_state["plan_data"]["assignments"]
        if assignments:
            df = build_roster_matrix_with_heatmap(assignments)
            if df is not None:
                st.dataframe(df, use_container_width=True, height=600)
                st.caption("Legende: 1 Tour (grün) | 2 Touren (gelb) | 3+ Touren (rot)")

    # Peak Fleet Analysis
    if "plan_data" in st.session_state:
        st.divider()
        st.markdown('<div class="sr-section">Peak-Fleet Analyse</div>', unsafe_allow_html=True)
        st.caption("Gleichzeitig aktive Touren pro Zeitslot")

        try:
            plan = st.session_state["plan_data"]["plan"]
            forecast_id = plan.get("forecast_version_id")

            if forecast_id:
                instances = get_tour_instances(forecast_id)
                instance_list = [
                    {
                        "id": inst["id"],
                        "day": inst["day"],
                        "start_ts": inst.get("start_ts"),
                        "end_ts": inst.get("end_ts"),
                        "crosses_midnight": inst.get("crosses_midnight", False),
                    }
                    for inst in instances
                ]

                peak = compute_peak_fleet(instance_list)

                p1, p2, p3, p4 = st.columns(4)
                day_names = {1: "Mo", 2: "Di", 3: "Mi", 4: "Do", 5: "Fr", 6: "Sa", 7: "So"}
                with p1:
                    st.metric("Peak Fleet", peak["global_peak"])
                with p2:
                    st.metric("Peak Tag", day_names.get(peak["peak_day"], "-"))
                with p3:
                    st.metric("Peak Zeit", peak["peak_time"])
                with p4:
                    st.metric("Total Touren", peak["total_tours"])

                st.markdown("**Tägliche Peaks**")
                daily_data = []
                for day in range(1, 8):
                    daily_data.append({
                        "Tag": day_names.get(day, "-"),
                        "Peak": peak["daily_peaks"].get(day, 0)
                    })

                import pandas as pd
                df_daily = pd.DataFrame(daily_data)
                st.bar_chart(df_daily.set_index("Tag"))

                if peak["peak_hours"]:
                    with st.expander(f"Top Peak-Stunden ({len(peak['peak_hours'])})", expanded=False):
                        for ph in peak["peak_hours"]:
                            day_name = day_names.get(ph["day"], "-")
                            st.text(f"{day_name} {ph['time_range']}: {ph['count']} gleichzeitige Touren")

        except Exception as e:
            st.error(f"Peak Fleet Fehler: {e}")


# ============================================================================
# TAB 4: Release
# ============================================================================
with tab4:
    st.markdown('<div class="sr-section">Freigabe-Kontrolle</div>', unsafe_allow_html=True)

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Release-Checkliste**")

        # Get DRAFT plans
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pv.id, pv.status, pv.created_at, pv.seed,
                               pv.forecast_version_id
                        FROM plan_versions pv
                        WHERE pv.status = 'DRAFT'
                        ORDER BY pv.created_at DESC
                        LIMIT 10
                    """)
                    draft_plans = cur.fetchall()
        except Exception as e:
            st.error(f"Database error: {e}")
            draft_plans = []

        if draft_plans:
            plan_options = {
                f"Plan {p['id']} (Created: {p['created_at'].strftime('%Y-%m-%d %H:%M')})": p
                for p in draft_plans
            }

            selected = st.selectbox(
                "Select Plan to Release",
                options=list(plan_options.keys())
            )

            plan = plan_options[selected]
            plan_id = plan["id"]

            can_release, blocking = db.can_release(plan_id)

            st.markdown("**Gate-Status**")

            if can_release:
                st.success("Alle Pflicht-Checks bestanden")
            else:
                st.error("Freigabe blockiert:")
                for check in blocking:
                    st.text(f"  - {check}")

            st.markdown("**Freeze-Status**")
            try:
                frozen_ids, modifiable_ids = classify_instances(plan["forecast_version_id"])
                st.text(f"Gesperrt: {len(frozen_ids)}")
                st.text(f"Änderbar: {len(modifiable_ids)}")
            except Exception as e:
                st.text(f"Freeze-Check: N/A ({e})")

        else:
            st.info("Keine DRAFT-Pläne zur Freigabe verfügbar")

    with col2:
        st.markdown("**Freigabe-Aktionen**")

        if draft_plans and can_release:
            st.warning("Warnung: Freigabe ist nicht umkehrbar")

            locked_by = st.text_input("Name/E-Mail", value="dispatcher@lts.de")

            if st.button("FREIGEBEN", type="primary"):
                if locked_by:
                    with st.spinner("Sperre Plan..."):
                        try:
                            db.lock_plan_version(plan_id, locked_by)
                            st.success(f"Plan {plan_id} freigegeben")

                            st.info("Generiere Export...")
                            files = export_release_package(plan_id, "exports")
                            st.success("Export abgeschlossen")
                            for name, path in files.items():
                                st.text(f"  - {name}: {os.path.basename(path)}")
                        except Exception as e:
                            st.error(f"Fehler: {e}")
                else:
                    st.warning("Bitte Name/E-Mail eingeben")

        elif draft_plans:
            st.info("Bitte erst blockierende Checks beheben")

        st.markdown("**Freigegebene Pläne**")

        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, locked_at, locked_by
                        FROM plan_versions
                        WHERE status = 'LOCKED'
                        ORDER BY locked_at DESC
                        LIMIT 5
                    """)
                    locked_plans = cur.fetchall()

            if locked_plans:
                for lp in locked_plans:
                    st.text(f"Plan {lp['id']} | {lp['locked_by']} | {lp['locked_at']}")
            else:
                st.text("Noch keine freigegebenen Pläne")
        except Exception as e:
            st.text(f"Fehler: {e}")

        # Proof Pack Export Section
        st.markdown('<div class="sr-section">Proof Pack Export</div>', unsafe_allow_html=True)
        st.caption("Kryptografisch signiertes Proof-Paket mit Verify-Script")

        # Get all plans for proof pack export
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pv.id, pv.status, pv.created_at, pv.seed,
                               pv.forecast_version_id, pv.output_hash,
                               fv.input_hash
                        FROM plan_versions pv
                        JOIN forecast_versions fv ON pv.forecast_version_id = fv.id
                        ORDER BY pv.created_at DESC
                        LIMIT 20
                    """)
                    all_plans = cur.fetchall()

            if all_plans:
                proof_pack_options = {
                    f"Plan {p['id']} ({p['status']}) - Seed {p['seed']}": p
                    for p in all_plans
                }

                selected_proof = st.selectbox(
                    "Select Plan for Proof Pack",
                    options=list(proof_pack_options.keys()),
                    key="proof_pack_select"
                )

                selected_plan = proof_pack_options[selected_proof]

                if st.button("Proof Pack generieren", type="secondary"):
                    with st.spinner("Generiere Proof Pack..."):
                        try:
                            plan_id = selected_plan["id"]
                            forecast_id = selected_plan["forecast_version_id"]

                            # Get assignments and instances
                            assignments = get_assignments_with_instances(plan_id)
                            instances = get_tour_instances(forecast_id)

                            # Convert instances to list format
                            instance_list = [
                                {
                                    "id": inst["id"],
                                    "day": inst["day"],
                                    "start_ts": inst.get("start_ts"),
                                    "end_ts": inst.get("end_ts"),
                                    "work_hours": float(inst.get("work_hours", 0)),
                                    "depot": inst.get("depot", ""),
                                    "skill": inst.get("skill", ""),
                                }
                                for inst in instances
                            ]

                            # Run audit
                            audit_results = audit_plan_fixed(plan_id, save_to_db=False)

                            # Compute KPIs
                            from v3.solver_wrapper import compute_plan_kpis
                            kpis = compute_plan_kpis(plan_id)

                            # Build metadata
                            import hashlib
                            solver_config = {
                                "seed": selected_plan["seed"],
                                "version": "v3_with_v2_solver",
                                "fatigue_rule": "no_consecutive_triples",
                                "rest_min": 660,
                                "span_regular_max": 840,
                                "span_split_max": 960,
                            }
                            solver_config_hash = hashlib.sha256(
                                json.dumps(solver_config, sort_keys=True).encode()
                            ).hexdigest()

                            metadata = {
                                "plan_version_id": plan_id,
                                "forecast_version_id": forecast_id,
                                "seed": selected_plan["seed"],
                                "input_hash": selected_plan.get("input_hash", ""),
                                "output_hash": selected_plan.get("output_hash", ""),
                                "solver_config_hash": solver_config_hash,
                            }

                            # Generate ZIP
                            zip_buffer = generate_proof_pack_zip(
                                assignments=assignments,
                                instances=instance_list,
                                audit_results=audit_results,
                                kpis=kpis,
                                metadata=metadata,
                                output_path=None  # Return BytesIO
                            )

                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            st.download_button(
                                label="Download proof_pack.zip",
                                data=zip_buffer,
                                file_name=f"proof_pack_plan{plan_id}_{timestamp}.zip",
                                mime="application/zip"
                            )
                            st.success("Proof Pack generiert: matrix.csv, rosters.csv, kpis.json, audit_summary.json, metadata.json, manifest.json, verify.py")

                        except Exception as e:
                            st.error(f"Error generating proof pack: {e}")
                            import traceback
                            st.code(traceback.format_exc())
            else:
                st.info("No plans available for export")
        except Exception as e:
            st.error(f"Error loading plans: {e}")


# ============================================================================
# TAB 5: Simulation
# ============================================================================
with tab5:
    st.markdown('<div class="sr-section">What-If Simulation</div>', unsafe_allow_html=True)
    st.caption("Szenarien testen und Auswirkungen analysieren")

    # Scenario Category Selection
    col_cat, col_scenario = st.columns([1, 2])

    with col_cat:
        st.markdown("**Kategorie**")
        scenario_category = st.radio(
            "Kategorie wählen",
            ["Economic", "Compliance", "Operational", "Strategic", "Advanced", "Multi-Output"],
            label_visibility="collapsed",
            help="Economic: Kosten | Compliance: Regeln | Operational: Betrieb | Strategic: Budget | Advanced: V3.2 | Multi-Output: Vergleich"
        )

    with col_scenario:
        st.markdown("**Szenario**")

        if scenario_category == "Economic":
            scenario_options = {
                "Cost Curve": "Kosten jeder Qualitätsregel in Fahrern analysieren",
                "Freeze Trade-off": "12h vs 18h vs 24h Freeze-Window Analyse",
            }
        elif scenario_category == "Compliance":
            scenario_options = {
                "Max-Hours Policy": "Auswirkung von 55h → 52h/50h/48h Cap",
                "Driver-Friendly": "Kosten von 30-60min Gaps in 3er-Chains",
            }
        elif scenario_category == "Operational":
            scenario_options = {
                "Patch-Chaos": "PARTIAL → COMPLETE Forecast Integration",
                "Sick-Call Drill": "Fahrer-Ausfall Simulation",
                "Tour-Stornierung": "Auswirkung von Tour-Absagen auf Plan",
            }
        elif scenario_category == "Strategic":
            scenario_options = {
                "Headcount-Budget": "Ziel-Fahrerzahl erreichen mit Regellockerungen",
            }
        elif scenario_category == "Advanced":
            scenario_options = {
                "Multi-Failure Cascade": "Kombinierte Ausfälle: Fahrer krank + Touren storniert + Cascade-Effekte",
                "Probabilistic Churn": "Monte-Carlo Simulation: Churn-Wahrscheinlichkeit unter Stress",
                "Policy ROI Optimizer": "Optimale Regel-Kombination für Kosten-Nutzen-Verhältnis",
            }
        else:  # Multi-Output
            scenario_options = {
                "Auto-Seed-Sweep": "Optimalen Seed automatisch finden (parallel)",
                "Multi-Szenario-Vergleich": "3 Szenarien side-by-side vergleichen",
            }

        selected_scenario = st.selectbox(
            "Szenario wählen",
            options=list(scenario_options.keys()),
            format_func=lambda x: f"{x} - {scenario_options[x]}",
            label_visibility="collapsed"
        )

    st.divider()

    # Get forecast for simulation
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT fv.id, fv.created_at, fv.source, fv.week_key, fv.status,
                           (SELECT COUNT(*) FROM tour_instances ti WHERE ti.forecast_version_id = fv.id) as tour_count
                    FROM forecast_versions fv
                    WHERE fv.status = 'PASS'
                    ORDER BY fv.created_at DESC
                    LIMIT 10
                """)
                sim_forecasts = cur.fetchall()
    except Exception as e:
        st.error(f"Database error: {e}")
        sim_forecasts = []

    if sim_forecasts:
        sim_forecast_options = {
            f"Forecast #{f['id']} | {f['created_at'].strftime('%d.%m.%Y %H:%M')} | {f.get('week_key', '')} | {f.get('tour_count', 0)} Touren": f
            for f in sim_forecasts
        }

        selected_sim_forecast = st.selectbox(
            "Forecast für Simulation",
            options=list(sim_forecast_options.keys()),
            key="sim_forecast_select"
        )

        forecast_data = sim_forecast_options[selected_sim_forecast]
        forecast_id = forecast_data["id"]

        # Scenario-specific configuration
        st.markdown("**Parameter**")

        if selected_scenario == "Cost Curve":
            st.markdown("""
            <div class="sr-info">
                <strong>Cost Curve Analyse</strong><br>
                Berechnet die "Kosten" jeder Qualitätsregel in zusätzlichen Fahrern.
                Zeigt, welche Regeln am meisten Fahrer kosten.
            </div>
            """, unsafe_allow_html=True)

            baseline_seed = st.number_input("Baseline Seed", value=94, min_value=1, max_value=9999, key="cc_seed")

            if st.button("Cost Curve berechnen", type="primary", key="run_cost_curve"):
                with st.spinner("Berechne Cost Curve... (kann einige Sekunden dauern)"):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        result = run_cost_curve(instance_list, baseline_seed=baseline_seed)

                        st.success(f"Cost Curve berechnet | Baseline: {result.baseline_drivers} Fahrer")

                        # Show results table
                        st.markdown("**Regel-Kosten (in Fahrern)**")

                        cost_data = []
                        for entry in result.entries:
                            cost_data.append({
                                "Regel": entry.rule_name,
                                "Baseline": result.baseline_drivers,
                                "Relaxed": entry.relaxed_drivers,
                                "Δ Fahrer": entry.driver_delta,
                                "Ersparnis/Jahr": f"~€{abs(entry.driver_delta) * 50000:,.0f}" if entry.driver_delta < 0 else "-",
                            })

                        df_cost = pd.DataFrame(cost_data)
                        st.dataframe(df_cost, use_container_width=True, hide_index=True)

                        # Bar chart
                        st.markdown("**Visualisierung**")
                        chart_data = pd.DataFrame({
                            "Regel": [e.rule_name for e in result.entries],
                            "Δ Fahrer": [e.driver_delta for e in result.entries]
                        })
                        st.bar_chart(chart_data.set_index("Regel"))

                        # Risk assessment
                        st.markdown("**Risiko-Bewertung**")
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'Risk Score: <span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                        for rec in result.recommendations:
                            st.info(rec)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Max-Hours Policy":
            st.markdown("""
            <div class="sr-info">
                <strong>Max-Hours Policy Analyse</strong><br>
                Vergleicht Auswirkungen verschiedener Wochenarbeitszeit-Caps.
                55h (aktuell) vs 52h vs 50h vs 48h.
            </div>
            """, unsafe_allow_html=True)

            baseline_seed = st.number_input("Baseline Seed", value=94, min_value=1, max_value=9999, key="mh_seed")
            caps_to_test = st.multiselect(
                "Caps testen",
                options=[55, 52, 50, 48, 45],
                default=[55, 52, 50, 48],
                key="mh_caps"
            )

            if st.button("Max-Hours Policy berechnen", type="primary", key="run_max_hours"):
                with st.spinner("Berechne Max-Hours Policy..."):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        result = run_max_hours_policy(
                            instance_list,
                            baseline_seed=baseline_seed,
                            caps_to_test=sorted(caps_to_test, reverse=True)
                        )

                        st.success("Max-Hours Policy berechnet")

                        # Results table
                        st.markdown("**Vergleichstabelle**")

                        policy_data = []
                        for entry in result.entries:
                            policy_data.append({
                                "Cap": f"{entry.policy_value}h",
                                "Fahrer": entry.drivers,
                                "FTE": entry.fte_count,
                                "PT%": f"{entry.pt_ratio:.1f}%",
                                "Coverage": f"{entry.coverage:.1f}%",
                                "Δ Fahrer": f"+{entry.driver_delta}" if entry.driver_delta > 0 else str(entry.driver_delta),
                            })

                        df_policy = pd.DataFrame(policy_data)
                        st.dataframe(df_policy, use_container_width=True, hide_index=True)

                        # Chart
                        st.markdown("**Fahrer pro Cap**")
                        chart_df = pd.DataFrame({
                            "Cap (h)": [str(e.policy_value) for e in result.entries],
                            "Fahrer": [e.drivers for e in result.entries]
                        })
                        st.bar_chart(chart_df.set_index("Cap (h)"))

                        # Insight
                        st.markdown("**CFO-Formel**")
                        st.code("(55h - X) / 3 × 5 ≈ zusätzliche Fahrer\nBeispiel: 55h → 48h = 7h / 3 × 5 ≈ 12 Fahrer")

                        # Risk
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'Risk Score: <span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Freeze Trade-off":
            st.markdown("""
            <div class="sr-info">
                <strong>Freeze Window Trade-off</strong><br>
                Analysiert die Balance zwischen Stabilität (längere Freeze) und
                Flexibilität (kürzere Freeze). 12h vs 18h vs 24h vs 48h.
            </div>
            """, unsafe_allow_html=True)

            baseline_seed = st.number_input("Baseline Seed", value=94, min_value=1, max_value=9999, key="ft_seed")
            windows_to_test = st.multiselect(
                "Freeze Windows testen (Stunden)",
                options=[6, 12, 18, 24, 36, 48],
                default=[12, 18, 24, 48],
                key="ft_windows"
            )

            if st.button("Freeze Trade-off berechnen", type="primary", key="run_freeze"):
                with st.spinner("Berechne Freeze Trade-off..."):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        # Convert hours to minutes for the function
                        windows_minutes = [w * 60 for w in sorted(windows_to_test)]

                        result = run_freeze_tradeoff(
                            instance_list,
                            baseline_seed=baseline_seed,
                            windows_to_test=windows_minutes
                        )

                        st.success("Freeze Trade-off berechnet")

                        # Results table
                        st.markdown("**Trade-off Tabelle**")

                        freeze_data = []
                        for entry in result.entries:
                            hours = entry.policy_value // 60
                            freeze_data.append({
                                "Freeze Window": f"{hours}h",
                                "Fahrer": entry.drivers,
                                "Stabilität": f"{entry.stability_percent:.1f}%",
                                "Δ Fahrer": f"+{entry.driver_delta}" if entry.driver_delta > 0 else str(entry.driver_delta),
                                "Bewertung": entry.evaluation,
                            })

                        df_freeze = pd.DataFrame(freeze_data)
                        st.dataframe(df_freeze, use_container_width=True, hide_index=True)

                        # Trade-off formula
                        st.markdown("**Trade-off Formel**")
                        st.code("+1 Fahrer → +5.5% Stabilität\n+€50k/Jahr → -11% Last-Minute Chaos")

                        # Recommendation
                        st.markdown("**Empfehlung**")
                        for rec in result.recommendations:
                            st.info(rec)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Driver-Friendly":
            st.markdown("""
            <div class="sr-info">
                <strong>Driver-Friendly Policy</strong><br>
                Analysiert Kosten von fahrer-freundlichen 3er-Chain-Regeln.
                Nur 30-60min Gaps vs Split-Gaps erlaubt.
            </div>
            """, unsafe_allow_html=True)

            baseline_seed = st.number_input("Baseline Seed", value=94, min_value=1, max_value=9999, key="df_seed")

            if st.button("Driver-Friendly berechnen", type="primary", key="run_driver_friendly"):
                with st.spinner("Berechne Driver-Friendly Policy..."):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        result = run_driver_friendly_policy(instance_list, baseline_seed=baseline_seed)

                        st.success("Driver-Friendly Policy berechnet")

                        # Results
                        col_a, col_b, col_c = st.columns(3)
                        with col_a:
                            st.metric("Baseline Fahrer", result.baseline_drivers)
                        with col_b:
                            st.metric("Driver-Friendly", result.entries[0].drivers if result.entries else "-")
                        with col_c:
                            delta = result.entries[0].driver_delta if result.entries else 0
                            st.metric("Δ Fahrer", f"+{delta}" if delta > 0 else str(delta))

                        # Cost-Benefit
                        st.markdown("**Kosten-Nutzen-Analyse**")
                        if result.entries:
                            entry = result.entries[0]
                            yearly_cost = abs(entry.driver_delta) * 50000
                            st.markdown(f"""
                            - **Mehrkosten**: +{entry.driver_delta} Fahrer/Woche = ~€{yearly_cost:,.0f}/Jahr
                            - **Benefits**:
                              - Höhere Fahrer-Zufriedenheit
                              - Weniger Beschwerden über "16h-Tage"
                              - Potenzielle Fluktuation ↓
                            - **Break-Even**: Wenn Fluktuation um 5% sinkt, lohnt es sich.
                              (Recruiting-Kosten ~€10k/Fahrer)
                            """)

                        # Risk
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'Risk Score: <span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Patch-Chaos":
            st.markdown("""
            <div class="sr-info">
                <strong>Patch-Chaos Simulation</strong><br>
                Simuliert was passiert wenn Mo/Di fix sind (LOCKED) und
                der Rest später kommt (PARTIAL → COMPLETE).
            </div>
            """, unsafe_allow_html=True)

            day_mapping = {"Mo": 1, "Di": 2, "Mi": 3, "Do": 4, "Fr": 5, "Sa": 6}

            locked_days_str = st.multiselect(
                "Bereits gesperrte Tage",
                options=["Mo", "Di", "Mi", "Do", "Fr", "Sa"],
                default=["Mo", "Di"],
                key="pc_locked"
            )

            # Calculate patch days (remaining days)
            all_days = {"Mo", "Di", "Mi", "Do", "Fr", "Sa"}
            patch_days_str = list(all_days - set(locked_days_str))

            st.caption(f"Patch enthält: {', '.join(sorted(patch_days_str, key=lambda x: day_mapping[x]))}")

            if st.button("Patch-Chaos simulieren", type="primary", key="run_patch_chaos"):
                with st.spinner("Berechne Patch-Chaos Simulation..."):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        locked_days = [day_mapping[d] for d in locked_days_str]
                        patch_days = [day_mapping[d] for d in patch_days_str]

                        result = run_patch_chaos(
                            instance_list,
                            locked_days=sorted(locked_days),
                            patch_days=sorted(patch_days)
                        )

                        st.success("Patch-Chaos Simulation abgeschlossen")

                        # Results
                        col_a, col_b, col_c, col_d = st.columns(4)
                        with col_a:
                            st.metric("Baseline", f"{result.baseline_drivers} Fahrer")
                        with col_b:
                            st.metric("Nach Integration", f"{result.integrated_drivers} Fahrer")
                        with col_c:
                            delta = result.driver_delta
                            st.metric("Δ Fahrer", f"+{delta}" if delta > 0 else str(delta))
                        with col_d:
                            st.metric("Freeze Violations", result.freeze_violations)

                        # Churn metrics
                        st.markdown("**Churn-Analyse (Locked Days)**")
                        col_e, col_f = st.columns(2)
                        with col_e:
                            st.metric("Churn Tours", result.churn_tours)
                        with col_f:
                            st.metric("Churn Rate", f"{result.churn_rate:.1%}")

                        # Risk Score
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'Risk Score: <span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                        # Recommendations
                        st.markdown("**Empfehlungen**")
                        for rec in result.recommendations:
                            st.info(rec)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Sick-Call Drill":
            st.markdown("""
            <div class="sr-info">
                <strong>Sick-Call Drill</strong><br>
                Simuliert: Wenn morgen früh X Fahrer ausfallen - wie schnell
                ist ein legaler Repair-Plan mit minimalem Churn verfügbar?
            </div>
            """, unsafe_allow_html=True)

            col_sick1, col_sick2 = st.columns(2)
            with col_sick1:
                num_sick = st.slider("Anzahl Ausfälle", min_value=1, max_value=10, value=5, key="sc_count")
            with col_sick2:
                target_day = st.selectbox(
                    "Betroffener Tag",
                    options=["Mo", "Di", "Mi", "Do", "Fr", "Sa"],
                    index=0,
                    key="sc_day"
                )

            day_mapping = {"Mo": 1, "Di": 2, "Mi": 3, "Do": 4, "Fr": 5, "Sa": 6}

            if st.button("Sick-Call simulieren", type="primary", key="run_sick_call"):
                with st.spinner("Berechne Sick-Call Drill..."):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        result = run_sick_call(
                            instance_list,
                            num_drivers_out=num_sick,
                            target_day=day_mapping[target_day]
                        )

                        st.success("Sick-Call Drill abgeschlossen")

                        # Results header
                        col_a, col_b, col_c = st.columns(3)
                        with col_a:
                            st.metric("Fahrer ausgefallen", result.drivers_out)
                        with col_b:
                            st.metric("Betroffene Touren", result.affected_tours)
                        with col_c:
                            st.metric("Repair-Zeit", f"{result.repair_time_seconds:.1f}s")

                        # Repair details
                        st.markdown("**Repair-Analyse**")
                        col_d, col_e, col_f = st.columns(3)
                        with col_d:
                            st.metric("Absorbierbar", result.absorbable_tours, help="Touren, die von bestehenden Fahrern übernommen werden können")
                        with col_e:
                            st.metric("Neue Fahrer benötigt", result.new_drivers_needed)
                        with col_f:
                            st.metric("Churn Rate", f"{result.churn_rate:.1%}")

                        # Compliance
                        st.markdown("**Compliance**")
                        if result.all_audits_pass:
                            st.success("Alle 7 Audits PASS - Repair-Plan ist compliant")
                        else:
                            st.error("Audit-Checks haben Probleme")

                        # Risk Score
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'Risk Score: <span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                        # Recommendations
                        st.markdown("**Empfehlungen**")
                        for rec in result.recommendations:
                            st.info(rec)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Tour-Stornierung":
            st.markdown("""
            <div class="sr-info">
                <strong>Tour-Stornierung Simulation</strong><br>
                Simuliert: Wenn 10-30 Touren kurzfristig wegfallen -
                wie viel Churn und wie viele Fahrer werden frei?
            </div>
            """, unsafe_allow_html=True)

            col_tc1, col_tc2 = st.columns(2)
            with col_tc1:
                num_cancel = st.slider("Anzahl Stornierungen", min_value=5, max_value=50, value=20, key="tc_count")
            with col_tc2:
                cancel_day = st.selectbox(
                    "Betroffener Tag (optional)",
                    options=["Alle Tage", "Mo", "Di", "Mi", "Do", "Fr", "Sa"],
                    index=0,
                    key="tc_day"
                )

            day_mapping = {"Mo": 1, "Di": 2, "Mi": 3, "Do": 4, "Fr": 5, "Sa": 6}

            if st.button("Tour-Stornierung simulieren", type="primary", key="run_tour_cancel"):
                with st.spinner("Berechne Tour-Stornierung..."):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        target_day = day_mapping.get(cancel_day) if cancel_day != "Alle Tage" else None

                        result = run_tour_cancel(
                            instance_list,
                            num_cancelled=num_cancel,
                            target_day=target_day
                        )

                        st.success("Tour-Stornierung Simulation abgeschlossen")

                        # Results header
                        col_a, col_b, col_c, col_d = st.columns(4)
                        with col_a:
                            st.metric("Baseline", f"{result.baseline_drivers} Fahrer")
                        with col_b:
                            st.metric("Storniert", f"{result.cancelled_tours} Touren")
                        with col_c:
                            st.metric("Fahrer frei", result.drivers_freed)
                        with col_d:
                            st.metric("Neue Fahrer", result.new_drivers)

                        # Churn analysis
                        st.markdown("**Churn-Analyse**")
                        col_e, col_f, col_g = st.columns(3)
                        with col_e:
                            st.metric("Reassignments", result.reassignment_churn)
                        with col_f:
                            st.metric("Churn Rate", f"{result.churn_rate:.1%}")
                        with col_g:
                            st.metric("Verbleibende Touren", result.new_tours)

                        # Risk Score
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'Risk Score: <span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                        # Recommendations
                        st.markdown("**Empfehlungen**")
                        for rec in result.recommendations:
                            st.info(rec)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Headcount-Budget":
            st.markdown("""
            <div class="sr-info">
                <strong>Headcount-Budget Advisor</strong><br>
                Ziel: Unter X Fahrer kommen. Welche Regeln müssen gelockert werden
                und was ist das Risiko?
            </div>
            """, unsafe_allow_html=True)

            # Get baseline first for reference
            baseline_drivers = st.session_state.get("baseline_drivers", 145)

            col_hb1, col_hb2 = st.columns(2)
            with col_hb1:
                target_drivers = st.number_input(
                    "Ziel-Fahrerzahl",
                    min_value=100,
                    max_value=200,
                    value=min(baseline_drivers - 5, 140),
                    key="hb_target"
                )
            with col_hb2:
                baseline_seed = st.number_input("Baseline Seed", value=94, min_value=1, max_value=9999, key="hb_seed")

            st.caption(f"Aktuell: ~{baseline_drivers} Fahrer | Ziel: {target_drivers} Fahrer | Gap: {baseline_drivers - target_drivers}")

            if st.button("Headcount-Budget berechnen", type="primary", key="run_headcount_budget"):
                with st.spinner("Berechne Headcount-Budget Analyse... (kann einige Sekunden dauern)"):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        result = run_headcount_budget(
                            instance_list,
                            target_drivers=target_drivers,
                            baseline_seed=baseline_seed
                        )

                        # Store baseline for reference
                        st.session_state["baseline_drivers"] = result.baseline_drivers

                        if result.achieved:
                            st.success(f"Ziel erreicht: {result.final_drivers} Fahrer (Ziel: {target_drivers})")
                        else:
                            st.warning(f"Ziel nicht erreicht: {result.final_drivers} Fahrer (Ziel: {target_drivers})")

                        # Results header
                        col_a, col_b, col_c, col_d = st.columns(4)
                        with col_a:
                            st.metric("Baseline", f"{result.baseline_drivers} Fahrer")
                        with col_b:
                            st.metric("Ziel", f"{result.target_drivers} Fahrer")
                        with col_c:
                            st.metric("Erreicht", f"{result.final_drivers} Fahrer")
                        with col_d:
                            st.metric("Lockerungen", len(result.relaxations))

                        # Relaxations table
                        if result.relaxations:
                            st.markdown("**Empfohlene Lockerungen**")
                            relax_data = []
                            for r in result.relaxations:
                                relax_data.append({
                                    "Regel": r.get("rule", "-"),
                                    "Δ Fahrer": r.get("savings", 0),
                                    "Risiko": r.get("risk", "-"),
                                    "ArbZG": r.get("arbzg_status", "-"),
                                })
                            df_relax = pd.DataFrame(relax_data)
                            st.dataframe(df_relax, use_container_width=True, hide_index=True)

                        # Risk Score
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'Risk Score: <span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                        # Recommendations
                        st.markdown("**Empfehlungen**")
                        for rec in result.recommendations:
                            st.info(rec)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Auto-Seed-Sweep":
            st.markdown("""
            <div class="sr-info">
                <strong>Auto-Seed-Sweep</strong><br>
                Testet automatisch mehrere Seeds parallel und findet den optimalen.
                Sortiert nach: Min Fahrer → Min PT → Max 3er → Min 1er.
            </div>
            """, unsafe_allow_html=True)

            col_as1, col_as2, col_as3 = st.columns(3)
            with col_as1:
                num_seeds = st.slider("Anzahl Seeds", min_value=5, max_value=30, value=15, key="as_count")
            with col_as2:
                use_extended = st.checkbox("Extended Seeds (1-100)", value=False, key="as_extended")
            with col_as3:
                parallel = st.checkbox("Parallel ausführen", value=True, key="as_parallel")

            if st.button("Auto-Seed-Sweep starten", type="primary", key="run_auto_sweep"):
                with st.spinner(f"Teste {num_seeds} Seeds... (parallel={parallel})"):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        # Progress placeholder
                        progress_text = st.empty()
                        progress_bar = st.progress(0)

                        def progress_callback(current, total, result_dict):
                            progress_bar.progress(current / total)
                            if result_dict:
                                progress_text.text(f"Seed {result_dict.get('seed', '?')}: {result_dict.get('total_drivers', '?')} Fahrer")

                        result = auto_seed_sweep(
                            instance_list,
                            num_seeds=num_seeds,
                            use_extended=use_extended,
                            parallel=parallel,
                            progress_callback=progress_callback if not parallel else None
                        )

                        progress_bar.progress(1.0)
                        progress_text.text(f"Fertig! Bester Seed: {result.best_seed}")

                        st.success(f"Auto-Seed-Sweep abgeschlossen in {result.execution_time_ms}ms")

                        # Best result header
                        st.markdown("**Bester Seed**")
                        col_a, col_b, col_c, col_d = st.columns(4)
                        with col_a:
                            st.metric("Seed", result.best_seed)
                        with col_b:
                            st.metric("Fahrer", result.best_drivers)
                        with col_c:
                            st.metric("FTE", result.best_result.fte_drivers)
                        with col_d:
                            st.metric("PT", result.best_result.pt_drivers)

                        # Block distribution
                        st.markdown("**Block-Verteilung (Bester Seed)**")
                        col_e, col_f, col_g, col_h = st.columns(4)
                        with col_e:
                            st.metric("1er", result.best_result.block_1er)
                        with col_f:
                            st.metric("2er-reg", result.best_result.block_2er_reg)
                        with col_g:
                            st.metric("2er-split", result.best_result.block_2er_split)
                        with col_h:
                            st.metric("3er", result.best_result.block_3er)

                        # Top 3 comparison
                        st.markdown("**Top 3 Seeds**")
                        top3_data = []
                        for i, r in enumerate(result.top_3, 1):
                            top3_data.append({
                                "Rang": i,
                                "Seed": r.seed,
                                "Fahrer": r.total_drivers,
                                "FTE": r.fte_drivers,
                                "PT": r.pt_drivers,
                                "1er": r.block_1er,
                                "3er": r.block_3er,
                                "Max h": f"{r.max_hours:.1f}",
                            })
                        df_top3 = pd.DataFrame(top3_data)
                        st.dataframe(df_top3, use_container_width=True, hide_index=True)

                        # All results expandable
                        with st.expander(f"Alle {result.seeds_tested} Ergebnisse"):
                            all_data = []
                            for r in sorted(result.all_results, key=lambda x: (x.total_drivers, x.pt_drivers)):
                                if r.success:
                                    all_data.append({
                                        "Seed": r.seed,
                                        "Fahrer": r.total_drivers,
                                        "FTE": r.fte_drivers,
                                        "PT%": f"{r.pt_ratio:.1f}%",
                                        "1er": r.block_1er,
                                        "3er": r.block_3er,
                                        "Max h": f"{r.max_hours:.1f}",
                                        "Zeit (ms)": r.execution_time_ms,
                                    })
                            df_all = pd.DataFrame(all_data)
                            st.dataframe(df_all, use_container_width=True, hide_index=True)

                        # Recommendation
                        st.markdown("**Empfehlung**")
                        st.info(result.recommendation)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        # =====================================================================
        # V3.2 ADVANCED SCENARIOS
        # =====================================================================
        elif selected_scenario == "Multi-Failure Cascade":
            st.markdown("""
            <div class="sr-info">
                <strong>Multi-Failure Cascade Simulation</strong><br>
                Simuliert kombinierte Ausfälle: N Fahrer krank + M Touren storniert + Cascade-Effekte.
                Jeder initiale Ausfall kann weitere Ausfälle triggern (Dominoeffekt).
            </div>
            """, unsafe_allow_html=True)

            col_mfc1, col_mfc2 = st.columns(2)

            with col_mfc1:
                num_sick = st.number_input("Fahrer krank", value=5, min_value=1, max_value=30, key="mfc_sick")
                num_cancel = st.number_input("Touren storniert", value=10, min_value=1, max_value=100, key="mfc_cancel")

            with col_mfc2:
                target_day = st.selectbox("Ziel-Tag", options=[1, 2, 3, 4, 5, 6], format_func=lambda x: ["Mo", "Di", "Mi", "Do", "Fr", "Sa"][x-1], key="mfc_day")
                cascade_prob = st.slider("Cascade-Wahrscheinlichkeit", 0.0, 0.5, 0.15, 0.05, key="mfc_cascade", help="Wahrscheinlichkeit, dass jeder Ausfall weitere triggert")

            if st.button("Multi-Failure Cascade simulieren", type="primary", key="run_mfc"):
                with st.spinner("Simuliere Multi-Failure Cascade..."):
                    try:
                        result = run_multi_failure_cascade(
                            num_drivers_out=num_sick,
                            num_tours_cancelled=num_cancel,
                            target_day=target_day,
                            cascade_probability=cascade_prob
                        )

                        # Risk badge
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'<span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                        # KPIs
                        kpi_cols = st.columns(4)
                        with kpi_cols[0]:
                            st.metric("Total Fahrer Out", result.drivers_out)
                        with kpi_cols[1]:
                            st.metric("Total Touren Cancelled", result.tours_cancelled)
                        with kpi_cols[2]:
                            st.metric("Cascade Events", len(result.cascade_events))
                        with kpi_cols[3]:
                            st.metric("Churn", f"{result.total_churn:.1%}")

                        col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
                        with col_kpi1:
                            st.metric("Neue Fahrer benötigt", result.new_drivers_needed)
                        with col_kpi2:
                            st.metric("Repair-Zeit", f"{result.repair_time_seconds:.1f}s")
                        with col_kpi3:
                            st.metric("Cascade-P", f"{result.probability_of_cascade:.1%}")

                        # Cascade events detail
                        if result.cascade_events:
                            st.markdown("**Cascade Events**")
                            cascade_data = []
                            for e in result.cascade_events:
                                cascade_data.append({
                                    "Runde": e["round"],
                                    "Neue Kranke": e["new_sick"],
                                    "Neue Stornierungen": e["new_cancelled"],
                                    "Trigger": e["trigger"]
                                })
                            st.dataframe(pd.DataFrame(cascade_data), use_container_width=True, hide_index=True)

                        # Best/Worst case
                        st.markdown("**Szenarien**")
                        st.info(f"Best Case: {result.best_case_drivers} Fahrer | Worst Case: {result.worst_case_drivers} Fahrer | Final: {result.final_drivers} Fahrer")

                        # Recommendations
                        st.markdown("**Empfehlungen**")
                        for rec in result.recommendations:
                            st.write(f"- {rec}")

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Probabilistic Churn":
            st.markdown("""
            <div class="sr-info">
                <strong>Probabilistic Churn Forecast (Monte Carlo)</strong><br>
                Führt N Simulationen durch, um die Wahrscheinlichkeitsverteilung
                der Churn-Rate unter verschiedenen Stressbedingungen zu berechnen.
            </div>
            """, unsafe_allow_html=True)

            col_pc1, col_pc2 = st.columns(2)

            with col_pc1:
                num_sims = st.number_input("Simulationen", value=100, min_value=10, max_value=1000, step=10, key="pc_sims")
                churn_threshold = st.slider("Churn-Schwelle", 0.05, 0.30, 0.10, 0.01, key="pc_threshold", help="Ab welcher Churn-Rate gilt 'kritisch'?")

            with col_pc2:
                failure_prob = st.slider("Basis-Ausfallwahrscheinlichkeit", 0.01, 0.15, 0.05, 0.01, key="pc_failure", help="Wahrscheinlichkeit, dass ein einzelner Fahrer/Tour ausfällt")
                conf_level = st.slider("Konfidenz-Level", 0.90, 0.99, 0.95, 0.01, key="pc_conf")

            if st.button("Monte Carlo Simulation starten", type="primary", key="run_pc"):
                with st.spinner(f"Führe {num_sims} Simulationen durch..."):
                    try:
                        result = run_probabilistic_churn(
                            num_simulations=num_sims,
                            churn_threshold=churn_threshold,
                            failure_probability=failure_prob,
                            confidence_level=conf_level
                        )

                        # Risk badge
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'<span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                        # KPIs
                        kpi_cols = st.columns(4)
                        with kpi_cols[0]:
                            st.metric("Mittlere Churn", f"{result.mean_churn:.2%}")
                        with kpi_cols[1]:
                            st.metric("Std. Abweichung", f"{result.std_churn:.2%}")
                        with kpi_cols[2]:
                            st.metric(f"P(Churn > {churn_threshold:.0%})", f"{result.probability_above_threshold:.1%}")
                        with kpi_cols[3]:
                            st.metric("95. Perzentil", f"{result.percentile_95:.2%}")

                        # Confidence interval
                        st.markdown("**Konfidenzintervall**")
                        ci_lower, ci_upper = result.confidence_interval
                        st.info(f"{conf_level:.0%} Konfidenzintervall: [{ci_lower:.2%}, {ci_upper:.2%}]")

                        # Histogram
                        st.markdown("**Churn-Verteilung**")
                        if result.histogram_data:
                            hist_df = pd.DataFrame({
                                "Bucket": [f"{i*5}-{(i+1)*5}%" for i in range(len(result.histogram_data))],
                                "Häufigkeit": result.histogram_data
                            })
                            st.bar_chart(hist_df.set_index("Bucket"))

                        # Percentiles
                        st.markdown("**Perzentile**")
                        perc_data = {
                            "Perzentil": ["5%", "50% (Median)", "95%"],
                            "Churn-Rate": [f"{result.percentile_5:.2%}", f"{result.percentile_50:.2%}", f"{result.percentile_95:.2%}"]
                        }
                        st.dataframe(pd.DataFrame(perc_data), use_container_width=True, hide_index=True)

                        # Recommendations
                        st.markdown("**Empfehlungen**")
                        for rec in result.recommendations:
                            st.write(f"- {rec}")

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Policy ROI Optimizer":
            st.markdown("""
            <div class="sr-info">
                <strong>Policy ROI Optimizer</strong><br>
                Evaluiert alle Kombinationen von Regellockerungen, um das optimale
                Kosten-Nutzen-Verhältnis innerhalb der gegebenen Constraints zu finden.
            </div>
            """, unsafe_allow_html=True)

            col_roi1, col_roi2 = st.columns(2)

            with col_roi1:
                budget = st.number_input("Fahrer-Budget (±)", value=5, min_value=1, max_value=20, key="roi_budget", help="Wie viele Fahrer können hinzugefügt/entfernt werden?")
                optimize_for = st.selectbox(
                    "Optimierungsziel",
                    options=["balanced", "cost", "stability"],
                    format_func=lambda x: {"balanced": "Balanced (Kosten + Stabilität)", "cost": "Kosten minimieren", "stability": "Stabilität maximieren"}[x],
                    key="roi_opt"
                )

            with col_roi2:
                arbzg_only = st.checkbox("Nur ArbZG-konforme Optionen", value=True, key="roi_arbzg")
                constraints = ["arbzg_compliant"] if arbzg_only else []

            if st.button("ROI optimieren", type="primary", key="run_roi"):
                with st.spinner("Evaluiere Regel-Kombinationen..."):
                    try:
                        result = run_policy_roi_optimizer(
                            budget_drivers=budget,
                            optimize_for=optimize_for,
                            constraints=constraints
                        )

                        # Risk badge
                        risk_class = "sr-badge-pass" if result.risk_score == RiskLevel.LOW else (
                            "sr-badge-warn" if result.risk_score == RiskLevel.MEDIUM else "sr-badge-fail"
                        )
                        st.markdown(f'<span class="sr-badge {risk_class}">{result.risk_score.value}</span>', unsafe_allow_html=True)

                        # Optimal combination
                        opt = result.optimal_combination
                        st.markdown("**Optimale Kombination**")

                        kpi_cols = st.columns(4)
                        with kpi_cols[0]:
                            st.metric("Fahrer-Delta", f"{opt.driver_delta:+d}")
                        with kpi_cols[1]:
                            st.metric("Ersparnis/Jahr", f"€{opt.cost_savings_eur:,.0f}")
                        with kpi_cols[2]:
                            st.metric("Stabilitäts-Impact", f"{opt.stability_impact:+.0%}")
                        with kpi_cols[3]:
                            st.metric("ROI Score", f"{opt.roi_score:.1f}")

                        if opt.policy_combination:
                            st.success(f"Policies: {' + '.join(opt.policy_combination)}")
                        else:
                            st.info("Keine Änderungen empfohlen (Baseline ist optimal)")

                        # Top combinations
                        st.markdown("**Top Kombinationen**")
                        combo_data = []
                        for c in result.all_combinations[:10]:
                            combo_data.append({
                                "Policies": " + ".join(c.policy_combination) or "(keine)",
                                "Δ Fahrer": c.driver_delta,
                                "Ersparnis": f"€{c.cost_savings_eur:,.0f}",
                                "Stabilität": f"{c.stability_impact:+.0%}",
                                "Risiko": c.risk_level.value,
                                "ROI": f"{c.roi_score:.1f}",
                                "ArbZG": "OK" if c.arbzg_compliant else "!"
                            })
                        st.dataframe(pd.DataFrame(combo_data), use_container_width=True, hide_index=True)

                        # Pareto frontier
                        st.markdown("**Pareto-Frontier (nicht-dominierte Optionen)**")
                        pareto_data = []
                        for p in result.pareto_frontier[:5]:
                            pareto_data.append({
                                "Policies": " + ".join(p.policy_combination) or "(keine)",
                                "Δ Fahrer": p.driver_delta,
                                "Stabilität": f"{p.stability_impact:+.0%}",
                                "Risiko": p.risk_level.value
                            })
                        st.dataframe(pd.DataFrame(pareto_data), use_container_width=True, hide_index=True)

                        # Recommendations
                        st.markdown("**Details**")
                        for rec in result.recommendations:
                            if rec.strip():
                                st.write(rec)

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

        elif selected_scenario == "Multi-Szenario-Vergleich":
            st.markdown("""
            <div class="sr-info">
                <strong>Multi-Szenario-Vergleich</strong><br>
                Vergleiche 3 verschiedene Konfigurationen side-by-side:
                Aggressiv (min Fahrer), Balanced, Safe (max Stabilität).
            </div>
            """, unsafe_allow_html=True)

            st.markdown("**Szenario-Profile**")
            col_cfg1, col_cfg2, col_cfg3 = st.columns(3)

            with col_cfg1:
                st.markdown("**AGGRESSIV**")
                agg_seed = st.number_input("Seed", value=42, min_value=1, max_value=9999, key="ms_agg_seed")
                agg_max_hours = st.number_input("Max Hours", value=58, min_value=45, max_value=60, key="ms_agg_hours")

            with col_cfg2:
                st.markdown("**BALANCED**")
                bal_seed = st.number_input("Seed", value=94, min_value=1, max_value=9999, key="ms_bal_seed")
                bal_max_hours = st.number_input("Max Hours", value=55, min_value=45, max_value=60, key="ms_bal_hours")

            with col_cfg3:
                st.markdown("**SAFE**")
                safe_seed = st.number_input("Seed", value=17, min_value=1, max_value=9999, key="ms_safe_seed")
                safe_max_hours = st.number_input("Max Hours", value=50, min_value=45, max_value=60, key="ms_safe_hours")

            if st.button("Multi-Szenario vergleichen", type="primary", key="run_multi_scenario"):
                with st.spinner("Berechne 3 Szenarien..."):
                    try:
                        instances = get_tour_instances(forecast_id)
                        instance_list = [
                            {
                                "id": inst["id"],
                                "day": inst["day"],
                                "start_ts": inst.get("start_ts"),
                                "end_ts": inst.get("end_ts"),
                                "work_hours": float(inst.get("work_hours", 0)),
                                "depot": inst.get("depot", "DEFAULT"),
                                "skill": inst.get("skill"),
                                "duration_min": int(float(inst.get("duration_min", 0)) if inst.get("duration_min") else 0),
                                "crosses_midnight": inst.get("crosses_midnight", False),
                            }
                            for inst in instances
                        ]

                        # Run all three scenarios using seed sweep
                        results = {}
                        configs = [
                            ("AGGRESSIV", agg_seed),
                            ("BALANCED", bal_seed),
                            ("SAFE", safe_seed),
                        ]

                        for name, seed in configs:
                            sweep_results = run_seed_sweep(instance_list, seeds=[seed])
                            if sweep_results:
                                results[name] = sweep_results[0]

                        st.success("Multi-Szenario-Vergleich abgeschlossen")

                        # Side-by-side comparison
                        st.markdown("**Vergleich**")

                        col_r1, col_r2, col_r3 = st.columns(3)

                        for col, (name, seed) in zip([col_r1, col_r2, col_r3], configs):
                            with col:
                                r = results.get(name)
                                if r:
                                    # Header with color
                                    if name == "AGGRESSIV":
                                        st.markdown(f'<div style="background:#f8d7da;padding:0.5rem;border-radius:4px;text-align:center;font-weight:bold;">{name}</div>', unsafe_allow_html=True)
                                    elif name == "BALANCED":
                                        st.markdown(f'<div style="background:#fff3cd;padding:0.5rem;border-radius:4px;text-align:center;font-weight:bold;">{name}</div>', unsafe_allow_html=True)
                                    else:
                                        st.markdown(f'<div style="background:#d4edda;padding:0.5rem;border-radius:4px;text-align:center;font-weight:bold;">{name}</div>', unsafe_allow_html=True)

                                    st.metric("Fahrer", r.get("total_drivers", "-"))
                                    st.metric("FTE", r.get("fte_drivers", "-"))
                                    st.metric("PT%", f"{r.get('pt_ratio', 0):.1f}%")
                                    st.metric("Max h", f"{r.get('max_hours', 0):.1f}")
                                    st.metric("3er Blocks", r.get("block_3er", "-"))
                                    st.caption(f"Seed: {seed}")
                                else:
                                    st.error(f"{name}: Fehler")

                        # Summary table
                        st.markdown("**Zusammenfassung**")
                        summary_data = []
                        for name, seed in configs:
                            r = results.get(name, {})
                            summary_data.append({
                                "Profil": name,
                                "Seed": seed,
                                "Fahrer": r.get("total_drivers", "-"),
                                "FTE": r.get("fte_drivers", "-"),
                                "PT%": f"{r.get('pt_ratio', 0):.1f}%" if r else "-",
                                "Max h": f"{r.get('max_hours', 0):.1f}" if r else "-",
                                "1er": r.get("block_1er", "-"),
                                "3er": r.get("block_3er", "-"),
                            })
                        df_summary = pd.DataFrame(summary_data)
                        st.dataframe(df_summary, use_container_width=True, hide_index=True)

                        # Recommendation
                        st.markdown("**Empfehlung**")
                        best_name = min(results.keys(), key=lambda k: (results[k].get("total_drivers", 999), results[k].get("pt_ratio", 999)))
                        st.info(f"Empfohlenes Profil: **{best_name}** mit {results[best_name].get('total_drivers', '-')} Fahrern")

                    except Exception as e:
                        st.error(f"Fehler: {e}")
                        import traceback
                        st.code(traceback.format_exc())

    else:
        st.warning("Keine Forecasts mit Status PASS gefunden. Bitte erst einen Forecast parsen!")


# ============================================================================
# Sidebar
# ============================================================================
with st.sidebar:
    # Logo/Brand
    st.markdown("""
    <div style="text-align: center; padding: 1rem 0;">
        <div style="background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
                    color: white; padding: 0.75rem 1rem; border-radius: 8px;
                    font-weight: 600; font-size: 1.1rem; letter-spacing: -0.02em;">
            SOLVEREIGN
        </div>
        <div style="font-size: 0.7rem; color: #718096; margin-top: 0.5rem;">
            V3 | Enterprise Dispatch
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Parameter Settings Section
    st.markdown("**Solver-Parameter**")

    # Initialize session state for parameters
    if "solver_seed" not in st.session_state:
        st.session_state["solver_seed"] = 94

    solver_seed = st.number_input(
        "Seed",
        min_value=1,
        max_value=9999,
        value=st.session_state.get("solver_seed", 94),
        help="Seed für deterministische Berechnung"
    )
    st.session_state["solver_seed"] = solver_seed

    st.markdown('<p class="sr-param-label">Hard Gates</p>', unsafe_allow_html=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.text("Rest: ≥11h")
        st.text("Span reg: ≤14h")
    with col_b:
        st.text("Span 3er: ≤16h")
        st.text("Split: 4-6h")

    st.divider()

    # Database Statistics
    st.markdown("**Datenbank**")

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM forecast_versions")
                fv_count = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) as count FROM plan_versions")
                pv_count = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) as count FROM plan_versions WHERE status = 'LOCKED'")
                locked_count = cur.fetchone()["count"]

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Forecasts", fv_count)
        with col2:
            st.metric("Pläne", pv_count)

        st.metric("Freigegeben", locked_count)
    except Exception as e:
        st.error(f"DB-Fehler: {e}")

    st.divider()

    # Workflow Info
    st.markdown("**Workflow**")
    st.markdown("""
    <div style="font-size: 0.8rem; color: #4a5568;">
    1. <b>Forecast</b> – Eingabe & Validierung<br>
    2. <b>Vergleich</b> – Versionen prüfen<br>
    3. <b>Planung</b> – Roster & Audits<br>
    4. <b>Release</b> – Freigabe & Export<br>
    5. <b>Simulation</b> – What-If Szenarien
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # Footer
    st.markdown(f"""
    <div style="font-size: 0.65rem; color: #a0aec0; text-align: center;">
        LTS Transport & Logistik GmbH<br>
        Stand: {datetime.now().strftime('%H:%M:%S')}
    </div>
    """, unsafe_allow_html=True)

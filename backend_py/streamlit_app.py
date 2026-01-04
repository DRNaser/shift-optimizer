"""
SOLVEREIGN V3 - Dispatcher Cockpit
====================================

4-Tab Streamlit UI for operational dispatch management.

Tabs:
    1. Parser - Input and validate forecast data
    2. Diff View - Compare forecast versions
    3. Plan Preview - View roster matrix and KPIs
    4. Release Control - Lock and export plans

Usage:
    streamlit run backend_py/streamlit_app.py

Requirements:
    pip install streamlit pandas
"""

import streamlit as st
import pandas as pd
from datetime import datetime, time
import json
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from v3 import db, models
    from v3.parser import parse_forecast_text
    from v3.diff_engine import compute_diff
    from v3.db_instances import expand_tour_template, get_tour_instances
    from v3.solver_wrapper import solve_and_audit
    from v3.audit_fixed import audit_plan_fixed
    from v3.export import export_release_package
    from v3.freeze_windows import classify_instances
except ImportError as e:
    st.error(f"Import error: {e}")
    st.stop()

# Page config
st.set_page_config(
    page_title="SOLVEREIGN Dispatcher",
    page_icon="🚚",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .status-pass { color: #28a745; font-weight: bold; }
    .status-warn { color: #ffc107; font-weight: bold; }
    .status-fail { color: #dc3545; font-weight: bold; }
    .metric-card {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# Title
st.title("SOLVEREIGN Dispatcher Cockpit")
st.caption("V3 MVP - Deterministic Dispatch Platform")

# Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "📥 Parser",
    "📊 Diff View",
    "🗓️ Plan Preview",
    "🚀 Release Control"
])


# ============================================================================
# TAB 1: Parser
# ============================================================================
with tab1:
    st.header("Forecast Input & Parser")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Input Forecast")

        input_method = st.radio(
            "Input Method",
            ["Paste Text", "Upload CSV"],
            horizontal=True
        )

        if input_method == "Paste Text":
            raw_text = st.text_area(
                "Paste Slack/Text Forecast",
                height=300,
                placeholder="""Mo 06:00-14:00 3 Fahrer Depot Nord
Di 07:00-15:00 2 Fahrer
Mi 14:00-22:00
Do 22:00-06:00
Fr 06:00-10:00 + 15:00-19:00"""
            )
        else:
            uploaded_file = st.file_uploader("Upload CSV", type=["csv", "txt"])
            if uploaded_file:
                raw_text = uploaded_file.read().decode("utf-8")
            else:
                raw_text = ""

        if st.button("🔍 Parse Forecast", type="primary"):
            if raw_text.strip():
                with st.spinner("Parsing..."):
                    try:
                        result = parse_forecast_text(
                            raw_text=raw_text,
                            source="streamlit",
                            save_to_db=False  # Dry run first
                        )

                        st.session_state["parse_result"] = result
                        st.session_state["raw_text"] = raw_text
                    except Exception as e:
                        st.error(f"Parse error: {e}")
            else:
                st.warning("Please enter forecast text")

    with col2:
        st.subheader("Parse Status")

        if "parse_result" in st.session_state:
            result = st.session_state["parse_result"]

            # Status badge
            status = result.get("status", "UNKNOWN")
            if status == "PASS":
                st.success(f"✅ Status: {status}")
            elif status == "WARN":
                st.warning(f"⚠️ Status: {status}")
            else:
                st.error(f"❌ Status: {status}")

            # Metrics
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Tours Parsed", result.get("tours_count", 0))
            with col_b:
                st.metric("Input Hash", result.get("input_hash", "")[:8] + "...")

            # Line-by-line results
            st.subheader("Parse Details")
            if "parse_results" in result:
                for pr in result["parse_results"]:
                    status_icon = "✅" if pr["status"] == "PASS" else "⚠️" if pr["status"] == "WARN" else "❌"
                    with st.expander(f"{status_icon} Line {pr['line_no']}: {pr.get('canonical_text', pr.get('raw_text', ''))[:50]}"):
                        st.text(f"Status: {pr['status']}")
                        st.text(f"Raw: {pr.get('raw_text', '')}")
                        if pr.get("canonical_text"):
                            st.text(f"Canonical: {pr['canonical_text']}")
                        if pr.get("issues"):
                            st.json(pr["issues"])

            # Save button
            if result.get("status") in ["PASS", "WARN"]:
                if st.button("💾 Save to Database"):
                    with st.spinner("Saving..."):
                        saved_result = parse_forecast_text(
                            raw_text=st.session_state["raw_text"],
                            source="streamlit",
                            save_to_db=True
                        )
                        st.success(f"Saved! Forecast Version ID: {saved_result.get('forecast_version_id')}")
                        st.session_state["last_forecast_id"] = saved_result.get("forecast_version_id")


# ============================================================================
# TAB 2: Diff View
# ============================================================================
with tab2:
    st.header("Forecast Comparison")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Select Versions")

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
                "Old Version (Base)",
                options=list(forecast_options.keys()),
                index=1 if len(forecast_options) > 1 else 0
            )
            new_version = st.selectbox(
                "New Version (Compare)",
                options=list(forecast_options.keys()),
                index=0
            )

            if st.button("🔄 Compute Diff", type="primary"):
                old_id = forecast_options[old_version]
                new_id = forecast_options[new_version]

                if old_id == new_id:
                    st.warning("Please select different versions")
                else:
                    with st.spinner("Computing diff..."):
                        try:
                            diff = compute_diff(old_id, new_id)
                            st.session_state["diff_result"] = diff
                        except Exception as e:
                            st.error(f"Diff error: {e}")
        else:
            st.info("No forecast versions found. Parse some data first!")

    with col2:
        st.subheader("Diff Results")

        if "diff_result" in st.session_state:
            diff = st.session_state["diff_result"]

            # Summary metrics
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("➕ Added", diff.added, delta_color="normal")
            with col_b:
                st.metric("➖ Removed", diff.removed, delta_color="inverse")
            with col_c:
                st.metric("🔄 Changed", diff.changed)

            # Diff details
            if diff.details:
                st.subheader("Change Details")

                # Filter
                filter_type = st.multiselect(
                    "Filter by type",
                    ["ADDED", "REMOVED", "CHANGED"],
                    default=["ADDED", "REMOVED", "CHANGED"]
                )

                # Display changes
                for detail in diff.details:
                    if detail.diff_type.value in filter_type:
                        if detail.diff_type.value == "ADDED":
                            st.markdown(f"➕ **ADDED**: {detail.fingerprint[:20]}...")
                        elif detail.diff_type.value == "REMOVED":
                            st.markdown(f"➖ **REMOVED**: {detail.fingerprint[:20]}...")
                        else:
                            st.markdown(f"🔄 **CHANGED**: {detail.fingerprint[:20]}...")
                            if detail.changed_fields:
                                st.text(f"   Changed: {', '.join(detail.changed_fields)}")


# ============================================================================
# TAB 3: Plan Preview
# ============================================================================
with tab3:
    st.header("Plan Preview")

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Select Plan")

        # Get available plan versions
        try:
            with db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT pv.id, pv.status, pv.created_at, pv.seed,
                               fv.id as forecast_id
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
            plan_options = {
                f"Plan {p['id']} ({p['status']}) - Seed {p['seed']}": p["id"]
                for p in plans
            }

            selected_plan = st.selectbox(
                "Select Plan Version",
                options=list(plan_options.keys())
            )

            plan_id = plan_options[selected_plan]

            if st.button("📊 Load Plan", type="primary"):
                with st.spinner("Loading..."):
                    try:
                        # Get assignments
                        assignments = db.get_assignments(plan_id)

                        # Get plan info
                        plan = db.get_plan_version(plan_id)

                        # Get audit results
                        audits = db.get_audit_logs(plan_id)

                        st.session_state["plan_data"] = {
                            "plan": plan,
                            "assignments": assignments,
                            "audits": audits
                        }
                    except Exception as e:
                        st.error(f"Load error: {e}")
        else:
            st.info("No plans found. Solve a forecast first!")

            # Solve button
            if "last_forecast_id" in st.session_state:
                if st.button("🧮 Solve Latest Forecast"):
                    with st.spinner("Solving..."):
                        try:
                            # Expand instances first
                            expand_tour_template(st.session_state["last_forecast_id"])

                            # Solve
                            result = solve_and_audit(
                                st.session_state["last_forecast_id"],
                                seed=94
                            )
                            st.success(f"Solved! Plan ID: {result['plan_version_id']}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Solve error: {e}")

    with col2:
        st.subheader("Plan Details")

        if "plan_data" in st.session_state:
            data = st.session_state["plan_data"]
            plan = data["plan"]
            assignments = data["assignments"]
            audits = data["audits"]

            # Status
            status = plan.get("status", "UNKNOWN")
            if status == "LOCKED":
                st.success(f"🔒 Status: {status}")
            else:
                st.info(f"📝 Status: {status}")

            # Metrics
            st.metric("Total Assignments", len(assignments))
            st.metric("Seed", plan.get("seed"))

            # Audit results
            st.subheader("Audit Status")
            for audit in audits:
                status_icon = "✅" if audit["status"] == "PASS" else "❌"
                st.text(f"{status_icon} {audit['check_name']}: {audit['status']}")

    # Roster Matrix
    if "plan_data" in st.session_state:
        st.subheader("Roster Matrix")

        assignments = st.session_state["plan_data"]["assignments"]
        if assignments:
            # Build matrix dataframe
            drivers = sorted(set(a["driver_id"] for a in assignments))
            days = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

            matrix_data = []
            for driver in drivers:
                driver_row = {"Driver": driver}
                for day_idx, day_name in enumerate(days, 1):
                    day_assignments = [a for a in assignments if a["driver_id"] == driver and a["day"] == day_idx]
                    if day_assignments:
                        driver_row[day_name] = len(day_assignments)
                    else:
                        driver_row[day_name] = ""
                matrix_data.append(driver_row)

            df = pd.DataFrame(matrix_data)
            st.dataframe(df, use_container_width=True)


# ============================================================================
# TAB 4: Release Control
# ============================================================================
with tab4:
    st.header("Release Control")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Release Checklist")

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

            # Check release gates
            can_release, blocking = db.can_release(plan_id)

            st.subheader("Gate Status")

            if can_release:
                st.success("✅ All mandatory checks passed!")
            else:
                st.error("❌ Cannot release - blocking checks:")
                for check in blocking:
                    st.text(f"   - {check}")

            # Freeze status
            st.subheader("Freeze Status")
            try:
                frozen_ids, modifiable_ids = classify_instances(plan["forecast_version_id"])
                st.text(f"🔒 Frozen tours: {len(frozen_ids)}")
                st.text(f"✏️ Modifiable tours: {len(modifiable_ids)}")
            except Exception as e:
                st.text(f"Freeze check: N/A ({e})")

        else:
            st.info("No DRAFT plans available for release")

    with col2:
        st.subheader("Release Actions")

        if draft_plans and can_release:
            st.warning("⚠️ Locking a plan is irreversible!")

            locked_by = st.text_input("Your Name/Email", value="dispatcher@lts.de")

            if st.button("🔒 LOCK & RELEASE", type="primary"):
                if locked_by:
                    with st.spinner("Locking plan..."):
                        try:
                            db.lock_plan_version(plan_id, locked_by)
                            st.success(f"✅ Plan {plan_id} LOCKED successfully!")

                            # Export
                            st.info("Generating export package...")
                            files = export_release_package(plan_id, "exports")
                            st.success("Export complete!")
                            for name, path in files.items():
                                st.text(f"  - {name}: {os.path.basename(path)}")
                        except Exception as e:
                            st.error(f"Lock failed: {e}")
                else:
                    st.warning("Please enter your name/email")

        elif draft_plans:
            st.info("Fix blocking checks before releasing")

        # View LOCKED plans
        st.subheader("Released Plans")

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
                    st.text(f"🔒 Plan {lp['id']} - Locked by {lp['locked_by']} at {lp['locked_at']}")
            else:
                st.text("No released plans yet")
        except Exception as e:
            st.text(f"Error: {e}")


# ============================================================================
# Sidebar
# ============================================================================
with st.sidebar:
    st.header("🚚 SOLVEREIGN V3")
    st.caption("Dispatcher Cockpit")

    st.divider()

    st.subheader("Quick Stats")

    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM forecast_versions")
                fv_count = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) as count FROM plan_versions")
                pv_count = cur.fetchone()["count"]

                cur.execute("SELECT COUNT(*) as count FROM plan_versions WHERE status = 'LOCKED'")
                locked_count = cur.fetchone()["count"]

        st.metric("Forecast Versions", fv_count)
        st.metric("Plan Versions", pv_count)
        st.metric("Released Plans", locked_count)
    except Exception as e:
        st.error(f"DB Error: {e}")

    st.divider()

    st.subheader("Help")
    st.markdown("""
    **Workflow:**
    1. **Parser** - Input & validate forecast
    2. **Diff** - Compare versions
    3. **Preview** - Review roster & audits
    4. **Release** - Lock & export

    **Documentation:**
    - [ROADMAP.md](backend_py/ROADMAP.md)
    - [SKILL.md](SKILL.md)
    """)

    st.divider()
    st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

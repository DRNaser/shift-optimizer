"""
SHIFT OPTIMIZER - Streamlit App
===============================
Web UI for the shift optimizer solver.
Deploy to Streamlit Cloud for persistent access.
"""

import streamlit as st
import pandas as pd
import json
import io
import re
from datetime import time as dt_time
from collections import defaultdict
from pathlib import Path

# Page config
st.set_page_config(
    page_title="Shift Optimizer",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .stMetric {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 0.5rem;
        color: white;
    }
    .block-container {
        padding-top: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================================
# IMPORTS - Only load solver if running locally with backend
# ============================================================================

SOLVER_AVAILABLE = False
try:
    import sys
    # Add backend_py to path for local development
    backend_path = Path(__file__).parent / "backend_py"
    if backend_path.exists():
        sys.path.insert(0, str(backend_path))
    
    from src.domain.models import Tour, Weekday
    from src.services.forecast_solver_v4 import solve_forecast_v4, ConfigV4
    SOLVER_AVAILABLE = True
except ImportError:
    st.warning("⚠️ Solver nicht verfügbar. Nur Demo-Modus aktiv.")

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

WEEKDAY_MAP = {
    'mo': Weekday.MONDAY if SOLVER_AVAILABLE else 'Mon',
    'mon': Weekday.MONDAY if SOLVER_AVAILABLE else 'Mon', 
    'monday': Weekday.MONDAY if SOLVER_AVAILABLE else 'Mon',
    'montag': Weekday.MONDAY if SOLVER_AVAILABLE else 'Mon',
    'di': Weekday.TUESDAY if SOLVER_AVAILABLE else 'Tue',
    'tue': Weekday.TUESDAY if SOLVER_AVAILABLE else 'Tue',
    'tuesday': Weekday.TUESDAY if SOLVER_AVAILABLE else 'Tue',
    'dienstag': Weekday.TUESDAY if SOLVER_AVAILABLE else 'Tue',
    'mi': Weekday.WEDNESDAY if SOLVER_AVAILABLE else 'Wed',
    'wed': Weekday.WEDNESDAY if SOLVER_AVAILABLE else 'Wed',
    'wednesday': Weekday.WEDNESDAY if SOLVER_AVAILABLE else 'Wed',
    'mittwoch': Weekday.WEDNESDAY if SOLVER_AVAILABLE else 'Wed',
    'do': Weekday.THURSDAY if SOLVER_AVAILABLE else 'Thu',
    'thu': Weekday.THURSDAY if SOLVER_AVAILABLE else 'Thu',
    'thursday': Weekday.THURSDAY if SOLVER_AVAILABLE else 'Thu',
    'donnerstag': Weekday.THURSDAY if SOLVER_AVAILABLE else 'Thu',
    'fr': Weekday.FRIDAY if SOLVER_AVAILABLE else 'Fri',
    'fri': Weekday.FRIDAY if SOLVER_AVAILABLE else 'Fri',
    'friday': Weekday.FRIDAY if SOLVER_AVAILABLE else 'Fri',
    'freitag': Weekday.FRIDAY if SOLVER_AVAILABLE else 'Fri',
    'sa': Weekday.SATURDAY if SOLVER_AVAILABLE else 'Sat',
    'sat': Weekday.SATURDAY if SOLVER_AVAILABLE else 'Sat',
    'saturday': Weekday.SATURDAY if SOLVER_AVAILABLE else 'Sat',
    'samstag': Weekday.SATURDAY if SOLVER_AVAILABLE else 'Sat',
    'so': Weekday.SUNDAY if SOLVER_AVAILABLE else 'Sun',
    'sun': Weekday.SUNDAY if SOLVER_AVAILABLE else 'Sun',
    'sunday': Weekday.SUNDAY if SOLVER_AVAILABLE else 'Sun',
    'sonntag': Weekday.SUNDAY if SOLVER_AVAILABLE else 'Sun',
}


def parse_time(time_str: str) -> dt_time:
    """Parse time string to datetime.time."""
    match = re.match(r'(\d{1,2}):(\d{2})', time_str.strip())
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        return dt_time(h % 24, m)
    return dt_time(0, 0)


def parse_csv_to_tours(df: pd.DataFrame) -> list:
    """Parse DataFrame to Tour objects."""
    tours = []
    
    # Find columns
    id_col = None
    day_col = None
    start_col = None
    end_col = None
    
    for col in df.columns:
        col_lower = col.lower()
        if 'id' in col_lower or 'tour' in col_lower:
            id_col = col
        elif 'day' in col_lower or 'tag' in col_lower or 'wochentag' in col_lower:
            day_col = col
        elif 'start' in col_lower or 'beginn' in col_lower:
            start_col = col
        elif 'end' in col_lower or 'ende' in col_lower:
            end_col = col
    
    if not all([day_col, start_col, end_col]):
        st.error(f"Spalten nicht gefunden. Benötigt: day/tag, start/beginn, end/ende")
        return []
    
    for idx, row in df.iterrows():
        try:
            day_str = str(row[day_col]).lower().strip()
            day = WEEKDAY_MAP.get(day_str)
            if not day:
                continue
            
            start = parse_time(str(row[start_col]))
            end = parse_time(str(row[end_col]))
            
            tour_id = str(row[id_col]) if id_col else f"T-{idx+1}"
            
            if SOLVER_AVAILABLE:
                tour = Tour(
                    id=tour_id,
                    day=day,
                    start_time=start,
                    end_time=end
                )
            else:
                tour = {
                    "id": tour_id,
                    "day": day,
                    "start_time": start.strftime("%H:%M"),
                    "end_time": end.strftime("%H:%M")
                }
            tours.append(tour)
        except Exception as e:
            continue
    
    return tours


# ============================================================================
# SIDEBAR
# ============================================================================

with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/delivery-truck.png", width=64)
    st.title("Shift Optimizer")
    st.caption("v4.0 - Policy-Based")
    
    st.divider()
    
    st.subheader("⚙️ Solver Konfiguration")
    
    time_limit = st.slider("Timeout (Sekunden)", 10, 300, 60, 10)
    min_hours = st.slider("Min. Stunden/FTE", 35, 45, 42)
    max_hours = st.slider("Max. Stunden/FTE", 48, 60, 53)
    
    st.divider()
    
    st.subheader("📊 Policy")
    use_policy = st.checkbox("Manual Policy verwenden", value=True)
    
    st.divider()
    
    st.caption("Solver Status:")
    if SOLVER_AVAILABLE:
        st.success("✅ Solver verfügbar")
    else:
        st.warning("⚠️ Demo-Modus")

# ============================================================================
# MAIN CONTENT
# ============================================================================

st.title("📅 Schicht-Optimierer")
st.markdown("Optimale Zuweisung von Touren zu Fahrern unter Einhaltung aller Constraints.")

# Tabs
tab1, tab2, tab3 = st.tabs(["📤 Tour-Upload", "🚀 Optimierung", "📈 Ergebnisse"])

# ============================================================================
# TAB 1: UPLOAD
# ============================================================================

with tab1:
    st.header("Tour-Daten laden")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        uploaded_file = st.file_uploader(
            "CSV-Datei mit Touren hochladen",
            type=["csv"],
            help="CSV mit Spalten: tour_id, day, start_time, end_time"
        )
        
        if uploaded_file:
            df = pd.read_csv(uploaded_file, sep=None, engine='python')
            st.session_state['tour_df'] = df
            st.success(f"✅ {len(df)} Zeilen geladen")
            
            with st.expander("📋 Vorschau"):
                st.dataframe(df.head(20), use_container_width=True)
    
    with col2:
        st.markdown("### Format")
        st.code("""tour_id,day,start_time,end_time
T-001,Mon,05:00,09:30
T-002,Mon,10:00,14:30
T-003,Tue,06:00,10:00
...""", language="csv")

# ============================================================================
# TAB 2: SOLVE
# ============================================================================

with tab2:
    st.header("Optimierung starten")
    
    if 'tour_df' not in st.session_state:
        st.info("⬆️ Bitte zuerst Tour-Daten hochladen.")
    else:
        df = st.session_state['tour_df']
        tours = parse_csv_to_tours(df)
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Touren", len(tours))
        with col2:
            st.metric("Erwartete FTEs", f"~{max(1, len(tours) // 8)}")
        with col3:
            st.metric("Timeout", f"{time_limit}s")
        
        st.divider()
        
        if st.button("🚀 Optimierung starten", type="primary", use_container_width=True):
            if not SOLVER_AVAILABLE:
                st.error("❌ Solver nicht verfügbar. Bitte lokal mit Backend starten.")
            elif len(tours) == 0:
                st.error("❌ Keine gültigen Touren gefunden.")
            else:
                with st.spinner("Optimiere... Das kann einige Minuten dauern."):
                    try:
                        config = ConfigV4(
                            min_hours_per_fte=float(min_hours),
                            max_hours_per_fte=float(max_hours),
                            time_limit_phase1=float(time_limit),
                        )
                        
                        result = solve_forecast_v4(tours, config)
                        st.session_state['result'] = result
                        st.session_state['result_dict'] = result.to_dict()
                        
                        st.success(f"✅ Fertig! Status: {result.status}")
                        st.balloons()
                        
                    except Exception as e:
                        st.error(f"❌ Fehler: {str(e)}")

# ============================================================================
# TAB 3: RESULTS
# ============================================================================

with tab3:
    st.header("Ergebnisse")
    
    if 'result' not in st.session_state:
        st.info("🔄 Bitte zuerst eine Optimierung durchführen.")
    else:
        result = st.session_state['result']
        result_dict = st.session_state['result_dict']
        kpi = result_dict.get('kpi', {})
        
        # KPIs
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Status", result.status)
        with col2:
            st.metric("FTE Fahrer", kpi.get('drivers_fte', 0))
        with col3:
            st.metric("PT Fahrer", kpi.get('drivers_pt', 0))
        with col4:
            st.metric("Blöcke", kpi.get('blocks_selected', 0))
        
        st.divider()
        
        # Block Mix
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📊 Block-Mix")
            block_mix = kpi.get('block_mix', {})
            if block_mix:
                mix_df = pd.DataFrame([
                    {"Typ": "1er", "Anteil": block_mix.get('1er', 0) * 100},
                    {"Typ": "2er", "Anteil": block_mix.get('2er', 0) * 100},
                    {"Typ": "3er", "Anteil": block_mix.get('3er', 0) * 100},
                ])
                st.bar_chart(mix_df.set_index("Typ"), height=200)
        
        with col2:
            st.subheader("⏱️ Zeiten")
            solve_times = result_dict.get('solve_times', {})
            st.json(solve_times)
        
        st.divider()
        
        # Driver List
        st.subheader("👥 Fahrer-Zuweisungen")
        
        drivers = result_dict.get('drivers', [])
        if drivers:
            driver_data = []
            for d in drivers[:50]:  # Limit to 50
                driver_data.append({
                    "Fahrer": d['driver_id'],
                    "Typ": d['type'],
                    "Stunden": d['hours_week'],
                    "Tage": d['days_worked'],
                    "Blöcke": len(d['blocks'])
                })
            
            st.dataframe(pd.DataFrame(driver_data), use_container_width=True)
        
        # Download
        st.divider()
        st.download_button(
            "📥 Ergebnis als JSON",
            data=json.dumps(result_dict, indent=2, ensure_ascii=False),
            file_name="solve_result.json",
            mime="application/json"
        )

# ============================================================================
# FOOTER
# ============================================================================

st.divider()
st.caption("Shift Optimizer v4.0 | Powered by OR-Tools CP-SAT | © LTS Transport")

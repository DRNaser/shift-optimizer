"""
PROMETHEUS METRICS - Canary Monitoring
=======================================
Exposes metrics for Grafana dashboards:
- Rollout Safety (budget overruns, infeasibility, signatures)
- Solver Performance (phase timings, path selection)
- Solution Quality (KPIs)

Usage:
    from src.api.prometheus_metrics import (
        record_run_completed,
        record_phase_timing,
        record_path_selection,
    )

Signature Tracking:
    Uses LRU window (last 5k signatures) to detect uniqueness.
    No high-cardinality labels - safe for long-running production.
"""

from prometheus_client import Counter, Histogram, Info
from collections import OrderedDict
import hashlib
import logging
import threading
import subprocess

logger = logging.getLogger("PrometheusMetrics")


# =============================================================================
# BUILD INFO METRIC (for version tracking)
# =============================================================================

def _get_git_commit_for_metrics() -> str:
    """Get short git commit hash for build info metric."""
    try:
        return subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


# Initialize build info metric at module load
build_info = Info('solver_build', 'Shift Optimizer build information')
build_info.info({
    'version': '2.0.0',
    'commit': _get_git_commit_for_metrics(),
    'ortools': '9.11.4210'
})


# =============================================================================
# SIGNATURE LRU WINDOW (prevents cardinality explosion)
# =============================================================================

class SignatureLRU:
    """
    Thread-safe LRU cache for signature tracking.
    Tracks last N signatures to detect uniqueness without exploding cardinality.
    """
    def __init__(self, max_size: int = 5000):
        self.max_size = max_size
        self._cache: OrderedDict[str, bool] = OrderedDict()
        self._lock = threading.Lock()
    
    def is_new(self, signature: str) -> bool:
        """
        Check if signature is new (not seen in window).
        Returns True if new, False if seen before.
        Thread-safe.
        """
        sig_hash = hashlib.md5(signature.encode()).hexdigest()
        
        with self._lock:
            if sig_hash in self._cache:
                # Move to end (most recent)
                self._cache.move_to_end(sig_hash)
                return False
            
            # New signature
            self._cache[sig_hash] = True
            
            # Evict oldest if over capacity
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)
            
            return True
    
    def size(self) -> int:
        """Current cache size."""
        with self._lock:
            return len(self._cache)


# Global signature tracker (5k window)
_signature_lru = SignatureLRU(max_size=5000)


# =============================================================================
# ROLLOUT SAFETY METRICS
# =============================================================================

# Budget overrun counter - should be 0 in healthy state
budget_overrun_counter = Counter(
    'solver_budget_overrun_total',
    'Number of runs with budget overrun reason code',
    ['phase']  # phase1, phase2, lns, total
)

# Infeasible run counter
infeasible_counter = Counter(
    'solver_infeasible_total',
    'Number of runs that returned INFEASIBLE status'
)

# Signature tracking (NO LABELS - uses LRU window)
signature_runs_total = Counter(
    'solver_signature_runs_total',
    'Total number of completed solver runs'
)

signature_unique_total = Counter(
    'solver_signature_unique_total',
    'Number of unique signatures seen (within LRU window)'
    # NO labels - safe for production
)

# Error counter
api_error_counter = Counter(
    'solver_api_error_total',
    'Number of API errors',
    ['endpoint', 'error_type']
)


# =============================================================================
# SOLVER PERFORMANCE METRICS
# =============================================================================

# Phase duration histograms
phase_duration = Histogram(
    'solver_phase_duration_seconds',
    'Duration of each solver phase',
    ['phase'],  # profiling, phase1, phase2, lns, total
    buckets=[0.5, 1, 2, 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300]
)

# Path selection counter
path_selection_counter = Counter(
    'solver_path_selection_total',
    'Path selection counts by path type',
    ['path', 'reason']  # path: A/B/C, reason: NORMAL_INSTANCE, PEAKY_HIGH, etc.
)

# Fallback counter
fallback_counter = Counter(
    'solver_fallback_total',
    'Number of fallback triggers',
    ['from_path', 'to_path']  # A->B, B->C
)

# SetPartitioning metrics
set_partitioning_counter = Counter(
    'solver_set_partitioning_total',
    'Set partitioning activation counts',
    ['status']  # success, fallback, timeout
)


# =============================================================================
# SOLUTION QUALITY METRICS (KPIs)
# =============================================================================

# Driver counts histogram
driver_count = Histogram(
    'solver_driver_count',
    'Number of drivers in solution',
    ['driver_type'],  # fte, pt, total
    buckets=[50, 75, 100, 125, 150, 175, 200, 250, 300]
)

# Ratio metrics (as histograms for distribution)
pt_ratio_histogram = Histogram(
    'solver_pt_ratio',
    'Ratio of PT drivers to total drivers',
    buckets=[0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]
)

underfull_ratio_histogram = Histogram(
    'solver_underfull_ratio',
    'Ratio of underfull FTE drivers',
    buckets=[0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5]
)

# Coverage rate histogram
coverage_rate_histogram = Histogram(
    'solver_coverage_rate',
    'Tour coverage rate (assigned / total)',
    buckets=[0.9, 0.92, 0.94, 0.96, 0.98, 0.99, 0.995, 1.0]
)


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def record_run_completed(run_report: dict):
    """
    Record metrics from a completed run report.
    
    Args:
        run_report: Dictionary with run report data
    """
    try:
        # Increment runs counter
        signature_runs_total.inc()
        
        # Record signature uniqueness using LRU window (NO high-cardinality labels)
        if 'solution_signature' in run_report:
            sig = run_report['solution_signature']
            if _signature_lru.is_new(sig):
                signature_unique_total.inc()
        
        # Check for budget overrun
        reason_codes = run_report.get('reason_codes', [])
        if 'BUDGET_OVERRUN' in str(reason_codes):
            budget_overrun_counter.labels(phase='total').inc()
        elif run_report.get('total_runtime', 0) > run_report.get('time_budget', float('inf')):
             # Hard consistency check: if runtime > budget, count as overrun even if reason code missing
             budget_overrun_counter.labels(phase='total').inc()
        
        # Check status
        status = run_report.get('status', '')
        if status == 'INFEASIBLE':
            infeasible_counter.inc()
        
        # Record KPIs
        kpi = run_report.get('kpi', {})
        if 'drivers_fte' in kpi:
            driver_count.labels(driver_type='fte').observe(kpi['drivers_fte'])
        if 'drivers_pt' in kpi:
            driver_count.labels(driver_type='pt').observe(kpi['drivers_pt'])
        
        # Compute total if not present
        drivers_total = kpi.get('drivers_total')
        if drivers_total is None:
            drivers_total = kpi.get('drivers_fte', 0) + kpi.get('drivers_pt', 0)
        if drivers_total > 0:
            driver_count.labels(driver_type='total').observe(drivers_total)
        
        # Record ratios
        if 'pt_ratio' in kpi:
            pt_ratio_histogram.observe(kpi['pt_ratio'])
        if 'underfull_ratio' in kpi:
            underfull_ratio_histogram.observe(kpi['underfull_ratio'])
        if 'coverage_rate' in kpi:
            coverage_rate_histogram.observe(kpi['coverage_rate'])
            
    except Exception as e:
        logger.warning(f"Failed to record run metrics: {e}")


def record_phase_timing(phase_name: str, duration_seconds: float):
    """Record phase duration."""
    phase_duration.labels(phase=phase_name).observe(duration_seconds)


def record_path_selection(path: str, reason: str):
    """Record path selection decision."""
    path_selection_counter.labels(path=path, reason=reason).inc()


def record_fallback(from_path: str, to_path: str):
    """Record fallback event."""
    fallback_counter.labels(from_path=from_path, to_path=to_path).inc()


def record_api_error(endpoint: str, error_type: str):
    """Record API error."""
    api_error_counter.labels(endpoint=endpoint, error_type=error_type).inc()


def record_candidate_counts(counts: dict[str, int]):
    """
    Record raw and kept candidate counts by size.
    Args:
        counts: Dict with keys blocks_Xer (kept) and raw_Xer (raw)
    """
    # Kept counts
    if 'blocks_1er' in counts:
        candidates_kept_counter.labels(size='1er').inc(counts['blocks_1er'])
    if 'blocks_2er' in counts:
        candidates_kept_counter.labels(size='2er').inc(counts['blocks_2er'])
    if 'blocks_3er' in counts:
        candidates_kept_counter.labels(size='3er').inc(counts['blocks_3er'])

    # Raw counts
    if 'raw_1er' in counts:
        candidates_raw_counter.labels(size='1er').inc(counts['raw_1er'])
    if 'raw_2er' in counts:
        candidates_raw_counter.labels(size='2er').inc(counts['raw_2er'])
    if 'raw_3er' in counts:
        candidates_raw_counter.labels(size='3er').inc(counts['raw_3er'])

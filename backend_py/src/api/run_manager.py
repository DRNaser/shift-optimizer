"""
SHIFT OPTIMIZER - Run Manager v2
=================================
Manages async solver runs, event streaming, and state persistence for v2.0 API.
Implements: Rate limiting, heartbeat, deterministic input sorting, config tracking, cleanup.
Real-time progress events with structured schema for SSE streaming.
"""

import json
import uuid
import time
import logging
import threading
import os
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path

from src.services.portfolio_controller import run_portfolio, PortfolioResult, BudgetSlice
from src.services.forecast_solver_v4 import ConfigV4
from src.domain.models import Tour, Driver

logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

MAX_RUNS_IN_MEMORY = 100  # Cleanup old runs after this limit
MAX_EVENTS_PER_RUN = 5000  # Ring buffer size
LOG_RATE_LIMIT_PER_SEC = 10  # Max solver_log events per second
LOG_MSG_MAX_CHARS = 500  # Truncate long log messages
HEARTBEAT_INTERVAL_SEC = 5.0  # SSE heartbeat interval

# Stall detection thresholds (user-approved)
STALL_ROUNDS_THRESHOLD = 6  # Stall after N rounds without improvement
STALL_SECONDS_THRESHOLD = 45.0  # OR stall after N seconds without improvement
STALL_MIN_ROUNDS = 3  # Minimum rounds before stall detection activates

# Artifacts directory
ARTIFACTS_DIR = Path(__file__).parent.parent.parent / "artifacts"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    """Stable event types for progress tracking."""
    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    HEARTBEAT = "heartbeat"
    METRIC = "metric"
    RMP_ROUND = "rmp_round"
    CG_ROUND = "cg_round"
    REPAIR_ACTION = "repair_action"
    IMPROVEMENT = "improvement"
    STALL = "stall"
    ARTIFACT_WRITTEN = "artifact_written"
    QUALITY_GATE = "quality_gate"
    ERROR = "error"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    SOLVER_LOG = "solver_log"


class Phase(str, Enum):
    """Pipeline phases for progress tracking."""
    PHASE0_BLOCK_BUILD = "phase0_block_build"
    PHASE1_CAPACITY = "phase1_capacity"
    PHASE2_SET_PARTITION = "phase2_set_partition"
    POST_REPAIR = "post_repair"
    EXPORT = "export"
    QUALITY_GATE = "quality_gate"


@dataclass
class ProgressEvent:
    """Structured progress event with stable schema for SSE streaming."""
    ts_iso: str
    run_id: str
    level: str  # INFO/WARN/ERROR
    event_type: str  # EventType value
    phase: Optional[str]  # Phase value
    step: Optional[str]  # e.g., "cp_sat_solve", "rmp_solve", "column_generation"
    message: str
    elapsed_s: float
    metrics: Optional[Dict[str, Any]] = None  # drivers_active, u_sum, pool_total, etc.
    context: Optional[Dict[str, Any]] = None  # round_idx, seed, peak_days, etc.
    seq: int = 0

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        # Remove None values for cleaner output
        return {k: v for k, v in d.items() if v is not None}

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)


@dataclass
class ConfigSnapshot:
    """Snapshot of effective config for audit trail."""
    config_effective_hash: str
    config_effective_dict: dict
    overrides_applied: dict
    overrides_rejected: dict
    overrides_clamped: dict
    reason_codes: List[str]


@dataclass
class RunContext:
    run_id: str
    status: RunStatus
    created_at: datetime
    input_summary: dict
    config: ConfigV4
    config_snapshot: Optional[ConfigSnapshot] = None
    time_budget: float = 30.0
    budget_slices: Optional[dict] = None
    events: List[dict] = field(default_factory=list)
    result: Optional[PortfolioResult] = None
    error: Optional[str] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_log_time: float = field(default=0.0)
    _log_count_this_sec: int = field(default=0)
    # Run timing for elapsed calculation
    _run_start_time: Optional[float] = None
    # JSONL file handle
    _jsonl_file: Optional[Any] = None
    # Stall detection state
    _last_improvement_time: float = field(default=0.0)
    _last_improvement_round: int = field(default=0)
    _best_drivers_active: int = field(default=999999)
    _best_u_sum: int = field(default=999999)

    def _get_elapsed_s(self) -> float:
        """Get seconds elapsed since run started."""
        if self._run_start_time is None:
            return 0.0
        return time.time() - self._run_start_time

    def _ensure_jsonl_file(self):
        """Lazy-init JSONL file for event persistence."""
        if self._jsonl_file is None:
            ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
            jsonl_path = ARTIFACTS_DIR / f"run_events_{self.run_id}.jsonl"
            self._jsonl_file = open(jsonl_path, 'a', encoding='utf-8')
            logger.info(f"Opened JSONL sink: {jsonl_path}")

    def _write_jsonl(self, event_dict: dict):
        """Write event to JSONL file."""
        try:
            self._ensure_jsonl_file()
            self._jsonl_file.write(json.dumps(event_dict, default=str) + '\n')
            self._jsonl_file.flush()
        except Exception as e:
            logger.warning(f"Failed to write JSONL event: {e}")

    def emit_progress(
        self,
        event_type: str,
        message: str,
        phase: Optional[str] = None,
        step: Optional[str] = None,
        level: str = "INFO",
        metrics: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ProgressEvent:
        """
        Emit a structured progress event.
        
        - Adds to ring buffer for SSE streaming
        - Writes to JSONL file for persistence
        - Returns the created ProgressEvent
        """
        with self._lock:
            seq = len(self.events)
            elapsed_s = self._get_elapsed_s()
            
            # Create structured event
            progress_event = ProgressEvent(
                ts_iso=datetime.now().isoformat(),
                run_id=self.run_id,
                level=level,
                event_type=event_type,
                phase=phase,
                step=step,
                message=message,
                elapsed_s=round(elapsed_s, 2),
                metrics=metrics,
                context=context,
                seq=seq
            )
            
            # Convert to dict for storage
            event_dict = progress_event.to_dict()
            # Add 'event' key for SSE compatibility
            event_dict["event"] = event_type
            event_dict["ts"] = event_dict.pop("ts_iso", datetime.now().isoformat())
            
            # Ring buffer: remove oldest if over limit
            if len(self.events) >= MAX_EVENTS_PER_RUN:
                self.events.pop(0)
                
            self.events.append(event_dict)
            
        # Write to JSONL (outside lock to avoid blocking)
        self._write_jsonl(event_dict)
        
        return progress_event

    def check_improvement(
        self,
        round_idx: int,
        drivers_active: int,
        u_sum: int
    ) -> Optional[str]:
        """
        Check for improvement and stall detection.
        
        Returns:
        - "improvement" if new best found
        - "stall" if stall detected
        - None otherwise
        """
        now = time.time()
        
        # Check for improvement
        improved = False
        if drivers_active < self._best_drivers_active:
            self._best_drivers_active = drivers_active
            improved = True
        if u_sum < self._best_u_sum:
            self._best_u_sum = u_sum
            improved = True
            
        if improved:
            self._last_improvement_time = now
            self._last_improvement_round = round_idx
            return "improvement"
        
        # Check for stall (only after minimum rounds)
        if round_idx >= STALL_MIN_ROUNDS:
            rounds_since = round_idx - self._last_improvement_round
            seconds_since = now - self._last_improvement_time if self._last_improvement_time > 0 else 0
            
            if rounds_since >= STALL_ROUNDS_THRESHOLD or seconds_since >= STALL_SECONDS_THRESHOLD:
                return "stall"
        
        return None

    def add_event(self, event_type: str, payload: dict, level: str = "INFO", phase: str = None):
        """Thread-safe event append with ring buffer (legacy compatibility)."""
        with self._lock:
            seq = len(self.events)
            event = {
                "run_id": self.run_id,
                "seq": seq,
                "ts": datetime.now().isoformat(),
                "level": level,
                "event": event_type,
                "phase": phase,
                "payload": payload
            }
            
            # Ring buffer: remove oldest if over limit
            if len(self.events) >= MAX_EVENTS_PER_RUN:
                self.events.pop(0)
                
            self.events.append(event)
            
        # Also write to JSONL
        self._write_jsonl(event)
            
    def add_log_event(self, msg: str, phase: str = None) -> bool:
        """
        Add solver_log event with rate limiting.
        Returns False if rate limit exceeded (event dropped).
        """
        current_time = time.time()
        
        with self._lock:
            # Reset counter each second
            if current_time - self._last_log_time >= 1.0:
                self._log_count_this_sec = 0
                self._last_log_time = current_time
                
            # Check rate limit
            if self._log_count_this_sec >= LOG_RATE_LIMIT_PER_SEC:
                return False
                
            self._log_count_this_sec += 1
            
        # Truncate message
        if len(msg) > LOG_MSG_MAX_CHARS:
            msg = msg[:LOG_MSG_MAX_CHARS] + "...[truncated]"
            
        self.add_event("solver_log", {"msg": msg}, phase=phase)
        return True
        
    def get_events_from(self, start_seq: int) -> List[dict]:
        """Get events starting from seq (for SSE resume)."""
        with self._lock:
            # Find events with seq >= start_seq
            return [e for e in self.events if e["seq"] >= start_seq]

    def close(self):
        """Close JSONL file handle."""
        if self._jsonl_file:
            try:
                self._jsonl_file.close()
            except Exception:
                pass
            self._jsonl_file = None


def _compute_drivers_total(solution) -> int:
    """Compute drivers_total with robust fallback and logging.
    
    Primary: drivers_fte + drivers_pt from KPI (preferred source)
    Fallback: Count DriverAssignment objects (each represents one unique driver)
    """
    kpi = solution.kpi if solution else {}
    
    # Primary: from KPI
    fte = kpi.get("drivers_fte", 0) or 0
    pt = kpi.get("drivers_pt", 0) or 0
    primary = fte + pt
    
    if primary > 0:
        return primary
    
    # Fallback: count DriverAssignment objects (each = one unique driver)
    if hasattr(solution, 'assignments') and solution.assignments:
        fallback = len(solution.assignments)
        logger.warning(
            f"drivers_total fallback used: {fallback} drivers "
            f"(KPI had fte={fte}, pt={pt})"
        )
        return fallback
    
    logger.error("drivers_total: no valid source, returning 0")
    return 0


class RunManager:
    """Singleton run manager with cleanup policy."""
    
    def __init__(self):
        self.runs: Dict[str, RunContext] = {}
        self._executor_threads: Dict[str, threading.Thread] = {}
        self._run_order: List[str] = []  # For FIFO cleanup

    def create_run(
        self, 
        tours: List[Tour], 
        drivers: List[Driver], 
        config: ConfigV4, 
        week_start: Any, 
        time_budget: float,
        config_snapshot: Optional[ConfigSnapshot] = None
    ) -> str:
        # Cleanup old runs if needed
        self._cleanup_old_runs()
        
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        
        # Sort tours deterministically before passing to solver
        sorted_tours = sorted(
            tours, 
            key=lambda t: (t.day.value, t.start_time.hour, t.start_time.minute, t.id)
        )
        
        # Compute budget slices for visibility
        slices = BudgetSlice.from_total(time_budget)
        
        ctx = RunContext(
            run_id=run_id,
            status=RunStatus.QUEUED,
            created_at=datetime.now(),
            input_summary={
                "tours": len(tours), 
                "drivers": len(drivers),
                "tours_sorted": True
            },
            config=config,
            config_snapshot=config_snapshot,
            time_budget=time_budget,
            budget_slices=slices.to_dict()
        )
        self.runs[run_id] = ctx
        self._run_order.append(run_id)
        
        # Start background execution
        thread = threading.Thread(
            target=self._execute_run,
            args=(ctx, sorted_tours, drivers, week_start, time_budget),
            daemon=True
        )
        self._executor_threads[run_id] = thread
        thread.start()
        
        return run_id

    def get_run(self, run_id: str) -> Optional[RunContext]:
        return self.runs.get(run_id)
        
    def list_runs(self, limit: int = 50, status: Optional[str] = None) -> List[dict]:
        """List recent runs."""
        runs = []
        for run_id in reversed(self._run_order[-limit:]):
            ctx = self.runs.get(run_id)
            if ctx:
                if status and ctx.status.value != status:
                    continue
                runs.append({
                    "run_id": run_id,
                    "status": ctx.status.value,
                    "created_at": ctx.created_at.isoformat()
                })
        return runs

    def cancel_run(self, run_id: str) -> bool:
        """Cancel a running run. Returns True if cancelled."""
        ctx = self.runs.get(run_id)
        if ctx and ctx.status in [RunStatus.QUEUED, RunStatus.RUNNING]:
            ctx.status = RunStatus.CANCELLED
            ctx.add_event("run_cancelled", {}, level="WARN")
            return True
        return False
        
    def _cleanup_old_runs(self):
        """Remove oldest runs if over limit."""
        while len(self._run_order) > MAX_RUNS_IN_MEMORY:
            old_run_id = self._run_order.pop(0)
            if old_run_id in self.runs:
                del self.runs[old_run_id]
            if old_run_id in self._executor_threads:
                del self._executor_threads[old_run_id]

    def _execute_run(
        self, 
        ctx: RunContext, 
        tours: List[Tour], 
        drivers: List[Driver], 
        week_start: Any, 
        time_budget: float
    ):
        """Blocking execution wrapper with structured progress events."""
        ctx.status = RunStatus.RUNNING
        ctx._run_start_time = time.time()  # Set start time for elapsed calculation
        
        # P3: Run Watchdog - enforce hard deadline
        from time import monotonic
        WATCHDOG_BUFFER_S = 30.0
        run_deadline = monotonic() + time_budget + WATCHDOG_BUFFER_S
        watchdog_triggered = [False]  # Mutable for closure
        
        def watchdog():
            stop_event = threading.Event()
            while monotonic() < run_deadline and not stop_event.is_set():
                if stop_event.wait(5): # Check every 5s
                    return
                # Emit heartbeat
                if ctx.status == RunStatus.RUNNING:
                    ctx.emit_progress("heartbeat", "Running...", level="DEBUG")
                    
                if ctx.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED):
                    return  # Run finished normally
            # Deadline exceeded
            if ctx.status == RunStatus.RUNNING:
                watchdog_triggered[0] = True
                logger.warning(f"Run {ctx.run_id} exceeded hard deadline ({time_budget}s + {WATCHDOG_BUFFER_S}s buffer)")
                ctx.status = RunStatus.FAILED
                ctx.error = "TIMED_OUT"
                ctx.emit_progress(
                    event_type=EventType.ERROR.value,
                    message="Hard deadline exceeded",
                    level="ERROR",
                    metrics={"drivers_total": 0},
                    context={"reason": "HARD_DEADLINE_EXCEEDED", "budget_s": time_budget}
                )
        
        # Start watchdog thread
        watchdog_thread = threading.Thread(target=watchdog, daemon=True)
        watchdog_thread.start()
        
        # Emit run_started with structured progress event
        ctx.emit_progress(
            event_type=EventType.RUN_STARTED.value,
            message=f"Optimization started with {len(tours)} tours",
            phase=None,
            step=None,
            level="INFO",
            metrics={
                "tours_count": len(tours),
                "drivers_pool": len(drivers),
                "time_budget_s": time_budget
            },
            context={
                "seed": ctx.config.seed,
                "budget_slices": ctx.budget_slices,
                "config_hash": ctx.config_snapshot.config_effective_hash if ctx.config_snapshot else None
            }
        )

        # Track current phase for log attribution
        current_phase = [None]  # Mutable container for closure

        # Log listener with rate limiting
        def log_fn(msg: str):
            # Detect phase from log content (case-insensitive)
            phase = current_phase[0]
            normalized = msg.upper()
            if "PHASE 1" in normalized or "INSTANCE PROFILING" in normalized:
                phase = "PROFILING"
                current_phase[0] = phase
            elif "PHASE 3" in normalized or "BLOCK SELECTION" in normalized or "CAPACITY PLANNING" in normalized:
                phase = "BLOCK_SELECTION"
                current_phase[0] = phase
            elif "PHASE 4" in normalized or "EXECUTING PATH" in normalized or "SET-PARTITIONING" in normalized:
                phase = "SOLVER_EXECUTION"
                current_phase[0] = phase
            elif normalized.startswith("LNS ") or normalized.startswith("LNS:"):
                if any(
                    token in normalized
                    for token in ("PROCESSING", "ENDGAME", "REFINEMENT")
                ):
                    if current_phase[0] in ("SOLVER_EXECUTION", "LNS"):
                        phase = "LNS"
                        current_phase[0] = phase
            elif "REPAIR" in normalized:
                phase = "REPAIR"
                current_phase[0] = phase

            # Rate-limited log
            ctx.add_log_event(msg, phase=phase)

        try:
            # Execute solver
            result = run_portfolio(
                tours=tours,
                time_budget=time_budget,
                seed=ctx.config.seed,
                config=ctx.config,
                log_fn=log_fn,
                context=ctx
            )
            
            ctx.result = result
            ctx.status = RunStatus.COMPLETED
            
            # Extract KPIs for structured event
            kpi = result.solution.kpi if result.solution and result.solution.kpi else {}
            drivers_fte = kpi.get("drivers_fte", 0) or 0
            drivers_pt = kpi.get("drivers_pt", 0) or 0
            drivers_total = _compute_drivers_total(result.solution)
            
            # Emit run_completed with structured progress event
            ctx.emit_progress(
                event_type=EventType.RUN_COMPLETED.value,
                message=f"Optimization completed: {drivers_total} drivers ({drivers_fte} FTE, {drivers_pt} PT)",
                phase=None,
                step=None,
                level="INFO",
                metrics={
                    "drivers_total": drivers_total,
                    "drivers_fte": drivers_fte,
                    "drivers_pt": drivers_pt,
                    "total_runtime_s": round(result.total_runtime_s, 2),
                    "u_sum": kpi.get("u_sum", 0),
                    "core_pt_share_hours": kpi.get("core_pt_share_hours", 0)
                },
                context={
                    "status": "COMPLETED",
                    "reason_codes": sorted(result.reason_codes) if result.reason_codes else [],
                    "path": result.parameters_used.path.value if result.parameters_used else None
                }
            )

        except Exception as e:
            logger.exception(f"Run {ctx.run_id} failed")
            ctx.status = RunStatus.FAILED
            ctx.error = str(e)
            ctx.emit_progress(
                event_type=EventType.ERROR.value,
                message=f"Optimization failed: {str(e)[:200]}",
                level="ERROR",
                metrics={},
                context={"error_code": "INTERNAL_ERROR", "error_detail": str(e)[:500]}
            )
        
        finally:
            # Clean up JSONL file handle
            ctx.close()


# Global instance
run_manager = RunManager()

"""
SHIFT OPTIMIZER - Run Manager v2
=================================
Manages async solver runs, event streaming, and state persistence for v2.0 API.
Implements: Rate limiting, heartbeat, deterministic input sorting, config tracking, cleanup.
"""

import json
import uuid
import time
import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field

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


def _compute_drivers_total(result: PortfolioResult) -> int:
    """Compute drivers_total with safe fallback and observability."""
    if result.solution and result.solution.kpi:
        drivers_fte = result.solution.kpi.get("drivers_fte", 0)
        drivers_pt = result.solution.kpi.get("drivers_pt", 0)
        if drivers_fte + drivers_pt > 0:
            return drivers_fte + drivers_pt

    assignments = result.solution.assignments if result.solution else []
    if assignments:
        unique_driver_ids = {
            getattr(assignment, "driver_id", None)
            for assignment in assignments
        }
        unique_driver_ids.discard(None)
        drivers_total = len(unique_driver_ids)
        logger.warning(
            "drivers_total fallback used (unique_driver_ids=%s, assignments=%s)",
            drivers_total,
            len(assignments),
        )
        return drivers_total

    logger.warning("drivers_total fallback used (no assignments)")
    return 0


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


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
    
    def add_event(self, event_type: str, payload: dict, level: str = "INFO", phase: str = None):
        """Thread-safe event append with ring buffer."""
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
                # Adjust seq numbers would be complex; we keep seq as absolute
                
            self.events.append(event)
            
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
            # Since we use ring buffer, seq is absolute but list index may differ
            return [e for e in self.events if e["seq"] >= start_seq]


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
        """Blocking execution wrapper with structured events."""
        ctx.status = RunStatus.RUNNING
        
        # run_started event with config snapshot
        started_payload = {
            "seed": ctx.config.seed,
            "time_budget": time_budget,
            "budget_slices": ctx.budget_slices,
            "input_summary": ctx.input_summary
        }
        if ctx.config_snapshot:
            started_payload["config_effective_hash"] = ctx.config_snapshot.config_effective_hash
            started_payload["overrides_applied"] = ctx.config_snapshot.overrides_applied
            started_payload["overrides_rejected"] = ctx.config_snapshot.overrides_rejected
            
        ctx.add_event("run_started", started_payload)

        # Track current phase for log attribution
        current_phase = [None]  # Mutable container for closure

        # Log listener with rate limiting
        def log_fn(msg: str):
            # Detect phase from log content (case-insensitive)
            phase = current_phase[0]
            normalized = msg.upper()
            if "PHASE 1" in normalized or "PHASE 3" in normalized or "BUILD" in normalized:
                phase = "PHASE1_CAPACITY"
                current_phase[0] = phase
            elif "PHASE 2" in normalized or "PHASE 4" in normalized or "ASSIGN" in normalized:
                phase = "PHASE2_ASSIGNMENT"
                current_phase[0] = phase
            elif normalized.startswith("LNS ") or normalized.startswith("LNS:"):
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
                log_fn=log_fn
            )
            
            ctx.result = result
            ctx.status = RunStatus.COMPLETED
            
            # run_completed event - using PortfolioResult attributes directly
            # Note: PortfolioResult has reason_codes directly, not via run_report
            solution_sig = ""
            if hasattr(result.solution, 'kpi') and result.solution.kpi:
                # Build signature from solution KPIs
                kpi = result.solution.kpi
                solution_sig = f"{kpi.get('solver_arch', 'unknown')}_{result.parameters_used.path.value}_{ctx.config.seed}"
            
            completed_payload = {
                "status": "COMPLETED",
                "solution_signature": solution_sig,
                "reason_codes": sorted(result.reason_codes) if result.reason_codes else [],
                "total_runtime_s": result.total_runtime_s,
                # FIX: Compute drivers_total correctly from FTE + PT
                "drivers_fte": result.solution.kpi.get("drivers_fte", 0) if result.solution.kpi else 0,
                "drivers_pt": result.solution.kpi.get("drivers_pt", 0) if result.solution.kpi else 0,
                "drivers_total": _compute_drivers_total(result),
            }
            ctx.add_event("run_completed", completed_payload)

        except Exception as e:
            logger.exception(f"Run {ctx.run_id} failed")
            ctx.status = RunStatus.FAILED
            ctx.error = str(e)
            ctx.add_event("error", {"msg": str(e), "code": "INTERNAL_ERROR"}, level="ERROR")


# Global instance
run_manager = RunManager()

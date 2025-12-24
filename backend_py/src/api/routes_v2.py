"""
SHIFT OPTIMIZER - API Routes v2
================================
Asynchronous run management, SSE streaming, and config endpoints.
Implements: Config validation, SSE resume with heartbeat, deterministic ordering.
"""

import json
import asyncio
import time
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from src.services.forecast_solver_v4 import ConfigV4
from src.api.schemas import (
    RunCreateRequest,
    RunCreateResponse,
    RunStatusResponse,
    RunLinks,
    ConfigSchemaResponse,
    ConfigGroupSchema,
    ConfigFieldSchema,
    ConfigOverrides,
    ScheduleResponse,
    ValidationOutput,
    StatsOutput,
    AssignmentOutput,
    UnassignedTourOutput,
    BlockOutput,
    TourOutput
)
from src.api.run_manager import run_manager, RunStatus, ConfigSnapshot, HEARTBEAT_INTERVAL_SEC
from src.api.config_validator import validate_and_apply_overrides, TUNABLE_FIELDS, LOCKED_FIELDS
from src.api.routes import (
    tour_input_to_domain, 
    driver_input_to_domain, 
    parse_date,
    tour_to_output
)

router_v2 = APIRouter()


# =============================================================================
# METRICS START
# =============================================================================

@router_v2.get("/metrics")
async def get_metrics():
    """Expose Prometheus metrics for scraping."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# =============================================================================
# CONFIG SCHEMA
# =============================================================================

@router_v2.get("/config-schema", response_model=ConfigSchemaResponse)
async def get_config_schema():
    """Get configuration UI schema/metadata."""
    
    # Build groups from TUNABLE_FIELDS and LOCKED_FIELDS
    feature_flags = []
    determinism_fields = []
    tuning_fields = []
    
    # Feature flags
    for key in ["enable_fill_to_target_greedy", "enable_bad_block_mix_rerun"]:
        if key in TUNABLE_FIELDS:
            spec = TUNABLE_FIELDS[key]
            feature_flags.append(ConfigFieldSchema(
                key=key,
                type=spec["type"],
                default=spec["default"],
                editable=True,
                description=f"v2.0 feature: {key.replace('_', ' ')}"
            ))
    
    # Locked LP-RMP
    feature_flags.append(ConfigFieldSchema(
        key="enable_lp_rmp_column_generation",
        type="bool",
        default=False,
        editable=False,
        locked_reason="Postponed to v2.1",
        description="LP-RMP Column Generation"
    ))
    
    # Determinism (locked)
    for key, spec in LOCKED_FIELDS.items():
        if key in ["num_search_workers", "use_deterministic_time"]:
            determinism_fields.append(ConfigFieldSchema(
                key=key,
                type="bool" if isinstance(spec["value"], bool) else "int",
                default=spec["value"],
                editable=False,
                locked_reason=spec["reason"],
                description=f"Locked: {key}"
            ))
    
    # Tuning fields
    for key in ["pt_ratio_threshold", "underfull_ratio_threshold", "rerun_1er_penalty_multiplier"]:
        if key in TUNABLE_FIELDS:
            spec = TUNABLE_FIELDS[key]
            tuning_fields.append(ConfigFieldSchema(
                key=key,
                type=spec["type"],
                default=spec["default"],
                editable=True,
                min=spec.get("min"),
                max=spec.get("max"),
                description=f"Tunable: {key.replace('_', ' ')}"
            ))
    
    return ConfigSchemaResponse(
        version="2.0.0",
        groups=[
            ConfigGroupSchema(id="feature_flags", label="Feature Flags (v2.0)", fields=feature_flags),
            ConfigGroupSchema(id="determinism", label="Determinism", fields=determinism_fields),
            ConfigGroupSchema(id="tuning", label="Tuning Parameters", fields=tuning_fields)
        ]
    )


# =============================================================================
# RUN MANAGEMENT
# =============================================================================

@router_v2.post("/runs", response_model=RunCreateResponse, status_code=201)
async def create_run(request: RunCreateRequest):
    """Start a new optimization run with validated config."""
    try:
        # Convert inputs
        tours = [tour_input_to_domain(t) for t in request.tours]
        drivers = [driver_input_to_domain(d) for d in request.drivers]
        week_start = parse_date(request.week_start)
        
        # Validate and apply config overrides
        # Use model_dump for Pydantic v2 to capture extra fields from ConfigDict(extra='allow')
        overrides = request.run.config_overrides.model_dump(exclude_unset=True)
        validation_result = validate_and_apply_overrides(
            base_config=ConfigV4(),
            overrides=overrides,
            seed=request.run.seed
        )
        
        # Create config snapshot for audit
        config_snapshot = ConfigSnapshot(
            config_effective_hash=validation_result.config_effective_hash,
            config_effective_dict=validation_result.config_effective._asdict(),
            overrides_applied=validation_result.overrides_applied,
            overrides_rejected=validation_result.overrides_rejected,
            overrides_clamped=validation_result.overrides_clamped,
            reason_codes=validation_result.reason_codes
        )
        
        # Create run
        run_id = run_manager.create_run(
            tours=tours,
            drivers=drivers,
            config=validation_result.config_effective,
            week_start=week_start,
            time_budget=request.run.time_budget_seconds,
            config_snapshot=config_snapshot
        )
        
        return RunCreateResponse(
            run_id=run_id,
            status="QUEUED",
            events_url=f"/api/v1/runs/{run_id}/events",
            run_url=f"/api/v1/runs/{run_id}"
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@router_v2.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run_status(run_id: str):
    """Get run status and metadata including config snapshot."""
    ctx = run_manager.get_run(run_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Run not found")
        
    # Budget info
    budget_info = {
        "total": ctx.time_budget,
        "slices": ctx.budget_slices,
        "status": "within_limits"
    }
    
    # Check for budget overrun in events
    if any("BUDGET_OVERRUN" in str(e.get("payload", {})) for e in ctx.events):
        budget_info["status"] = "overrun"
        
    # Add config snapshot info
    if ctx.config_snapshot:
        budget_info["config_hash"] = ctx.config_snapshot.config_effective_hash
        budget_info["overrides_rejected"] = ctx.config_snapshot.overrides_rejected

    return RunStatusResponse(
        run_id=run_id,
        status=ctx.status.value,
        phase=ctx.events[-1].get("phase") if ctx.events else None,
        budget=budget_info,
        links=RunLinks(
            events=f"/api/v1/runs/{run_id}/events",
            report=f"/api/v1/runs/{run_id}/report",
            plan=f"/api/v1/runs/{run_id}/plan",
            canonical_report=f"/api/v1/runs/{run_id}/report/canonical",
            cancel=f"/api/v1/runs/{run_id}/cancel"
        ),
        created_at=ctx.created_at.isoformat()
    )


@router_v2.get("/runs/{run_id}/events")
async def stream_run_events(run_id: str, request: Request):
    """
    Stream run events (SSE) with resume support and heartbeat.
    
    Supports:
    - Last-Event-ID header for resume
    - Heartbeat every 5 seconds if no events
    - Ring buffer replay
    """
    ctx = run_manager.get_run(run_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Run not found")
        
    # Support Last-Event-ID for resume
    last_id = request.headers.get("last-event-id")
    start_seq = int(last_id) + 1 if last_id else 0
    
    async def event_generator():
        current_seq = start_seq
        last_send_time = time.time()
        
        # Check if we need to send a snapshot (if resuming from old seq)
        events = ctx.get_events_from(start_seq)
        if events and events[0]["seq"] > start_seq:
            # Some events were lost (ring buffer rolled over)
            snapshot_event = {
                "run_id": ctx.run_id,
                "seq": -1,  # Special marker
                "ts": ctx.created_at.isoformat(),
                "event": "run_snapshot",
                "level": "INFO",
                "phase": None,
                "payload": {
                    "warning": "Some events were dropped (ring buffer overflow)",
                    "oldest_available_seq": events[0]["seq"] if events else 0,
                    "status": ctx.status.value
                }
            }
            yield f"id: -1\nevent: run_snapshot\ndata: {json.dumps(snapshot_event)}\n\n"
        
        while True:
            # Check disconnection
            if await request.is_disconnected():
                break
                
            # Get new events
            events_to_send = ctx.get_events_from(current_seq)
            
            if events_to_send:
                for event in events_to_send:
                    yield f"id: {event['seq']}\nevent: {event['event']}\ndata: {json.dumps(event)}\n\n"
                    current_seq = event["seq"] + 1
                last_send_time = time.time()
            else:
                # Send heartbeat if idle
                if time.time() - last_send_time >= HEARTBEAT_INTERVAL_SEC:
                    heartbeat = {
                        "run_id": ctx.run_id,
                        "event": "heartbeat",
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "payload": {"status": ctx.status.value}
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"
                    last_send_time = time.time()
            
            # Exit if run finished and we sent everything
            if ctx.status in [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED]:
                remaining = ctx.get_events_from(current_seq)
                if not remaining:
                    break
            
            await asyncio.sleep(0.1)
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router_v2.get("/runs/{run_id}/report")
async def get_run_report(run_id: str):
    """Get full JSON run report including config snapshot.
    
    Returns config snapshot even for FAILED runs to show overrides_rejected.
    """
    ctx = run_manager.get_run(run_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # Build base response with config snapshot (even for FAILED runs)
    response = {
        "run_id": run_id,
        "status": ctx.status.value if hasattr(ctx.status, 'value') else str(ctx.status),
    }
    
    # Always include config snapshot if available (critical for debugging FAILED runs)
    if ctx.config_snapshot:
        response["config"] = {
            "effective_hash": ctx.config_snapshot.config_effective_hash,
            "overrides_applied": ctx.config_snapshot.overrides_applied,
            "overrides_rejected": ctx.config_snapshot.overrides_rejected,
            "overrides_clamped": ctx.config_snapshot.overrides_clamped
        }
    
    # If result is not available (FAILED or still running), return partial report
    if not ctx.result:
        response["input_summary"] = ctx.input_summary if hasattr(ctx, 'input_summary') else {}
        response["error"] = "Result not available (run may have FAILED or is still running)"
        return response
    
    result = ctx.result  # PortfolioResult
    
    # Build solution signature from KPIs
    solution_sig = ""
    if hasattr(result.solution, 'kpi') and result.solution.kpi:
        kpi = result.solution.kpi
        solution_sig = f"{kpi.get('solver_arch', 'unknown')}_{result.parameters_used.path.value}_{ctx.config.seed}"
    
    # Build full response from PortfolioResult attributes
    response.update({
        "input_summary": ctx.input_summary,
        "features": {
            "n_tours": result.features.n_tours,
            "peakiness_index": result.features.peakiness_index,
            "pt_pressure_proxy": result.features.pt_pressure_proxy,
            "lower_bound_drivers": result.features.lower_bound_drivers,
        } if result.features else {},
        "path": {
            "initial": result.initial_path.value,
            "final": result.final_path.value,
            "fallback_used": result.fallback_used,
            "fallback_count": result.fallback_count,
        },
        "timing": {
            "profiling_s": round(result.profiling_time_s, 3),
            "phase1_s": round(result.phase1_time_s, 3),
            "phase2_s": round(result.phase2_time_s, 3),
            "lns_s": round(result.lns_time_s, 3),
            "total_s": round(result.total_runtime_s, 3)
        },
        "reason_codes": sorted(result.reason_codes) if result.reason_codes else [],
        "solution_signature": solution_sig,
        "result_summary": {
            "status": result.solution.status if result.solution else "UNKNOWN",
            "drivers_total": result.solution.kpi.get("drivers_total", 0) if result.solution and result.solution.kpi else 0,
            "gap_to_lb": result.gap_to_lb,
            "early_stopped": result.early_stopped,
            "early_stop_reason": result.early_stop_reason,
        },
        "kpi": result.solution.kpi if result.solution and result.solution.kpi else {},
    })
    
    return response


@router_v2.get("/runs/{run_id}/report/canonical")
async def get_run_report_canonical(run_id: str):
    """Get canonical JSON run report (stable, no timestamps)."""
    ctx = run_manager.get_run(run_id)
    if not ctx or not ctx.result:
        raise HTTPException(status_code=404, detail="Run report not available")
    
    result = ctx.result
    
    # Build canonical report from PortfolioResult (no timestamps)
    canonical = {
        "path": result.final_path.value,
        "reason_codes": sorted(result.reason_codes) if result.reason_codes else [],
        "timing": {
            "total_s": round(result.total_runtime_s, 1),
        },
        "result": {
            "status": result.solution.status if result.solution else "UNKNOWN",
            "gap_to_lb": round(result.gap_to_lb, 4),
        }
    }
    
    import json
    json_str = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    return Response(content=json_str, media_type="application/json")


@router_v2.get("/runs/{run_id}/plan", response_model=ScheduleResponse)
async def get_run_plan(run_id: str):
    """Get final schedule/plan with deterministic ordering."""
    ctx = run_manager.get_run(run_id)
    if not ctx or not ctx.result:
        raise HTTPException(status_code=404, detail="Plan not available")
    
    result = ctx.result  # PortfolioResult
    solution = result.solution  # SolveResultV4
    
    if not solution:
        raise HTTPException(status_code=404, detail="Solution not available")
    
    # Convert SolveResultV4.assignments (DriverAssignment) to API output format
    output_assignments = []
    
    # Sort deterministically: (driver_type, driver_id)
    sorted_driver_assignments = sorted(
        solution.assignments,
        key=lambda a: (a.driver_type, a.driver_id)
    )
    
    for driver_asgn in sorted_driver_assignments:
        # Each DriverAssignment has blocks - iterate and create AssignmentOutput per block
        sorted_blocks = sorted(
            driver_asgn.blocks,
            key=lambda b: (b.day.value, b.first_start.hour if b.first_start else 0, b.id)
        )
        
        for block in sorted_blocks:
            # Sort tours within block
            sorted_tours = sorted(
                block.tours,
                key=lambda t: (t.start_time.hour, t.start_time.minute, t.id)
            )
            tours_output = [tour_to_output(t) for t in sorted_tours]
            
            # Determine block_type from block.block_type or len(tours)
            block_type_str = "single"
            if hasattr(block, 'block_type') and block.block_type:
                block_type_str = block.block_type.value
            elif len(block.tours) == 2:
                block_type_str = "double"
            elif len(block.tours) == 3:
                block_type_str = "triple"
            
            # Determine pause_zone with explicit default if missing
            p_zone = "REGULAR"
            if hasattr(block, "pause_zone"):
                # Handle enum or string
                val = block.pause_zone
                if hasattr(val, "value"):
                    p_zone = val.value
                else:
                    p_zone = str(val)
            
            output_assignments.append(AssignmentOutput(
                driver_id=driver_asgn.driver_id,
                driver_name=f"{driver_asgn.driver_type} {driver_asgn.driver_id}",
                day=block.day.value,
                block=BlockOutput(
                    id=block.id,
                    day=block.day.value,
                    block_type=block_type_str,
                    tours=tours_output,
                    driver_id=driver_asgn.driver_id,
                    total_work_hours=block.total_work_hours,
                    span_hours=block.span_hours,
                    pause_zone=p_zone
                )
            ))
    
    # Build stats from solution.kpi
    kpi = solution.kpi or {}
    
    # Count ACTUAL tours assigned (sum of tours across all blocks)
    total_tours_assigned_actual = sum(
        len(a.block.tours) for a in output_assignments
    )
    
    # Get input tour count from context
    tours_value = ctx.input_summary.get("tours", 0) if hasattr(ctx, 'input_summary') else 0
    total_tours_input = tours_value if isinstance(tours_value, int) else len(tours_value) if tours_value else total_tours_assigned_actual
    
    # Calculate total drivers from KPI (correct keys from portfolio_controller)
    drivers_fte = kpi.get("drivers_fte", 0)
    drivers_pt = kpi.get("drivers_pt", 0)
    total_drivers = drivers_fte + drivers_pt
    
    # Calculate assignment rate based on actual tours
    assignment_rate = total_tours_assigned_actual / total_tours_input if total_tours_input > 0 else 1.0
    
    stats = StatsOutput(
        total_drivers=total_drivers,
        total_tours_input=total_tours_input,
        total_tours_assigned=total_tours_assigned_actual,  # FIXED: actual tour count
        total_tours_unassigned=max(0, total_tours_input - total_tours_assigned_actual),
        block_counts={
            "1er": kpi.get("blocks_1er", 0),
            "2er": kpi.get("blocks_2er", 0),
            "3er": kpi.get("blocks_3er", 0),
        },
        assignment_rate=assignment_rate,
        average_driver_utilization=kpi.get("fte_hours_avg", 0.0) / 53.0 if kpi.get("fte_hours_avg") else 0.0,
        average_work_hours=kpi.get("fte_hours_avg", 0.0),
        # Driver metrics (Patch 2 - Reporting Sync)
        drivers_fte=drivers_fte,
        drivers_pt=drivers_pt,
        total_hours=kpi.get("total_hours"),
        fte_hours_avg=kpi.get("fte_hours_avg"),
        # Packability Diagnostics
        forced_1er_rate=kpi.get("forced_1er_rate"),
        forced_1er_count=kpi.get("forced_1er_count"),
        missed_3er_opps_count=kpi.get("missed_3er_opps_count"),
        missed_2er_opps_count=kpi.get("missed_2er_opps_count"),
        missed_multi_opps_count=kpi.get("missed_multi_opps_count"),
        # Output Profile Info (FROM KPI, not ctx.config)
        output_profile=kpi.get("output_profile"),
        gap_3er_min_minutes=kpi.get("gap_3er_min_minutes"),
        # Tour Share Metrics (computed from block counts)
        tour_share_1er=kpi.get("blocks_1er", 0) / total_tours_assigned_actual if total_tours_assigned_actual > 0 else None,
        tour_share_2er=(kpi.get("blocks_2er", 0) * 2) / total_tours_assigned_actual if total_tours_assigned_actual > 0 else None,
        tour_share_3er=(kpi.get("blocks_3er", 0) * 3) / total_tours_assigned_actual if total_tours_assigned_actual > 0 else None,
        # BEST_BALANCED two-pass metrics (FROM KPI, not block_stats)
        D_min=kpi.get("D_min"),
        driver_cap=kpi.get("driver_cap"),
        day_spread=kpi.get("day_spread"),
        # Two-pass execution proof fields
        twopass_executed=kpi.get("twopass_executed"),
        pass1_time_s=kpi.get("pass1_time_s"),
        pass2_time_s=kpi.get("pass2_time_s"),
        drivers_total_pass1=kpi.get("drivers_total_pass1"),
        drivers_total_pass2=kpi.get("drivers_total_pass2"),
    )
    
    validation = ValidationOutput(
        is_valid=solution.status in ["OPTIMAL", "FEASIBLE", "COMPLETE", "COMPLETED", "OK", "HARD_OK"],
        hard_violations=[],
        warnings=[]
    )
    
    # Patch 3: Build unassigned_tours from solution.missing_tours
    unassigned_output = []
    if hasattr(solution, 'missing_tours') and solution.missing_tours:
        # Create a lookup for tours by ID
        tour_lookup = {t.id: t for t in ctx.tours} if hasattr(ctx, 'tours') else {}
        
        for tid in solution.missing_tours:
            tour = tour_lookup.get(tid)
            if tour:
                unassigned_output.append(UnassignedTourOutput(
                    tour=tour_to_output(tour),
                    reason_codes=["NO_BLOCK_CANDIDATES"],
                    details="Kein valider Block unter Pausenregeln gefunden."
                ))
            else:
                # Tour not in context - create minimal output
                unassigned_output.append(UnassignedTourOutput(
                    tour=TourOutput(
                        id=tid,
                        day="Unknown",
                        start_time="00:00",
                        end_time="00:00",
                        duration_hours=0.0
                    ),
                    reason_codes=["NO_BLOCK_CANDIDATES", "TOUR_NOT_FOUND"],
                    details=f"Tour {tid} konnte nicht zugeordnet werden."
                ))
    
    return ScheduleResponse(
        id=run_id,
        week_start=ctx.input_summary.get("week_start", "2024-01-01") if hasattr(ctx, 'input_summary') else "2024-01-01",
        assignments=output_assignments,
        unassigned_tours=unassigned_output,  # Patch 3: From solution.missing_tours
        validation=validation,
        stats=stats,
        version="4.0",
        solver_type="portfolio_v4",
        schema_version="2.0"
    )


@router_v2.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a running optimization."""
    success = run_manager.cancel_run(run_id)
    if not success:
        ctx = run_manager.get_run(run_id)
        if not ctx:
            raise HTTPException(status_code=404, detail="Run not found")
        return {"status": ctx.status.value, "message": "Run already finished"}
    return {"status": "CANCELLED"}


@router_v2.get("/runs")
async def list_runs(limit: int = 50, status: str = None):
    """List recent runs."""
    runs = run_manager.list_runs(limit=limit, status=status)
    return {"runs": runs, "count": len(runs)}

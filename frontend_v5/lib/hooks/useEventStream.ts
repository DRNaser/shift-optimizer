"use client";

import { useState, useEffect, useCallback, useRef } from "react";

// =============================================================================
// TYPES - Match backend ProgressEvent schema
// =============================================================================

export interface ProgressEvent {
    ts: string;
    run_id: string;
    level: "INFO" | "WARN" | "ERROR";
    event_type: string;
    event: string; // SSE event type (same as event_type)
    phase?: string;
    step?: string;
    message: string;
    elapsed_s: number;
    metrics?: Record<string, number | string>;
    context?: Record<string, any>;
    seq: number;
}

export interface ProgressMetrics {
    drivers_total?: number;
    drivers_fte?: number;
    drivers_pt?: number;
    u_sum?: number;
    core_pt_share_hours?: number;
    pool_total?: number;
    round_idx?: number;
    total_runtime_s?: number;
    tours_count?: number;
    time_budget_s?: number;
}

export interface EventStreamState {
    connected: boolean;
    events: ProgressEvent[];
    lastEvent: ProgressEvent | null;
    currentPhase: string | null;
    currentStep: string | null;
    metrics: ProgressMetrics;
    error: string | null;
}

// =============================================================================
// HOOK
// =============================================================================

export function useEventStream(runId: string | null) {
    const [state, setState] = useState<EventStreamState>({
        connected: false,
        events: [],
        lastEvent: null,
        currentPhase: null,
        currentStep: null,
        metrics: {},
        error: null,
    });

    const eventSourceRef = useRef<EventSource | null>(null);
    const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

    const connect = useCallback(() => {
        if (!runId) return;

        // Clean up existing connection
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
        }

        const url = `/api/v1/runs/${runId}/events`;
        console.log(`[SSE] Connecting to ${url}`);

        const eventSource = new EventSource(url);
        eventSourceRef.current = eventSource;

        eventSource.onopen = () => {
            console.log("[SSE] Connected");
            setState(prev => ({ ...prev, connected: true, error: null }));
        };

        eventSource.onmessage = (event) => {
            try {
                const data: ProgressEvent = JSON.parse(event.data);

                setState(prev => {
                    // Build updated metrics from event
                    const newMetrics = { ...prev.metrics };
                    if (data.metrics) {
                        Object.assign(newMetrics, data.metrics);
                    }

                    // Update phase/step if present
                    const newPhase = data.phase || prev.currentPhase;
                    const newStep = data.step || prev.currentStep;

                    // Add event to list (cap at 500)
                    const newEvents = [...prev.events, data].slice(-500);

                    return {
                        ...prev,
                        events: newEvents,
                        lastEvent: data,
                        currentPhase: newPhase,
                        currentStep: newStep,
                        metrics: newMetrics,
                    };
                });
            } catch (e) {
                console.warn("[SSE] Failed to parse event:", e);
            }
        };

        // Handle specific event types
        eventSource.addEventListener("run_started", (event) => {
            const data = JSON.parse((event as MessageEvent).data);
            console.log("[SSE] Run started:", data);
        });

        eventSource.addEventListener("run_completed", (event) => {
            const data = JSON.parse((event as MessageEvent).data);
            console.log("[SSE] Run completed:", data);
            // Close connection on completion
            eventSource.close();
            setState(prev => ({ ...prev, connected: false }));
        });

        eventSource.addEventListener("heartbeat", (event) => {
            // Heartbeat - just update connection status
            setState(prev => ({ ...prev, connected: true }));
        });

        eventSource.onerror = (e) => {
            console.error("[SSE] Error:", e);
            setState(prev => ({ ...prev, connected: false, error: "Connection lost" }));
            eventSource.close();

            // Attempt reconnect after 3 seconds
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
            reconnectTimeoutRef.current = setTimeout(() => {
                console.log("[SSE] Attempting reconnect...");
                connect();
            }, 3000);
        };
    }, [runId]);

    // Connect when runId changes
    useEffect(() => {
        if (runId) {
            connect();
        }

        return () => {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
        };
    }, [runId, connect]);

    // Manual disconnect
    const disconnect = useCallback(() => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
        }
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
        }
        setState(prev => ({ ...prev, connected: false }));
    }, []);

    // Clear events
    const clearEvents = useCallback(() => {
        setState(prev => ({ ...prev, events: [] }));
    }, []);

    return {
        ...state,
        connect,
        disconnect,
        clearEvents,
    };
}

// =============================================================================
// HELPER: Format elapsed time
// =============================================================================

export function formatElapsed(seconds: number): string {
    if (seconds < 60) {
        return `${seconds.toFixed(1)}s`;
    }
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs.toFixed(0)}s`;
}

// =============================================================================
// HELPER: Get phase display name
// =============================================================================

export function getPhaseDisplayName(phase: string | null): string {
    if (!phase) return "Initializing";

    const phaseNames: Record<string, string> = {
        "phase0_block_build": "Block Building",
        "phase1_capacity": "Capacity Planning",
        "phase2_set_partition": "Set Partitioning",
        "post_repair": "Repair & Consolidation",
        "export": "Exporting Results",
        "quality_gate": "Quality Gate",
    };

    return phaseNames[phase] || phase;
}

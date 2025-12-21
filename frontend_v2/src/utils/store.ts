/**
 * Global Store using Zustand
 */
import { create } from 'zustand';
import type { SSEEvent, RunStatus, RunReport, PlanResponse } from './api';

const MAX_EVENTS = 2000;

interface RunState {
    // Current run
    currentRunId: string | null;
    runStatus: RunStatus | null;

    // Events (ring buffer)
    events: SSEEvent[];

    // Metrics
    currentPhase: string | null;
    budgetSlices: Record<string, number> | null;
    reasonCodes: string[];

    // Results
    report: RunReport | null;
    plan: PlanResponse | null;

    // Connection state
    sseConnected: boolean;
    lastHeartbeat: Date | null;

    // Actions
    setCurrentRunId: (runId: string | null) => void;
    setRunStatus: (status: RunStatus | null) => void;
    addEvent: (event: SSEEvent) => void;
    addEvents: (events: SSEEvent[]) => void;
    replaceEvents: (events: SSEEvent[]) => void;
    setReport: (report: RunReport | null) => void;
    setPlan: (plan: PlanResponse | null) => void;
    setSseConnected: (connected: boolean) => void;
    setLastHeartbeat: (time: Date) => void;
    reset: () => void;
}

export const useRunStore = create<RunState>((set, get) => ({
    currentRunId: null,
    runStatus: null,
    events: [],
    currentPhase: null,
    budgetSlices: null,
    reasonCodes: [],
    report: null,
    plan: null,
    sseConnected: false,
    lastHeartbeat: null,

    setCurrentRunId: (runId) => set({ currentRunId: runId }),

    setRunStatus: (status) => set({
        runStatus: status,
        currentPhase: status?.phase ?? null,
        budgetSlices: status?.budget?.slices ?? null
    }),

    addEvent: (event) => set((state) => {
        // Process event for metrics
        let updates: Partial<RunState> = {};

        if (event.event === 'run_started' && event.payload.budget_slices) {
            updates.budgetSlices = event.payload.budget_slices;
        }
        if (event.phase) {
            updates.currentPhase = event.phase;
        }
        if (event.event === 'heartbeat') {
            updates.lastHeartbeat = new Date();
        }
        if (event.payload.reason_codes) {
            updates.reasonCodes = Array.from(new Set([...state.reasonCodes, ...event.payload.reason_codes]));
        }

        // Ring buffer
        const newEvents = [...state.events, event];
        if (newEvents.length > MAX_EVENTS) {
            newEvents.shift();
        }

        return { ...updates, events: newEvents };
    }),

    addEvents: (events) => set((state) => {
        const newEvents = [...state.events, ...events].slice(-MAX_EVENTS);
        return { events: newEvents };
    }),

    replaceEvents: (events) => set({
        events: events.slice(-MAX_EVENTS),
        reasonCodes: []
    }),

    setReport: (report) => set({
        report,
        reasonCodes: report?.reason_codes ?? []
    }),

    setPlan: (plan) => set({ plan }),

    setSseConnected: (connected) => set({ sseConnected: connected }),

    setLastHeartbeat: (time) => set({ lastHeartbeat: time }),

    reset: () => set({
        currentRunId: null,
        runStatus: null,
        events: [],
        currentPhase: null,
        budgetSlices: null,
        reasonCodes: [],
        report: null,
        plan: null,
        sseConnected: false,
        lastHeartbeat: null
    })
}));

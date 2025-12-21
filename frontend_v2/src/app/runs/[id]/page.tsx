'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import {
    getRunStatus,
    cancelRun,
    createEventSource,
    type RunStatus as RunStatusType,
    type SSEEvent
} from '@/utils/api';
import { useRunStore } from '@/utils/store';

export default function LiveRunPage() {
    const params = useParams();
    const router = useRouter();
    const runId = params.id as string;

    const {
        events,
        currentPhase,
        budgetSlices,
        reasonCodes,
        sseConnected,
        lastHeartbeat,
        runStatus,
        setRunStatus,
        addEvent,
        replaceEvents,
        setSseConnected,
        setLastHeartbeat,
        reset
    } = useRunStore();

    const [error, setError] = useState<string | null>(null);
    const [cancelling, setCancelling] = useState(false);
    const [autoScroll, setAutoScroll] = useState(true);
    const [filterLevel, setFilterLevel] = useState<string>('ALL');

    const eventSourceRef = useRef<EventSource | null>(null);
    const logContainerRef = useRef<HTMLDivElement>(null);
    const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

    // Poll status
    const pollStatus = useCallback(async () => {
        try {
            const status = await getRunStatus(runId);
            setRunStatus(status);

            // If finished, navigate to results
            if (status.status === 'COMPLETED') {
                setTimeout(() => router.push(`/runs/${runId}/results`), 1000);
            }
        } catch (e: any) {
            console.error('Status poll error:', e);
        }
    }, [runId, setRunStatus, router]);

    // Setup SSE and polling
    useEffect(() => {
        reset();

        // Start status polling
        pollStatus();
        pollIntervalRef.current = setInterval(pollStatus, 2000);

        // Start SSE
        const es = createEventSource(
            runId,
            (event) => {
                // Handle snapshot (replace all events)
                if (event.event === 'run_snapshot') {
                    replaceEvents([]);
                }

                addEvent(event);

                // Handle heartbeat
                if (event.event === 'heartbeat') {
                    setLastHeartbeat(new Date());
                }

                // Handle completion events
                if (['run_completed', 'run_failed', 'run_cancelled'].includes(event.event)) {
                    pollStatus();
                }
            },
            (err) => {
                console.error('SSE error:', err);
                setSseConnected(false);

                // Reconnect after delay
                setTimeout(() => {
                    if (eventSourceRef.current) {
                        eventSourceRef.current.close();
                    }
                    eventSourceRef.current = createEventSource(
                        runId,
                        (event) => addEvent(event),
                        () => setSseConnected(false)
                    );
                    setSseConnected(true);
                }, 3000);
            }
        );

        eventSourceRef.current = es;
        setSseConnected(true);

        return () => {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
            }
            if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current);
            }
        };
    }, [runId]);

    // Auto-scroll logs
    useEffect(() => {
        if (autoScroll && logContainerRef.current) {
            logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
        }
    }, [events, autoScroll]);

    // Handle cancel
    const handleCancel = async () => {
        setCancelling(true);
        try {
            await cancelRun(runId);
            await pollStatus();
        } catch (e: any) {
            setError(e.message);
        } finally {
            setCancelling(false);
        }
    };

    // Filter events
    const filteredEvents = events.filter(e => {
        if (filterLevel === 'ALL') return true;
        return e.level === filterLevel;
    });

    // Format time
    const formatTime = (ts: string) => {
        try {
            return new Date(ts).toLocaleTimeString();
        } catch {
            return ts;
        }
    };

    const isFinished = runStatus?.status && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(runStatus.status);

    return (
        <div className="max-w-6xl mx-auto">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-2xl font-bold">Run: {runId}</h1>
                    <div className="flex items-center gap-4 mt-2">
                        <span className={`status-badge status-${runStatus?.status || 'QUEUED'}`}>
                            {runStatus?.status || 'Loading...'}
                        </span>
                        {currentPhase && (
                            <span className="phase-badge">{currentPhase}</span>
                        )}
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <span className={`connection-indicator ${sseConnected ? 'connected' : 'disconnected'}`} />
                            {sseConnected ? 'Connected' : 'Disconnected'}
                        </div>
                    </div>
                </div>

                <div className="flex gap-2">
                    {!isFinished && (
                        <button
                            onClick={handleCancel}
                            disabled={cancelling}
                            className="btn-destructive"
                        >
                            {cancelling ? 'Cancelling...' : 'Cancel'}
                        </button>
                    )}
                    {isFinished && runStatus?.status === 'COMPLETED' && (
                        <a href={`/runs/${runId}/results`} className="btn-primary">
                            View Results
                        </a>
                    )}
                </div>
            </div>

            {error && (
                <div className="mb-4 p-4 bg-destructive/10 text-destructive rounded-lg">{error}</div>
            )}

            {/* Budget & Metrics */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                {/* Budget */}
                <div className="card">
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">Budget</h3>
                    <div className="text-2xl font-bold">{runStatus?.budget.total || 0}s</div>
                    {budgetSlices && (
                        <div className="mt-2 space-y-1 text-xs">
                            {Object.entries(budgetSlices).map(([phase, seconds]) => (
                                <div key={phase} className="flex justify-between">
                                    <span className="text-muted-foreground">{phase}</span>
                                    <span>{typeof seconds === 'number' ? seconds.toFixed(1) : seconds}s</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Reason Codes */}
                <div className="card">
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">Reason Codes</h3>
                    {reasonCodes.length === 0 ? (
                        <span className="text-muted-foreground text-sm">None</span>
                    ) : (
                        <div className="flex flex-wrap gap-1">
                            {reasonCodes.map((code, i) => (
                                <span
                                    key={i}
                                    className={`text-xs px-2 py-0.5 rounded ${code.includes('OVERRUN') ? 'bg-destructive/10 text-destructive' :
                                        code.includes('WARN') ? 'bg-amber-100 text-amber-800' :
                                            'bg-muted text-muted-foreground'
                                        }`}
                                >
                                    {code}
                                </span>
                            ))}
                        </div>
                    )}
                </div>

                {/* Connection */}
                <div className="card">
                    <h3 className="text-sm font-medium text-muted-foreground mb-2">Connection</h3>
                    <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                            <span className="text-muted-foreground">Events received</span>
                            <span>{events.length}</span>
                        </div>
                        <div className="flex justify-between">
                            <span className="text-muted-foreground">Last heartbeat</span>
                            <span>{lastHeartbeat ? formatTime(lastHeartbeat.toISOString()) : '-'}</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* Log Console */}
            <div className="card">
                <div className="flex items-center justify-between mb-4">
                    <h3 className="text-lg font-semibold">Live Logs</h3>
                    <div className="flex items-center gap-4">
                        <select
                            value={filterLevel}
                            onChange={(e) => setFilterLevel(e.target.value)}
                            className="input h-8 w-32 text-sm"
                        >
                            <option value="ALL">All Levels</option>
                            <option value="DEBUG">Debug</option>
                            <option value="INFO">Info</option>
                            <option value="WARN">Warn</option>
                            <option value="ERROR">Error</option>
                        </select>
                        <label className="flex items-center gap-2 text-sm">
                            <input
                                type="checkbox"
                                checked={autoScroll}
                                onChange={(e) => setAutoScroll(e.target.checked)}
                            />
                            Auto-scroll
                        </label>
                    </div>
                </div>

                <div
                    ref={logContainerRef}
                    className="log-console bg-muted rounded-lg h-96 overflow-auto"
                >
                    {filteredEvents.length === 0 ? (
                        <div className="p-4 text-muted-foreground text-center">
                            Waiting for events...
                        </div>
                    ) : (
                        filteredEvents.map((event, i) => (
                            <div key={i} className={`log-entry level-${event.level}`}>
                                <span className="text-muted-foreground mr-2">[{formatTime(event.ts)}]</span>
                                <span className="text-primary/70 mr-2">{event.event}</span>
                                {event.phase && (
                                    <span className="text-amber-600 mr-2">[{event.phase}]</span>
                                )}
                                <span>
                                    {event.payload.msg || event.payload.message || JSON.stringify(event.payload)}
                                </span>
                            </div>
                        ))
                    )}
                </div>
            </div>
        </div>
    );
}

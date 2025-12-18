import { useEffect, useRef, useState, useMemo } from 'react';

interface SolverState {
    phase: 'IDLE' | 'RMP' | 'RELAXED' | 'GREEDY' | 'REPAIR' | 'DONE';
    roundCurrent: number;
    roundMax: number;
    poolSize: number;
    under: number;
    over: number;
    status: string;
}

interface LogTerminalProps {
    logs: string[];
    isConnected: boolean;
}

const MAX_VISIBLE_LINES = 500;
const STUCK_NO_LOGS_SECONDS = 15;
const STUCK_ROUND_SECONDS = 60;

export function LogTerminal({ logs, isConnected }: LogTerminalProps) {
    const contentRef = useRef<HTMLDivElement>(null);
    const [autoScroll, setAutoScroll] = useState(true);
    const [lastLogTime, setLastLogTime] = useState(Date.now());
    const [lastRoundTime, setLastRoundTime] = useState(Date.now());
    const [stuckWarning, setStuckWarning] = useState<string | null>(null);

    // Parse solver state from logs
    const solverState = useMemo<SolverState>(() => {
        const state: SolverState = {
            phase: 'IDLE',
            roundCurrent: 0,
            roundMax: 0,
            poolSize: 0,
            under: 0,
            over: 0,
            status: '',
        };

        // Scan last 100 lines for state updates
        const recentLogs = logs.slice(-100);
        for (const line of recentLogs) {
            // Phase detection
            if (line.includes('RESTRICTED MASTER PROBLEM (RMP)')) {
                state.phase = 'RMP';
            } else if (line.includes('RELAXED RMP')) {
                state.phase = 'RELAXED';
            } else if (line.includes('PHASE 2: Driver Assignment (Greedy)')) {
                state.phase = 'GREEDY';
            } else if (line.includes('POST-GREEDY REPAIR')) {
                state.phase = 'REPAIR';
            } else if (line.includes('Solver completed!')) {
                state.phase = 'DONE';
            }

            // Round detection
            const roundMatch = line.match(/--- Round (\d+)\/(\d+) ---/);
            if (roundMatch) {
                state.roundCurrent = parseInt(roundMatch[1]);
                state.roundMax = parseInt(roundMatch[2]);
            }

            // Pool size
            const poolMatch = line.match(/Pool size: (\d+)/);
            if (poolMatch) {
                state.poolSize = parseInt(poolMatch[1]);
            }

            // Under/Over
            const diagMatch = line.match(/under=(\d+), over=(\d+)/);
            if (diagMatch) {
                state.under = parseInt(diagMatch[1]);
                state.over = parseInt(diagMatch[2]);
            }

            // Status
            const statusMatch = line.match(/RMP Status: (\w+)/);
            if (statusMatch) {
                state.status = statusMatch[1];
            }
        }

        return state;
    }, [logs]);

    // Update timestamps
    useEffect(() => {
        if (logs.length > 0) {
            setLastLogTime(Date.now());
        }
    }, [logs.length]);

    useEffect(() => {
        if (solverState.roundCurrent > 0) {
            setLastRoundTime(Date.now());
        }
    }, [solverState.roundCurrent]);

    // Stuck detection
    useEffect(() => {
        const checkStuck = () => {
            const now = Date.now();
            const noLogsSince = (now - lastLogTime) / 1000;
            const roundStuckSince = (now - lastRoundTime) / 1000;

            // Pattern-based stall
            const lastLines = logs.slice(-5).join(' ');
            if (lastLines.includes('No improvement for 5 rounds') ||
                lastLines.includes('No progress for')) {
                setStuckWarning('⚠️ Solver stalled - no progress for multiple rounds. Expecting fallback.');
                return;
            }

            // No logs warning
            if (noLogsSince > STUCK_NO_LOGS_SECONDS && logs.length > 0) {
                setStuckWarning(`⚠️ No log updates for ${Math.floor(noLogsSince)}s — solver may be stuck.`);
                return;
            }

            // Round not advancing (only during RMP/RELAXED)
            if ((solverState.phase === 'RMP' || solverState.phase === 'RELAXED') &&
                roundStuckSince > STUCK_ROUND_SECONDS) {
                setStuckWarning(`⚠️ Round not advancing for ${Math.floor(roundStuckSince)}s — solver in long solve.`);
                return;
            }

            setStuckWarning(null);
        };

        const interval = setInterval(checkStuck, 1000);
        return () => clearInterval(interval);
    }, [logs, lastLogTime, lastRoundTime, solverState.phase]);

    // Auto-scroll
    useEffect(() => {
        if (autoScroll && contentRef.current) {
            contentRef.current.scrollTop = contentRef.current.scrollHeight;
        }
    }, [logs, autoScroll]);

    const getLineClass = (line: string): string => {
        const lowerLine = line.toLowerCase();
        if (lowerLine.includes('error') || lowerLine.includes('failed') || lowerLine.includes('traceback')) return 'log-line error';
        if (lowerLine.includes('✓') || lowerLine.includes('success') || lowerLine.includes('complete')) return 'log-line success';
        if (lowerLine.includes('warning') || lowerLine.includes('warn')) return 'log-line warning';
        if (lowerLine.includes('set-partitioning failed')) return 'log-line error';
        return 'log-line info';
    };

    // Only render last MAX_VISIBLE_LINES for performance
    const visibleLogs = logs.slice(-MAX_VISIBLE_LINES);

    const phaseBadgeClass = {
        'IDLE': 'badge-secondary',
        'RMP': 'badge-info',
        'RELAXED': 'badge-warning',
        'GREEDY': 'badge-primary',
        'REPAIR': 'badge-success',
        'DONE': 'badge-success',
    }[solverState.phase] || 'badge-secondary';

    const copyLogs = () => {
        navigator.clipboard.writeText(logs.join('\n'));
    };

    return (
        <div className="log-terminal">
            {/* Header with stats */}
            <div className="log-header">
                <div className="log-dot red"></div>
                <div className="log-dot yellow"></div>
                <div className={`log-dot ${isConnected ? 'green' : 'red'}`}></div>

                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginLeft: '12px' }}>
                    <span className={`badge ${phaseBadgeClass}`} style={{ fontSize: '0.7rem' }}>
                        {solverState.phase}
                    </span>
                    {solverState.roundCurrent > 0 && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                            Round {solverState.roundCurrent}/{solverState.roundMax}
                        </span>
                    )}
                    {solverState.poolSize > 0 && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                            Pool: {solverState.poolSize}
                        </span>
                    )}
                    {(solverState.under > 0 || solverState.over > 0) && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                            U:{solverState.under} O:{solverState.over}
                        </span>
                    )}
                </div>

                <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button
                        onClick={() => setAutoScroll(!autoScroll)}
                        style={{
                            background: autoScroll ? 'var(--color-success)' : 'var(--color-surface-alt)',
                            border: 'none',
                            color: 'white',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            fontSize: '0.7rem',
                            cursor: 'pointer'
                        }}
                    >
                        {autoScroll ? '⬇️ Auto' : '⏸️ Paused'}
                    </button>
                    <button
                        onClick={copyLogs}
                        style={{
                            background: 'var(--color-surface-alt)',
                            border: 'none',
                            color: 'white',
                            padding: '2px 8px',
                            borderRadius: '4px',
                            fontSize: '0.7rem',
                            cursor: 'pointer'
                        }}
                    >
                        📋
                    </button>
                    <span style={{ fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                        {logs.length} lines
                    </span>
                </div>
            </div>

            {/* Stuck warning banner */}
            {stuckWarning && (
                <div style={{
                    background: 'var(--color-warning)',
                    color: '#000',
                    padding: '8px 12px',
                    fontSize: '0.85rem',
                    fontWeight: 500,
                }}>
                    {stuckWarning}
                </div>
            )}

            {/* Log content */}
            <div
                className="log-content"
                ref={contentRef}
                onScroll={(e) => {
                    const el = e.currentTarget;
                    const atBottom = el.scrollHeight - el.scrollTop <= el.clientHeight + 50;
                    setAutoScroll(atBottom);
                }}
            >
                {logs.length === 0 ? (
                    <div className="log-line info">Waiting for solver logs...</div>
                ) : (
                    visibleLogs.map((line, i) => (
                        <div key={logs.length - MAX_VISIBLE_LINES + i} className={getLineClass(line)}>{line}</div>
                    ))
                )}
            </div>
        </div>
    );
}

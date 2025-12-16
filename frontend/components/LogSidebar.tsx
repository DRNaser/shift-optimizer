// Live Log Sidebar Component
// Displays real-time solver logs from SSE stream

import { useEffect, useRef } from 'react';
import { useLogStream, LogEntry } from '../hooks/useLogStream';

function getLogColor(level: LogEntry['level']): string {
    switch (level) {
        case 'SUCCESS': return '#22c55e';  // Green
        case 'INFO': return '#3b82f6';     // Blue
        case 'WARN': return '#f59e0b';     // Yellow
        case 'ERROR': return '#ef4444';    // Red
        default: return '#94a3b8';         // Gray
    }
}

function getLogIcon(level: LogEntry['level']): string {
    switch (level) {
        case 'SUCCESS': return '✓';
        case 'INFO': return 'ℹ';
        case 'WARN': return '⚠';
        case 'ERROR': return '✕';
        default: return '•';
    }
}

function formatTime(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString('de-DE', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    });
}

export default function LogSidebar() {
    const { logs, isConnected, clearLogs } = useLogStream();
    const logContainerRef = useRef<HTMLDivElement>(null);

    // Auto-scroll to bottom when new logs arrive
    useEffect(() => {
        if (logContainerRef.current) {
            logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
        }
    }, [logs]);

    return (
        <aside className="log-sidebar">
            {/* Header */}
            <div className="log-header">
                <div className="log-title">
                    <span className={`connection-dot ${isConnected ? 'connected' : 'disconnected'}`} />
                    <span>Live Logs</span>
                </div>
                <button onClick={clearLogs} className="clear-btn" title="Clear logs">
                    🗑
                </button>
            </div>

            {/* Log Container */}
            <div ref={logContainerRef} className="log-container">
                {logs.length === 0 ? (
                    <div className="log-empty">
                        Waiting for solver activity...
                    </div>
                ) : (
                    logs.map((log, idx) => (
                        <div
                            key={idx}
                            className="log-entry"
                            style={{ borderLeftColor: getLogColor(log.level) }}
                        >
                            <span className="log-time">{formatTime(log.ts)}</span>
                            <span
                                className="log-icon"
                                style={{ color: getLogColor(log.level) }}
                            >
                                {getLogIcon(log.level)}
                            </span>
                            <span className="log-message">{log.message}</span>
                        </div>
                    ))
                )}
            </div>

            {/* Styles */}
            <style>{`
                .log-sidebar {
                    position: fixed;
                    right: 0;
                    top: 0;
                    bottom: 0;
                    width: 320px;
                    background: linear-gradient(180deg, #1e293b 0%, #0f172a 100%);
                    border-left: 1px solid #334155;
                    display: flex;
                    flex-direction: column;
                    z-index: 100;
                    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
                    font-size: 12px;
                }

                .log-header {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    padding: 12px 16px;
                    background: #334155;
                    border-bottom: 1px solid #475569;
                }

                .log-title {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    color: #f1f5f9;
                    font-weight: 600;
                    font-size: 14px;
                }

                .connection-dot {
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    animation: pulse 2s infinite;
                }

                .connection-dot.connected {
                    background: #22c55e;
                    box-shadow: 0 0 8px #22c55e80;
                }

                .connection-dot.disconnected {
                    background: #ef4444;
                    box-shadow: 0 0 8px #ef444480;
                }

                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.5; }
                }

                .clear-btn {
                    background: transparent;
                    border: 1px solid #475569;
                    color: #94a3b8;
                    padding: 4px 8px;
                    border-radius: 4px;
                    cursor: pointer;
                    transition: all 0.2s;
                }

                .clear-btn:hover {
                    background: #475569;
                    color: #f1f5f9;
                }

                .log-container {
                    flex: 1;
                    overflow-y: auto;
                    padding: 8px;
                }

                .log-container::-webkit-scrollbar {
                    width: 6px;
                }

                .log-container::-webkit-scrollbar-track {
                    background: #1e293b;
                }

                .log-container::-webkit-scrollbar-thumb {
                    background: #475569;
                    border-radius: 3px;
                }

                .log-empty {
                    color: #64748b;
                    text-align: center;
                    padding: 40px 20px;
                    font-style: italic;
                }

                .log-entry {
                    display: flex;
                    align-items: flex-start;
                    gap: 8px;
                    padding: 6px 8px;
                    margin-bottom: 4px;
                    background: #1e293b80;
                    border-left: 3px solid;
                    border-radius: 0 4px 4px 0;
                    transition: background 0.2s;
                }

                .log-entry:hover {
                    background: #1e293b;
                }

                .log-time {
                    color: #64748b;
                    flex-shrink: 0;
                    font-size: 11px;
                }

                .log-icon {
                    flex-shrink: 0;
                    font-weight: bold;
                }

                .log-message {
                    color: #e2e8f0;
                    word-break: break-word;
                    line-height: 1.4;
                }
            `}</style>
        </aside>
    );
}

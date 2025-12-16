// Custom hook for SSE log streaming
// Connects to backend /api/v1/logs/stream and returns live logs

import { useState, useEffect, useCallback, useRef } from 'react';

export interface LogEntry {
    level: 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS';
    message: string;
    ts: number;
}

export interface UseLogStreamReturn {
    logs: LogEntry[];
    isConnected: boolean;
    clearLogs: () => void;
}

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

export function useLogStream(): UseLogStreamReturn {
    const [logs, setLogs] = useState<LogEntry[]>([]);
    const [isConnected, setIsConnected] = useState(false);
    const eventSourceRef = useRef<EventSource | null>(null);
    const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const connect = useCallback(() => {
        // Clean up existing connection
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
        }

        try {
            const es = new EventSource(`${API_BASE}/api/v1/logs/stream`);
            eventSourceRef.current = es;

            es.onopen = () => {
                setIsConnected(true);
                console.log('[LogStream] Connected');
            };

            es.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data) as LogEntry;
                    setLogs(prev => [...prev.slice(-200), data]); // Keep last 200 logs
                } catch (e) {
                    // Ignore parsing errors (e.g., keepalive messages)
                }
            };

            es.onerror = () => {
                setIsConnected(false);
                es.close();

                // Reconnect after 2 seconds
                if (reconnectTimeoutRef.current) {
                    clearTimeout(reconnectTimeoutRef.current);
                }
                reconnectTimeoutRef.current = setTimeout(() => {
                    console.log('[LogStream] Reconnecting...');
                    connect();
                }, 2000);
            };
        } catch (e) {
            console.error('[LogStream] Failed to connect:', e);
            setIsConnected(false);
        }
    }, []);

    const clearLogs = useCallback(() => {
        setLogs([]);
    }, []);

    useEffect(() => {
        connect();

        return () => {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
            }
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
        };
    }, [connect]);

    return { logs, isConnected, clearLogs };
}

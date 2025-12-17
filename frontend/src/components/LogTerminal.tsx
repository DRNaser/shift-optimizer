import { useEffect, useRef, useState } from 'react';

interface LogTerminalProps {
    logs: string[];
    isConnected: boolean;
}

export function LogTerminal({ logs, isConnected }: LogTerminalProps) {
    const contentRef = useRef<HTMLDivElement>(null);
    const [autoScroll, setAutoScroll] = useState(true);

    useEffect(() => {
        if (autoScroll && contentRef.current) {
            contentRef.current.scrollTop = contentRef.current.scrollHeight;
        }
    }, [logs, autoScroll]);

    const getLineClass = (line: string): string => {
        const lowerLine = line.toLowerCase();
        if (lowerLine.includes('error') || lowerLine.includes('failed')) return 'log-line error';
        if (lowerLine.includes('✓') || lowerLine.includes('success') || lowerLine.includes('complete')) return 'log-line success';
        if (lowerLine.includes('warning') || lowerLine.includes('warn')) return 'log-line warning';
        return 'log-line info';
    };

    return (
        <div className="log-terminal">
            <div className="log-header">
                <div className="log-dot red"></div>
                <div className="log-dot yellow"></div>
                <div className={`log-dot ${isConnected ? 'green' : 'red'}`}></div>
                <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: 'var(--color-text-muted)' }}>
                    {isConnected ? 'Connected' : 'Disconnected'}
                </span>
            </div>
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
                    logs.map((line, i) => (
                        <div key={i} className={getLineClass(line)}>{line}</div>
                    ))
                )}
            </div>
        </div>
    );
}

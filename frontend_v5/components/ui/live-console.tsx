"use client";

import { useEffect, useRef } from "react";

interface LogEntry {
    timestamp: string;
    level: "INFO" | "SOLVER" | "OK" | "ERROR" | "FINAL" | "WARN";
    message: string;
}

interface LiveConsoleProps {
    logs: LogEntry[];
    isRunning: boolean;
}

const levelColors: Record<LogEntry["level"], string> = {
    INFO: "text-slate-400",
    SOLVER: "text-blue-400",
    OK: "text-emerald-400",
    ERROR: "text-red-400",
    FINAL: "text-amber-400 font-bold",
    WARN: "text-yellow-500",
};

export function LiveConsole({ logs, isRunning }: LiveConsoleProps) {
    const scrollRef = useRef<HTMLDivElement>(null);

    // Auto-scroll to bottom on new logs
    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [logs]);

    return (
        <div className="bg-slate-950/80 backdrop-blur-sm border border-slate-800 rounded-lg overflow-hidden flex flex-col h-full">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800 bg-slate-900/50">
                <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${isRunning ? "bg-emerald-500 animate-pulse" : "bg-slate-600"}`} />
                    <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
                        Pipeline Console
                    </span>
                </div>
                <span className="text-xs text-slate-500 font-mono">
                    {logs.length} events
                </span>
            </div>

            {/* Log Area */}
            <div
                ref={scrollRef}
                className="flex-1 overflow-y-auto p-4 font-mono text-xs space-y-1 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent"
            >
                {logs.length === 0 ? (
                    <div className="text-slate-600 italic">
                        System Ready - Waiting for Input...
                    </div>
                ) : (
                    logs.map((log, i) => (
                        <div key={i} className="flex gap-2">
                            <span className="text-slate-600 shrink-0">[{log.timestamp}]</span>
                            <span className={`${levelColors[log.level]} shrink-0`}>
                                [{log.level}]
                            </span>
                            <span className="text-slate-300">{log.message}</span>
                        </div>
                    ))
                )}

                {isRunning && (
                    <div className="flex items-center gap-2 text-blue-400 animate-pulse">
                        <span className="text-slate-600">[...]</span>
                        <span>Processing...</span>
                    </div>
                )}
            </div>
        </div>
    );
}

export type { LogEntry };

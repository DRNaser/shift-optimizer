// Solver Options Panel
// Configure solver type, time limit, and other options

import React from 'react';
import { SolverType } from '../types';

interface SolverOptionsProps {
    solverType: SolverType;
    onSolverTypeChange: (type: SolverType) => void;
    timeLimit: number;
    onTimeLimitChange: (limit: number) => void;
    lnsIterations: number;
    onLnsIterationsChange: (iterations: number) => void;
    isLoading: boolean;
}

export default function SolverOptions({
    solverType,
    onSolverTypeChange,
    timeLimit,
    onTimeLimitChange,
    lnsIterations,
    onLnsIterationsChange,
    isLoading,
}: SolverOptionsProps) {
    const solverDescriptions: Record<SolverType, string> = {
        'greedy': 'Fast baseline scheduler (~10ms). Good for quick previews.',
        'cpsat': 'Optimal CP-SAT solver (~1-30s). Finds best solution.',
        'cpsat+lns': 'CP-SAT + LNS refinement (~5-60s). Highest quality.',
    };

    return (
        <div className="bg-white rounded-xl shadow-lg p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">Solver Options</h3>

            {/* Solver Type Selection */}
            <div className="mb-6">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                    Solver Type
                </label>
                <div className="grid grid-cols-3 gap-3">
                    {(['greedy', 'cpsat', 'cpsat+lns'] as SolverType[]).map((type) => (
                        <button
                            key={type}
                            onClick={() => onSolverTypeChange(type)}
                            disabled={isLoading}
                            className={`px-4 py-3 rounded-lg border-2 text-center transition-all ${solverType === type
                                    ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                                } ${isLoading ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                        >
                            <div className="font-semibold">{type.toUpperCase()}</div>
                            <div className="text-xs mt-1 opacity-75">
                                {type === 'greedy' && '⚡ Fast'}
                                {type === 'cpsat' && '🎯 Optimal'}
                                {type === 'cpsat+lns' && '🏆 Best'}
                            </div>
                        </button>
                    ))}
                </div>
                <p className="text-sm text-gray-500 mt-2">
                    {solverDescriptions[solverType]}
                </p>
            </div>

            {/* Time Limit (for CP-SAT) */}
            {(solverType === 'cpsat' || solverType === 'cpsat+lns') && (
                <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Time Limit: {timeLimit}s
                    </label>
                    <input
                        type="range"
                        min="5"
                        max="120"
                        step="5"
                        value={timeLimit}
                        onChange={(e) => onTimeLimitChange(Number(e.target.value))}
                        disabled={isLoading}
                        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                    />
                    <div className="flex justify-between text-xs text-gray-500 mt-1">
                        <span>5s</span>
                        <span>60s</span>
                        <span>120s</span>
                    </div>
                </div>
            )}

            {/* LNS Iterations (for CP-SAT+LNS) */}
            {solverType === 'cpsat+lns' && (
                <div className="mb-4">
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        LNS Iterations: {lnsIterations}
                    </label>
                    <input
                        type="range"
                        min="5"
                        max="50"
                        step="5"
                        value={lnsIterations}
                        onChange={(e) => onLnsIterationsChange(Number(e.target.value))}
                        disabled={isLoading}
                        className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                    />
                    <div className="flex justify-between text-xs text-gray-500 mt-1">
                        <span>5</span>
                        <span>25</span>
                        <span>50</span>
                    </div>
                </div>
            )}
        </div>
    );
}

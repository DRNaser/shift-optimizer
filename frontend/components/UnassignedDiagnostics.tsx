/**
 * UnassignedDiagnostics.tsx
 * =========================
 * Debug panel for understanding why tours are unassigned.
 * Shows reason codes, candidate counts, and blocking details.
 */

import React, { useState, useMemo } from 'react';
import { UnassignedTourOutput } from '../types';

interface DiagnosticDetail {
    tour_id: string;
    day: string;
    time: string;
    reason_code: string;
    candidate_blocks_total: number;
    candidate_drivers_total: number;
    top_blockers: Array<{ code: string; count: number }>;
    has_any_blocks: boolean;
    has_any_feasible_driver: boolean;
    is_globally_conflicting: boolean;
    details?: string;
}

interface Props {
    unassignedTours: UnassignedTourOutput[];
}

// Map reason codes to human-readable descriptions
const reasonDescriptions: Record<string, string> = {
    qualification_missing: 'No driver has required qualifications',
    driver_unavailable: 'No driver available on this day',
    span_exceeded: 'Block span exceeds driver limit',
    tours_per_day_exceeded: 'Too many tours for any driver',
    rest_violation: 'Would violate rest time rules',
    overlap: 'Overlaps with other tours',
    weekly_hours_exceeded: 'All drivers at weekly hour limit',
    no_block_generated: 'Could not form a valid block',
    global_infeasible: 'Conflicts with other assignments',
    driver_weekly_limit: 'All drivers at capacity',
    infeasible: 'No feasible assignment exists'
};

// Style constants
const styles = {
    container: {
        backgroundColor: '#1a1a2e',
        borderRadius: '12px',
        padding: '20px',
        marginTop: '20px',
        border: '1px solid #e94560'
    },
    header: {
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '16px'
    },
    title: {
        color: '#e94560',
        fontSize: '18px',
        fontWeight: 600,
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
    },
    filterBar: {
        display: 'flex',
        gap: '8px',
        flexWrap: 'wrap' as const,
        marginBottom: '16px'
    },
    filterChip: {
        padding: '6px 12px',
        borderRadius: '16px',
        fontSize: '12px',
        cursor: 'pointer',
        border: '1px solid #333',
        transition: 'all 0.2s'
    },
    table: {
        width: '100%',
        borderCollapse: 'collapse' as const
    },
    th: {
        textAlign: 'left' as const,
        padding: '10px 8px',
        borderBottom: '2px solid #333',
        color: '#888',
        fontSize: '12px',
        textTransform: 'uppercase' as const
    },
    td: {
        padding: '10px 8px',
        borderBottom: '1px solid #222',
        color: '#ccc',
        fontSize: '13px'
    },
    reasonBadge: {
        display: 'inline-block',
        padding: '4px 8px',
        borderRadius: '4px',
        fontSize: '11px',
        fontWeight: 500
    },
    expandRow: {
        backgroundColor: '#12121f',
        padding: '12px'
    },
    blockerList: {
        display: 'flex',
        gap: '8px',
        flexWrap: 'wrap' as const
    },
    blockerChip: {
        backgroundColor: '#2a2a4a',
        padding: '4px 8px',
        borderRadius: '4px',
        fontSize: '11px',
        color: '#aaa'
    },
    flagIcon: {
        display: 'inline-block',
        width: '16px',
        textAlign: 'center' as const,
        marginRight: '4px'
    },
    summaryGrid: {
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: '12px',
        marginBottom: '16px'
    },
    summaryCard: {
        backgroundColor: '#12121f',
        padding: '12px',
        borderRadius: '8px',
        textAlign: 'center' as const
    },
    summaryNumber: {
        fontSize: '24px',
        fontWeight: 600,
        color: '#e94560'
    },
    summaryLabel: {
        fontSize: '11px',
        color: '#888',
        textTransform: 'uppercase' as const
    }
};

// Get color for reason code
function getReasonColor(reason: string): string {
    const colors: Record<string, string> = {
        qualification_missing: '#f59e0b',
        driver_unavailable: '#8b5cf6',
        span_exceeded: '#ef4444',
        rest_violation: '#ec4899',
        weekly_hours_exceeded: '#f97316',
        no_block_generated: '#6366f1',
        global_infeasible: '#dc2626',
        driver_weekly_limit: '#f97316',
        infeasible: '#ef4444'
    };
    return colors[reason] || '#6b7280';
}

export function UnassignedDiagnostics({ unassignedTours }: Props) {
    const [selectedReason, setSelectedReason] = useState<string | null>(null);
    const [expandedTour, setExpandedTour] = useState<string | null>(null);

    // Convert unassigned tours to diagnostic format
    const diagnostics: DiagnosticDetail[] = useMemo(() => {
        return unassignedTours.map(ut => ({
            tour_id: ut.tour.id,
            day: ut.tour.day,
            time: `${ut.tour.start_time}-${ut.tour.end_time}`,
            reason_code: ut.reason_codes[0] || 'unknown',
            candidate_blocks_total: 0, // Would need API enrichment
            candidate_drivers_total: 0,
            top_blockers: [],
            has_any_blocks: true,
            has_any_feasible_driver: false,
            is_globally_conflicting: ut.reason_codes.includes('driver_weekly_limit'),
            details: ut.details
        }));
    }, [unassignedTours]);

    // Count by reason
    const reasonCounts = useMemo(() => {
        const counts: Record<string, number> = {};
        diagnostics.forEach(d => {
            counts[d.reason_code] = (counts[d.reason_code] || 0) + 1;
        });
        return counts;
    }, [diagnostics]);

    // Filter diagnostics
    const filteredDiagnostics = useMemo(() => {
        if (!selectedReason) return diagnostics;
        return diagnostics.filter(d => d.reason_code === selectedReason);
    }, [diagnostics, selectedReason]);

    if (unassignedTours.length === 0) {
        return null;
    }

    return (
        <div style={styles.container}>
            {/* Header */}
            <div style={styles.header}>
                <div style={styles.title}>
                    <span>⚠️</span>
                    <span>Unassigned Tours ({unassignedTours.length})</span>
                </div>
            </div>

            {/* Summary Cards */}
            <div style={styles.summaryGrid}>
                {Object.entries(reasonCounts)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 5)
                    .map(([reason, count]) => (
                        <div
                            key={reason}
                            style={{
                                ...styles.summaryCard,
                                cursor: 'pointer',
                                border: selectedReason === reason ? `2px solid ${getReasonColor(reason)}` : '2px solid transparent'
                            }}
                            onClick={() => setSelectedReason(selectedReason === reason ? null : reason)}
                        >
                            <div style={{ ...styles.summaryNumber, color: getReasonColor(reason) }}>
                                {count}
                            </div>
                            <div style={styles.summaryLabel}>
                                {reason.replace(/_/g, ' ')}
                            </div>
                        </div>
                    ))}
            </div>

            {/* Filter Chips */}
            <div style={styles.filterBar}>
                <span
                    style={{
                        ...styles.filterChip,
                        backgroundColor: !selectedReason ? '#e94560' : '#222',
                        color: !selectedReason ? '#fff' : '#888'
                    }}
                    onClick={() => setSelectedReason(null)}
                >
                    All ({diagnostics.length})
                </span>
                {Object.entries(reasonCounts).map(([reason, count]) => (
                    <span
                        key={reason}
                        style={{
                            ...styles.filterChip,
                            backgroundColor: selectedReason === reason ? getReasonColor(reason) : '#222',
                            color: selectedReason === reason ? '#fff' : '#888',
                            borderColor: getReasonColor(reason)
                        }}
                        onClick={() => setSelectedReason(selectedReason === reason ? null : reason)}
                    >
                        {reason.replace(/_/g, ' ')} ({count})
                    </span>
                ))}
            </div>

            {/* Table */}
            <table style={styles.table}>
                <thead>
                    <tr>
                        <th style={styles.th}>Tour</th>
                        <th style={styles.th}>Day</th>
                        <th style={styles.th}>Time</th>
                        <th style={styles.th}>Reason</th>
                        <th style={styles.th}>Flags</th>
                        <th style={styles.th}>Details</th>
                    </tr>
                </thead>
                <tbody>
                    {filteredDiagnostics.map(d => (
                        <React.Fragment key={d.tour_id}>
                            <tr
                                style={{ cursor: 'pointer' }}
                                onClick={() => setExpandedTour(expandedTour === d.tour_id ? null : d.tour_id)}
                            >
                                <td style={styles.td}>
                                    <strong>{d.tour_id}</strong>
                                </td>
                                <td style={styles.td}>{d.day}</td>
                                <td style={styles.td}>{d.time}</td>
                                <td style={styles.td}>
                                    <span
                                        style={{
                                            ...styles.reasonBadge,
                                            backgroundColor: `${getReasonColor(d.reason_code)}20`,
                                            color: getReasonColor(d.reason_code),
                                            border: `1px solid ${getReasonColor(d.reason_code)}`
                                        }}
                                    >
                                        {d.reason_code.replace(/_/g, ' ')}
                                    </span>
                                </td>
                                <td style={styles.td}>
                                    <span style={styles.flagIcon} title="Has blocks">
                                        {d.has_any_blocks ? '📦' : '❌'}
                                    </span>
                                    <span style={styles.flagIcon} title="Has feasible driver">
                                        {d.has_any_feasible_driver ? '👤' : '❌'}
                                    </span>
                                    <span style={styles.flagIcon} title="Global conflict">
                                        {d.is_globally_conflicting ? '⚡' : ''}
                                    </span>
                                </td>
                                <td style={{ ...styles.td, maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {d.details || reasonDescriptions[d.reason_code] || '-'}
                                </td>
                            </tr>
                            {expandedTour === d.tour_id && (
                                <tr>
                                    <td colSpan={6} style={styles.expandRow}>
                                        <div style={{ marginBottom: '8px' }}>
                                            <strong style={{ color: '#fff' }}>Full Details:</strong>
                                            <p style={{ color: '#aaa', margin: '4px 0' }}>
                                                {reasonDescriptions[d.reason_code] || d.details || 'No additional details'}
                                            </p>
                                        </div>
                                        {d.top_blockers.length > 0 && (
                                            <div>
                                                <strong style={{ color: '#fff' }}>Top Blocking Reasons:</strong>
                                                <div style={{ ...styles.blockerList, marginTop: '8px' }}>
                                                    {d.top_blockers.map(b => (
                                                        <span key={b.code} style={styles.blockerChip}>
                                                            {b.code.replace(/_/g, ' ')}: {b.count}
                                                        </span>
                                                    ))}
                                                </div>
                                            </div>
                                        )}
                                        <div style={{ marginTop: '8px', fontSize: '12px', color: '#666' }}>
                                            Blocks: {d.candidate_blocks_total} | Drivers: {d.candidate_drivers_total}
                                        </div>
                                    </td>
                                </tr>
                            )}
                        </React.Fragment>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

export default UnassignedDiagnostics;

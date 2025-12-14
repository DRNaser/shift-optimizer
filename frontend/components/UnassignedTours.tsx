// Unassigned Tours Component
// Shows tours that couldn't be assigned with reason codes

import React from 'react';
import {
    UnassignedTourOutput,
    getReasonDescription,
    ReasonCode
} from '../types';

interface UnassignedToursProps {
    tours: UnassignedTourOutput[];
}

export default function UnassignedTours({ tours }: UnassignedToursProps) {
    if (tours.length === 0) {
        return (
            <div className="bg-green-50 border border-green-200 rounded-xl p-6 text-center">
                <div className="text-green-600 font-semibold text-lg">✓ All Tours Assigned</div>
                <p className="text-green-500 text-sm mt-1">Every tour has been successfully assigned to a driver.</p>
            </div>
        );
    }

    return (
        <div className="bg-white rounded-xl shadow-lg overflow-hidden">
            <div className="bg-gradient-to-r from-amber-500 to-orange-500 px-6 py-4">
                <h2 className="text-xl font-bold text-white">Unassigned Tours</h2>
                <p className="text-amber-100 text-sm">
                    {tours.length} tour{tours.length !== 1 ? 's' : ''} could not be assigned
                </p>
            </div>

            <div className="divide-y divide-gray-100">
                {tours.map((item, idx) => (
                    <UnassignedTourRow key={idx} item={item} />
                ))}
            </div>
        </div>
    );
}

interface UnassignedTourRowProps {
    item: UnassignedTourOutput;
}

function UnassignedTourRow({ item }: UnassignedTourRowProps) {
    const { tour, reason_codes, details } = item;

    return (
        <div className="px-6 py-4 hover:bg-gray-50 transition-colors">
            <div className="flex items-start justify-between">
                <div>
                    <div className="font-medium text-gray-900">
                        {tour.id}
                    </div>
                    <div className="text-sm text-gray-500 mt-1">
                        {tour.day} • {tour.start_time} - {tour.end_time} ({tour.duration_hours.toFixed(1)}h)
                    </div>
                    {tour.location !== 'DEFAULT' && (
                        <div className="text-xs text-gray-400 mt-0.5">
                            Location: {tour.location}
                        </div>
                    )}
                </div>

                <div className="flex flex-wrap gap-1.5 max-w-xs">
                    {reason_codes.map((code, idx) => (
                        <ReasonBadge key={idx} code={code as ReasonCode} />
                    ))}
                </div>
            </div>

            {details && details !== 'Could not be assigned' && (
                <div className="mt-2 text-sm text-gray-600 bg-gray-50 rounded px-3 py-2">
                    {details}
                </div>
            )}
        </div>
    );
}

interface ReasonBadgeProps {
    code: ReasonCode;
}

function ReasonBadge({ code }: ReasonBadgeProps) {
    const getColor = (code: ReasonCode): string => {
        if (code.includes('WEEKLY') || code.includes('DAILY')) return 'bg-purple-100 text-purple-700';
        if (code.includes('QUALIFICATION')) return 'bg-blue-100 text-blue-700';
        if (code.includes('AVAILABLE')) return 'bg-yellow-100 text-yellow-700';
        if (code.includes('REST')) return 'bg-orange-100 text-orange-700';
        return 'bg-gray-100 text-gray-700';
    };

    return (
        <span
            className={`px-2 py-1 rounded-full text-xs font-medium ${getColor(code)}`}
            title={getReasonDescription(code)}
        >
            {code.replace(/_/g, ' ').toLowerCase()}
        </span>
    );
}

// Quick Data Entry Component  
// Simple form for entering tours and using sample data

import React, { useState } from 'react';
import { TourInput, DriverInput, WEEKDAYS, Weekday } from '../types';
import FileUploadZone from './FileUploadZone';

interface QuickDataEntryProps {
    onDataLoad: (tours: TourInput[], drivers: DriverInput[]) => void;
}

export default function QuickDataEntry({ onDataLoad }: QuickDataEntryProps) {
    const [activeTab, setActiveTab] = useState<'sample' | 'upload' | 'custom'>('upload');

    // Sample data for demo
    const loadSampleData = () => {
        const tours: TourInput[] = [
            // Monday
            { id: 'T-001', day: 'MONDAY', start_time: '06:00', end_time: '10:00' },
            { id: 'T-002', day: 'MONDAY', start_time: '10:30', end_time: '14:30' },
            { id: 'T-003', day: 'MONDAY', start_time: '15:00', end_time: '19:00' },
            // Tuesday
            { id: 'T-004', day: 'TUESDAY', start_time: '07:00', end_time: '11:00' },
            { id: 'T-005', day: 'TUESDAY', start_time: '11:30', end_time: '15:30' },
            { id: 'T-006', day: 'TUESDAY', start_time: '16:00', end_time: '20:00' },
            // Wednesday
            { id: 'T-007', day: 'WEDNESDAY', start_time: '06:30', end_time: '10:30' },
            { id: 'T-008', day: 'WEDNESDAY', start_time: '11:00', end_time: '15:00' },
            // Thursday
            { id: 'T-009', day: 'THURSDAY', start_time: '08:00', end_time: '12:00' },
            { id: 'T-010', day: 'THURSDAY', start_time: '12:30', end_time: '16:30' },
            { id: 'T-011', day: 'THURSDAY', start_time: '17:00', end_time: '21:00' },
            // Friday
            { id: 'T-012', day: 'FRIDAY', start_time: '06:00', end_time: '10:00' },
            { id: 'T-013', day: 'FRIDAY', start_time: '10:30', end_time: '14:30' },
            // Saturday
            { id: 'T-014', day: 'SATURDAY', start_time: '08:00', end_time: '12:00' },
            { id: 'T-015', day: 'SATURDAY', start_time: '12:30', end_time: '16:30' },
        ];

        const drivers: DriverInput[] = [
            { id: 'D-001', name: 'Max Mustermann' },
            { id: 'D-002', name: 'Anna Schmidt' },
            { id: 'D-003', name: 'Thomas Müller' },
            { id: 'D-004', name: 'Lisa Weber' },
        ];

        onDataLoad(tours, drivers);
    };

    // Extended sample data
    const loadExtendedSample = () => {
        const tours: TourInput[] = [];
        let tourNum = 1;

        for (const day of WEEKDAYS.slice(0, 6)) { // Mon-Sat
            // Morning block
            tours.push({ id: `T-${String(tourNum++).padStart(3, '0')}`, day, start_time: '06:00', end_time: '10:00' });
            tours.push({ id: `T-${String(tourNum++).padStart(3, '0')}`, day, start_time: '10:30', end_time: '14:30' });
            tours.push({ id: `T-${String(tourNum++).padStart(3, '0')}`, day, start_time: '15:00', end_time: '19:00' });

            // Extra tours on busy days
            if (['MONDAY', 'FRIDAY'].includes(day)) {
                tours.push({ id: `T-${String(tourNum++).padStart(3, '0')}`, day, start_time: '07:00', end_time: '11:00' });
                tours.push({ id: `T-${String(tourNum++).padStart(3, '0')}`, day, start_time: '11:30', end_time: '15:30' });
            }
        }

        const drivers: DriverInput[] = [];
        for (let i = 1; i <= 6; i++) {
            drivers.push({
                id: `D-${String(i).padStart(3, '0')}`,
                name: `Driver ${i}`,
            });
        }

        onDataLoad(tours, drivers);
    };

    return (
        <div className="bg-white rounded-xl shadow-lg p-6">
            <h3 className="text-lg font-semibold text-gray-800 mb-4">Load Data</h3>

            {/* Tab buttons */}
            <div className="flex gap-2 mb-4">
                <button
                    onClick={() => setActiveTab('sample')}
                    className={`px-4 py-2 rounded-lg font-medium transition-all ${activeTab === 'sample'
                        ? 'bg-indigo-100 text-indigo-700'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                >
                    Sample Data
                </button>
                <button
                    onClick={() => setActiveTab('custom')}
                    className={`px-4 py-2 rounded-lg font-medium transition-all ${activeTab === 'custom'
                        ? 'bg-indigo-100 text-indigo-700'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                >
                    Custom (JSON)
                </button>
            </div>

            {activeTab === 'sample' && (
                <div className="space-y-3">
                    <button
                        onClick={loadSampleData}
                        className="w-full py-3 px-4 bg-gradient-to-r from-indigo-500 to-purple-500 text-white font-medium rounded-lg hover:from-indigo-600 hover:to-purple-600 transition-all shadow-md hover:shadow-lg"
                    >
                        📦 Load Sample (15 tours, 4 drivers)
                    </button>
                    <button
                        onClick={loadExtendedSample}
                        className="w-full py-3 px-4 bg-gradient-to-r from-emerald-500 to-teal-500 text-white font-medium rounded-lg hover:from-emerald-600 hover:to-teal-600 transition-all shadow-md hover:shadow-lg"
                    >
                        📊 Load Extended (28 tours, 6 drivers)
                    </button>
                </div>
            )}

            {activeTab === 'upload' && (
                <div>
                    <FileUploadZone onDataLoad={onDataLoad} />
                    <div className="mt-4 text-sm text-gray-600 bg-blue-50 border border-blue-200 rounded-lg p-3">
                        <strong>💡 Tip:</strong> Your CSV/Excel should have these columns:
                        <br />
                        <strong>Tours:</strong> id, day, start_time, end_time, location (optional)
                        <br />
                        <strong>Drivers:</strong> id, name, qualifications (optional)
                    </div>
                </div>
            )}

            {activeTab === 'custom' && (
                <CustomJsonInput onDataLoad={onDataLoad} />
            )}
        </div>
    );
}

// Custom JSON input
interface CustomJsonInputProps {
    onDataLoad: (tours: TourInput[], drivers: DriverInput[]) => void;
}

function CustomJsonInput({ onDataLoad }: CustomJsonInputProps) {
    const [jsonInput, setJsonInput] = useState('');
    const [error, setError] = useState<string | null>(null);

    const handleParse = () => {
        try {
            const data = JSON.parse(jsonInput);
            if (!data.tours || !data.drivers) {
                throw new Error('JSON must have "tours" and "drivers" arrays');
            }
            onDataLoad(data.tours, data.drivers);
            setError(null);
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Invalid JSON');
        }
    };

    const exampleJson = JSON.stringify({
        tours: [
            { id: 'T-001', day: 'MONDAY', start_time: '08:00', end_time: '12:00' },
        ],
        drivers: [
            { id: 'D-001', name: 'Driver Name' },
        ],
    }, null, 2);

    return (
        <div className="space-y-3">
            <textarea
                value={jsonInput}
                onChange={(e) => setJsonInput(e.target.value)}
                placeholder={exampleJson}
                className="w-full h-40 px-3 py-2 border border-gray-300 rounded-lg font-mono text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            />
            {error && (
                <div className="text-red-600 text-sm bg-red-50 px-3 py-2 rounded">
                    {error}
                </div>
            )}
            <button
                onClick={handleParse}
                className="w-full py-2 px-4 bg-gray-800 text-white font-medium rounded-lg hover:bg-gray-900 transition-all"
            >
                Parse & Load JSON
            </button>
        </div>
    );
}

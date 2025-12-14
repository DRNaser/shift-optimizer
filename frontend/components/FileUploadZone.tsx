// File Upload Component for CSV/Excel data import
// Provides drag-and-drop and click-to-browse functionality

import React, { useState, useRef } from 'react';
import Papa from 'papaparse';
import * as XLSX from 'xlsx';
import { TourInput, DriverInput, Weekday } from '../types';

interface FileUploadZoneProps {
    onDataLoad: (tours: TourInput[], drivers: DriverInput[]) => void;
}

interface ParseResult {
    tours: TourInput[];
    drivers: DriverInput[];
    errors: string[];
}

export default function FileUploadZone({ onDataLoad }: FileUploadZoneProps) {
    const [isDragging, setIsDragging] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleDragOver = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = () => {
        setIsDragging(false);
    };

    const handleDrop = (e: React.DragEvent) => {
        e.preventDefault();
        setIsDragging(false);

        const files = Array.from(e.dataTransfer.files);
        if (files.length > 0) {
            handleFiles(files);
        }
    };

    const handleBrowseClick = () => {
        fileInputRef.current?.click();
    };

    const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files ? Array.from(e.target.files) : [];
        if (files.length > 0) {
            handleFiles(files);
        }
    };

    const handleFiles = async (files: File[]) => {
        setIsProcessing(true);
        setError(null);
        setSuccess(null);

        try {
            const file = files[0]; // Take first file
            const fileExt = file.name.split('.').pop()?.toLowerCase();

            let result: ParseResult;

            if (fileExt === 'csv') {
                result = await parseCSV(file);
            } else if (fileExt === 'xlsx' || fileExt === 'xls') {
                result = await parseExcel(file);
            } else {
                throw new Error('Unsupported file format. Please upload CSV or Excel files.');
            }

            if (result.errors.length > 0) {
                setError(`Parsed with warnings:\n${result.errors.join('\n')}`);
            }

            if (result.tours.length > 0 || result.drivers.length > 0) {
                onDataLoad(result.tours, result.drivers);
                setSuccess(`✓ Loaded ${result.tours.length} tours and ${result.drivers.length} drivers`);
            } else {
                setError('No valid data found in file');
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to parse file');
        } finally {
            setIsProcessing(false);
        }
    };

    const parseCSV = (file: File): Promise<ParseResult> => {
        return new Promise((resolve) => {
            Papa.parse(file, {
                header: true,
                skipEmptyLines: true,
                complete: (results) => {
                    const parsed = parseData(results.data as any[]);
                    resolve(parsed);
                },
                error: (error) => {
                    resolve({ tours: [], drivers: [], errors: [error.message] });
                },
            });
        });
    };

    const parseExcel = (file: File): Promise<ParseResult> => {
        return new Promise((resolve) => {
            const reader = new FileReader();

            reader.onload = (e) => {
                try {
                    const data = e.target?.result;
                    const workbook = XLSX.read(data, { type: 'binary' });

                    // Try to find tours and drivers sheets
                    const toursSheet = workbook.Sheets['Tours'] || workbook.Sheets['tours'] || workbook.Sheets[workbook.SheetNames[0]];
                    const driversSheet = workbook.Sheets['Drivers'] || workbook.Sheets['drivers'] || workbook.Sheets[workbook.SheetNames[1]];

                    const toursData = XLSX.utils.sheet_to_json(toursSheet);
                    const driversData = driversSheet ? XLSX.utils.sheet_to_json(driversSheet) : [];

                    const parsed = parseData([...toursData, ...driversData]);
                    resolve(parsed);
                } catch (error) {
                    resolve({
                        tours: [],
                        drivers: [],
                        errors: [error instanceof Error ? error.message : 'Failed to parse Excel']
                    });
                }
            };

            reader.readAsBinaryString(file);
        });
    };

    const parseData = (data: any[]): ParseResult => {
        const tours: TourInput[] = [];
        const drivers: DriverInput[] = [];
        const errors: string[] = [];

        data.forEach((row, index) => {
            // Detect if row is a tour or driver
            if (row.start_time || row.startTime || row['Start Time']) {
                // It's a tour
                try {
                    const tour: TourInput = {
                        id: row.id || row.ID || row['Tour ID'] || `T-${String(index + 1).padStart(3, '0')}`,
                        day: normalizeDay(row.day || row.Day || row.DAY),
                        start_time: normalizeTime(row.start_time || row.startTime || row['Start Time']),
                        end_time: normalizeTime(row.end_time || row.endTime || row['End Time']),
                        location: row.location || row.Location,
                        required_qualifications: parseQualifications(row.qualifications || row.Qualifications),
                    };
                    tours.push(tour);
                } catch (err) {
                    errors.push(`Row ${index + 1}: ${err instanceof Error ? err.message : 'Invalid tour data'}`);
                }
            } else if (row.name || row.Name || row.driver_name) {
                // It's a driver
                try {
                    const driver: DriverInput = {
                        id: row.id || row.ID || row['Driver ID'] || `D-${String(index + 1).padStart(3, '0')}`,
                        name: row.name || row.Name || row.driver_name || row['Driver Name'] || `Driver ${index + 1}`,
                        qualifications: parseQualifications(row.qualifications || row.Qualifications),
                        max_weekly_hours: row.max_weekly_hours || row['Max Weekly Hours'],
                        max_daily_span_hours: row.max_daily_span_hours || row['Max Daily Span'],
                        max_tours_per_day: row.max_tours_per_day || row['Max Tours Per Day'],
                    };
                    drivers.push(driver);
                } catch (err) {
                    errors.push(`Row ${index + 1}: ${err instanceof Error ? err.message : 'Invalid driver data'}`);
                }
            }
        });

        return { tours, drivers, errors };
    };

    const normalizeDay = (day: string): Weekday => {
        if (!day) throw new Error('Missing day');

        const dayUpper = day.toUpperCase();
        const dayMap: Record<string, Weekday> = {
            'MON': 'MONDAY', 'MONDAY': 'MONDAY',
            'TUE': 'TUESDAY', 'TUESDAY': 'TUESDAY',
            'WED': 'WEDNESDAY', 'WEDNESDAY': 'WEDNESDAY',
            'THU': 'THURSDAY', 'THURSDAY': 'THURSDAY',
            'FRI': 'FRIDAY', 'FRIDAY': 'FRIDAY',
            'SAT': 'SATURDAY', 'SATURDAY': 'SATURDAY',
            'SUN': 'SUNDAY', 'SUNDAY': 'SUNDAY',
        };

        if (dayMap[dayUpper]) return dayMap[dayUpper];
        throw new Error(`Invalid day: ${day}`);
    };

    const normalizeTime = (time: string): string => {
        if (!time) throw new Error('Missing time');

        // Handle HH:MM format
        if (/^\d{1,2}:\d{2}$/.test(time)) {
            return time;
        }

        // Handle Excel time number (fraction of day)
        if (!isNaN(Number(time))) {
            const totalMinutes = Math.round(Number(time) * 24 * 60);
            const hours = Math.floor(totalMinutes / 60);
            const minutes = totalMinutes % 60;
            return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`;
        }

        throw new Error(`Invalid time format: ${time}`);
    };

    const parseQualifications = (qual: any): string[] | undefined => {
        if (!qual) return undefined;
        if (Array.isArray(qual)) return qual;
        if (typeof qual === 'string') {
            return qual.split(',').map(q => q.trim()).filter(q => q);
        }
        return undefined;
    };

    return (
        <div className="file-upload-container">
            <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={handleBrowseClick}
                className={`upload-zone ${isDragging ? 'dragging' : ''} ${isProcessing ? 'processing' : ''}`}
            >
                <div className="upload-icon">
                    {isProcessing ? '⏳' : '📁'}
                </div>
                <h3>{isProcessing ? 'Processing...' : 'Drag & drop CSV/Excel here'}</h3>
                <p>or <span className="browse-link">click to browse</span></p>
                <small>Supported formats: .csv, .xlsx, .xls</small>
            </div>

            <input
                ref={fileInputRef}
                type="file"
                accept=".csv,.xlsx,.xls"
                onChange={handleFileInputChange}
                style={{ display: 'none' }}
            />

            {error && (
                <div className="message message-error">
                    <span className="message-icon">⚠️</span>
                    <span className="message-text">{error}</span>
                </div>
            )}

            {success && (
                <div className="message message-success">
                    <span className="message-icon">✓</span>
                    <span className="message-text">{success}</span>
                </div>
            )}

            <style>{`
        .file-upload-container {
          width: 100%;
        }

        .upload-zone {
          border: 2px dashed #cbd5e1;
          background: #f8fafc;
          border-radius: 12px;
          padding: 48px 24px;
          text-align: center;
          cursor: pointer;
          transition: all 250ms ease-in-out;
        }

        .upload-zone:hover {
          border-color: #6366f1;
          background: #eef2ff;
        }

        .upload-zone.dragging {
          border-color: #22c55e;
          background: #f0fdf4;
          transform: scale(1.02);
        }

        .upload-zone.processing {
          cursor: wait;
          opacity: 0.7;
        }

        .upload-icon {
          font-size: 48px;
          margin-bottom: 16px;
          animation: float 3s ease-in-out infinite;
        }

        @keyframes float {
          0%, 100% { transform: translateY(0); }
          50% { transform: translateY(-10px); }
        }

        .upload-zone h3 {
          margin: 0 0 8px 0;
          font-size: 18px;
          font-weight: 600;
          color: #0f172a;
        }

        .upload-zone p {
          margin: 0 0 8px 0;
          font-size: 14px;
          color: #64748b;
        }

        .browse-link {
          color: #6366f1;
          text-decoration: underline;
          font-weight: 500;
        }

        .upload-zone small {
          display: block;
          font-size: 12px;
          color: #94a3b8;
        }

        .message {
          margin-top: 16px;
          padding: 12px 16px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          gap: 12px;
          font-size: 14px;
          animation: slideIn 250ms ease-out;
        }

        @keyframes slideIn {
          from {
            opacity: 0;
            transform: translateY(-8px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        .message-error {
          background: #fef2f2;
          color: #991b1b;
          border: 1px solid #fecaca;
        }

        .message-success {
          background: #f0fdf4;
          color: #166534;
          border: 1px solid #bbf7d0;
        }

        .message-icon {
          font-size: 18px;
          flex-shrink: 0;
        }

        .message-text {
          flex: 1;
          white-space: pre-line;
        }
      `}</style>
        </div>
    );
}

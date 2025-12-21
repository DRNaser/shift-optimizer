/**
 * CSV Parsing Utility
 * -------------------
 * Parses the German-format forecast CSV into tour objects.
 * 
 * Supports two formats:
 * 1. Simple: tour_id, weekday, start_time, end_time
 * 2. Forecast: Day header (e.g., "Montag;Anzahl") followed by "Zeit;Count" rows
 */

import type { TourInput, WeekdayFE } from '../api';

const WEEKDAY_MAP: Record<string, WeekdayFE> = {
    // German to short format (backend expects 'Mon', 'Tue', etc.)
    'montag': 'Mon',
    'dienstag': 'Tue',
    'mittwoch': 'Wed',
    'donnerstag': 'Thu',
    'freitag': 'Fri',
    'samstag': 'Sat',
    'sonntag': 'Sun',
    // English
    'monday': 'Mon',
    'tuesday': 'Tue',
    'wednesday': 'Wed',
    'thursday': 'Thu',
    'friday': 'Fri',
    'saturday': 'Sat',
    'sunday': 'Sun',
};


export interface ParseResult {
    tours: TourInput[];
    errors: string[];
    weekStart: string;
}

/**
 * Parse a forecast CSV file content.
 * Detects format automatically and handles both simple and forecast formats.
 */
export function parseForecastCSV(content: string): ParseResult {
    // Remove BOM if present
    const cleanContent = content.replace(/^\uFEFF/, '').trim();
    const lines = cleanContent.split(/\r?\n/);
    if (lines.length < 2) {
        return { tours: [], errors: ['CSV must have at least a header and one data row'], weekStart: '' };
    }

    // Detect delimiter
    const delimiter = lines[0].includes(';') ? ';' : ',';
    const firstLine = lines[0].split(delimiter).map(h => h.trim().toLowerCase());

    // Check if this is the forecast format:
    // 1. First column is a day name (e.g., "montag")
    // 2. OR second column contains "anzahl"
    // 3. OR first column contains a time range (e.g., "04:45-09:15")
    const dayNames = ['montag', 'dienstag', 'mittwoch', 'donnerstag', 'freitag', 'samstag', 'sonntag'];
    const firstColIsDay = dayNames.some(day => firstLine[0] === day || firstLine[0].startsWith(day));
    const secondColIsAnzahl = firstLine.length > 1 && firstLine[1].includes('anzahl');
    const hasTimeRange = /^\d{1,2}:\d{2}-\d{1,2}:\d{2}$/.test(firstLine[0]);

    const isForecastFormat = firstColIsDay || secondColIsAnzahl || hasTimeRange;

    console.log('CSV Detection:', { firstLine, firstColIsDay, secondColIsAnzahl, isForecastFormat });

    if (isForecastFormat) {
        return parseForecastFormat(lines, delimiter);
    } else {
        return parseSimpleFormat(lines, delimiter);
    }
}

/**
 * Parse forecast format:
 * Montag;Anzahl
 * 04:45-09:15;15
 * 05:00-09:30;10
 * ;
 * Dienstag;Anzahl
 * ...
 */
function parseForecastFormat(lines: string[], delimiter: string): ParseResult {
    const tours: TourInput[] = [];
    const errors: string[] = [];
    let currentDay: WeekdayFE | null = null;
    let tourCounter = 0;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line || line === delimiter) continue;

        const cols = line.split(delimiter).map(c => c.trim());
        const firstCol = cols[0].toLowerCase();

        // Check if this is a day header
        const matchedDay = Object.entries(WEEKDAY_MAP).find(([key]) =>
            firstCol.includes(key)
        );

        if (matchedDay) {
            currentDay = matchedDay[1];
            continue;
        }

        // Skip if no day context yet
        if (!currentDay) {
            continue;
        }

        // Parse time slot and count
        const timeSlot = cols[0];
        const countStr = cols[1];

        // Validate time slot format (HH:MM-HH:MM)
        const timeMatch = timeSlot.match(/^(\d{1,2}:\d{2})-(\d{1,2}:\d{2})$/);
        if (!timeMatch) {
            if (timeSlot) {
                errors.push(`Row ${i + 1}: Invalid time format '${timeSlot}'`);
            }
            continue;
        }

        const startTime = timeMatch[1].padStart(5, '0');
        const endTime = timeMatch[2].padStart(5, '0');
        const count = parseInt(countStr, 10);

        if (isNaN(count) || count <= 0) {
            errors.push(`Row ${i + 1}: Invalid count '${countStr}'`);
            continue;
        }

        // Create individual tours for each count
        for (let j = 0; j < count; j++) {
            tourCounter++;
            tours.push({
                id: `T${String(tourCounter).padStart(4, '0')}`,
                day: currentDay,
                start_time: startTime,
                end_time: endTime,
            });
        }
    }

    // Calculate week start (next Monday from today)
    const today = new Date();
    const daysUntilMonday = (8 - today.getDay()) % 7 || 7;
    const nextMonday = new Date(today);
    nextMonday.setDate(today.getDate() + daysUntilMonday);
    const weekStart = nextMonday.toISOString().split('T')[0];

    return { tours, errors, weekStart };
}

/**
 * Parse simple format:
 * tour_id, weekday, start_time, end_time
 */
function parseSimpleFormat(lines: string[], delimiter: string): ParseResult {
    const header = lines[0].split(delimiter).map(h => h.trim().toLowerCase());

    // Column indices
    const idIdx = header.findIndex(h => h.includes('tour') && h.includes('id'));
    const dayIdx = header.findIndex(h => h === 'weekday' || h === 'wochentag' || h === 'day');
    const startIdx = header.findIndex(h => h.includes('start'));
    const endIdx = header.findIndex(h => h.includes('end') || h.includes('ende'));

    if (idIdx < 0 || dayIdx < 0 || startIdx < 0 || endIdx < 0) {
        return {
            tours: [],
            errors: [`Missing required columns. Found: ${header.join(', ')}`],
            weekStart: '',
        };
    }

    const tours: TourInput[] = [];
    const errors: string[] = [];

    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;

        const cols = line.split(delimiter).map(c => c.trim());
        const tourId = cols[idIdx];
        const dayRaw = cols[dayIdx].toLowerCase();
        const startTime = cols[startIdx];
        const endTime = cols[endIdx];

        const day = WEEKDAY_MAP[dayRaw];
        if (!day) {
            errors.push(`Row ${i + 1}: Unknown weekday '${dayRaw}'`);
            continue;
        }

        // Validate times (HH:MM format)
        if (!/^\d{1,2}:\d{2}$/.test(startTime) || !/^\d{1,2}:\d{2}$/.test(endTime)) {
            errors.push(`Row ${i + 1}: Invalid time format`);
            continue;
        }

        tours.push({
            id: tourId,
            day,
            start_time: startTime.padStart(5, '0'),
            end_time: endTime.padStart(5, '0'),
        });
    }

    // Calculate week start
    const today = new Date();
    const daysUntilMonday = (8 - today.getDay()) % 7 || 7;
    const nextMonday = new Date(today);
    nextMonday.setDate(today.getDate() + daysUntilMonday);
    const weekStart = nextMonday.toISOString().split('T')[0];

    return { tours, errors, weekStart };
}

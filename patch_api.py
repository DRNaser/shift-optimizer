"""Patch api.ts to support forecast format"""
import pathlib
import re

# Read original
p = pathlib.Path('frontend_next/lib/api.ts')
content = p.read_text(encoding='utf-8')

# New parser function
new_parser = '''
const DAY_MAP_FORECAST: Record<string, TourInput['day']> = {
    'montag': 'MONDAY',
    'dienstag': 'TUESDAY',
    'mittwoch': 'WEDNESDAY',
    'donnerstag': 'THURSDAY',
    'freitag': 'FRIDAY',
    'samstag': 'SATURDAY',
    'sonntag': 'SUNDAY',
    'monday': 'MONDAY',
    'tuesday': 'TUESDAY',
    'wednesday': 'WEDNESDAY',
    'thursday': 'THURSDAY',
    'friday': 'FRIDAY',
    'saturday': 'SATURDAY',
    'sunday': 'SUNDAY',
};

export function parseToursFromCSV(content: string): TourInput[] {
    const lines = content.trim().split(/\\r?\\n/);
    const tours: TourInput[] = [];
    let currentDay: TourInput['day'] | null = null;
    let tourCounter = 1;

    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) continue;

        const parts = trimmed.split(/[\\t,;]/);
        const firstPart = parts[0].trim().toLowerCase();

        // Check if day header
        const dayMatch = Object.keys(DAY_MAP_FORECAST).find(d => firstPart.startsWith(d));
        if (dayMatch) {
            currentDay = DAY_MAP_FORECAST[dayMatch];
            continue;
        }

        if (firstPart === 'anzahl' || firstPart === 'count' || !firstPart) continue;

        // Parse time range: 04:45-09:15
        const timeMatch = firstPart.match(/(\\d{1,2}:\\d{2})-(\\d{1,2}:\\d{2})/);
        if (timeMatch && currentDay) {
            const [, startTime, endTime] = timeMatch;
            const countPart = parts[1]?.trim();
            const count = parseInt(countPart) || 1;

            for (let i = 0; i < count; i++) {
                tours.push({
                    id: `T-${tourCounter++}`,
                    day: currentDay,
                    start_time: normalizeTime(startTime),
                    end_time: normalizeTime(endTime),
                });
            }
        }
    }
    return tours;
}
'''

# Find beginning and end of parser function
start_marker = "export function parseToursFromCSV(content: string): TourInput[] {"
end_marker = "\n    return tours;\n}"

start_idx = content.find(start_marker)
if start_idx == -1:
    print("Could not find parseToursFromCSV function start!")
    exit(1)

# Find end of function
search_from = start_idx
end_idx = content.find(end_marker, search_from)
if end_idx == -1:
    print("Could not find function end!")
    exit(1)

end_idx += len(end_marker)

# Replace
new_content = content[:start_idx] + new_parser.strip() + content[end_idx:]

p.write_text(new_content, encoding='utf-8')
print(f"Parser patched! Replaced {end_idx - start_idx} chars")


import { OptimizationResult, Driver } from '../types';

export const exportToJson = (data: OptimizationResult, filename: string) => {
  const jsonString = `data:text/json;charset=utf-8,${encodeURIComponent(
    JSON.stringify(data, null, 2)
  )}`;
  const link = document.createElement('a');
  link.href = jsonString;
  link.download = filename;
  link.click();
};

const convertToCsv = (result: OptimizationResult): string => {
  const headers = [
    'driver_id',
    'day',
    'block_type',
    'total_hours',
    'segment_1_start',
    'segment_1_end',
    'segment_2_start',
    'segment_2_end',
    'segment_3_start',
    'segment_3_end',
  ];

  const rows = result.drivers.map(driver => {
    const row: (string | number)[] = [
      driver.driver_id,
      driver.day,
      driver.block_type,
      driver.total_hours,
    ];
    for(let i=0; i<3; i++){
        if(driver.segments[i]){
            row.push(driver.segments[i].start, driver.segments[i].end);
        } else {
            row.push('', '');
        }
    }
    return row.join(',');
  });

  return [headers.join(','), ...rows].join('\n');
};

export const exportToCsv = (data: OptimizationResult, filename: string) => {
    const csvString = convertToCsv(data);
    const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    const url = URL.createObjectURL(blob);
    link.setAttribute('href', url);
    link.setAttribute('download', filename);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
};

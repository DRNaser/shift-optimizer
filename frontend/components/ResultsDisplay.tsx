import React from 'react';
import { OptimizationResult } from '../types';
import StatsPanel from './StatsPanel';
import { exportToCsv, exportToJson } from '../utils/export';
// FIX: Removed unused 'DownloadIcon' import as it is not exported from './Icons'.
import { CsvIcon, JsonIcon } from './Icons';

interface ResultsDisplayProps {
  result: OptimizationResult;
}

const blockTypeStyles = {
    '3er': 'bg-green-100 text-green-800',
    '2er': 'bg-blue-100 text-blue-800',
    '1er': 'bg-yellow-100 text-yellow-800'
}

const ResultsDisplay: React.FC<ResultsDisplayProps> = ({ result }) => {
  if (!result) return null;

  return (
    <div className="bg-white p-6 rounded-lg shadow-md">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6">
        <h2 className="text-2xl font-bold text-slate-700 mb-4 md:mb-0">2. Optimization Results</h2>
        <div className="flex gap-4">
            <button onClick={() => exportToJson(result, 'optimization_results.json')} className="flex items-center justify-center gap-2 bg-orange-500 text-white font-semibold py-2 px-4 rounded-lg hover:bg-orange-600 transition-colors">
                <JsonIcon /> Export JSON
            </button>
            <button onClick={() => exportToCsv(result, 'optimization_results.csv')} className="flex items-center justify-center gap-2 bg-green-500 text-white font-semibold py-2 px-4 rounded-lg hover:bg-green-600 transition-colors">
                <CsvIcon /> Export CSV
            </button>
        </div>
      </div>
      
      <StatsPanel stats={result.stats} />

      <h3 className="text-xl font-semibold text-slate-600 mt-8 mb-4">Driver Assignments</h3>
      <div className="overflow-x-auto border border-slate-200 rounded-lg max-h-[70vh]">
        <table className="w-full text-sm text-left text-slate-500">
          <thead className="text-xs text-slate-700 uppercase bg-slate-100 sticky top-0">
            <tr>
              <th scope="col" className="px-6 py-3">Driver ID</th>
              <th scope="col" className="px-6 py-3">Day</th>
              <th scope="col" className="px-6 py-3">Block Type</th>
              <th scope="col" className="px-6 py-3">Shift Segments</th>
              <th scope="col" className="px-6 py-3 text-right">Total Hours</th>
            </tr>
          </thead>
          <tbody>
            {result.drivers.map((driver) => (
              <tr key={driver.driver_id} className="bg-white border-b hover:bg-slate-50">
                <td className="px-6 py-4 font-medium text-slate-900">{driver.driver_id}</td>
                <td className="px-6 py-4">{driver.day}</td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-1 text-xs font-semibold rounded-full ${blockTypeStyles[driver.block_type]}`}>
                    {driver.block_type} Block
                  </span>
                </td>
                <td className="px-6 py-4">
                  <div className="flex flex-col gap-1">
                    {driver.segments.map((seg, index) => (
                      <span key={index} className="bg-slate-100 text-slate-700 px-2 py-0.5 rounded text-center">
                        {seg.start} - {seg.end}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="px-6 py-4 text-right font-medium text-slate-900">{driver.total_hours.toFixed(2)}h</td>
              </tr>
            ))}
          </tbody>
        </table>
         {result.drivers.length === 0 && (
            <div className="text-center py-8 text-slate-500 bg-slate-50 rounded-b-lg">
                No driver assignments could be generated from the input shifts.
            </div>
         )}
      </div>
    </div>
  );
};

export default ResultsDisplay;
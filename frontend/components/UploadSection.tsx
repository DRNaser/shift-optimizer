
import React, { useRef } from 'react';
import { Shift } from '../types';
import { CsvIcon, JsonIcon } from './Icons';

interface UploadSectionProps {
  setShifts: React.Dispatch<React.SetStateAction<Shift[]>>;
}

const UploadSection: React.FC<UploadSectionProps> = ({ setShifts }) => {
  const jsonInputRef = useRef<HTMLInputElement>(null);
  const csvInputRef = useRef<HTMLInputElement>(null);

  const handleJsonUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const content = e.target?.result;
          const parsedShifts = JSON.parse(content as string);
          // Add a temporary unique ID for React list keys
          const shiftsWithIds = parsedShifts.map((shift: Omit<Shift, 'id'>, index: number) => ({...shift, id: Date.now() + index}));
          setShifts(shiftsWithIds);
        } catch (error) {
          alert('Error parsing JSON file. Please check the file format.');
        }
      };
      reader.readAsText(file);
    }
     // Reset file input to allow uploading the same file again
    if(event.target) event.target.value = '';
  };

  const handleCsvUpload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const content = e.target?.result as string;
          const lines = content.split(/\r?\n/).filter(line => line.trim() !== '');
          const headers = lines[0].split(',').map(h => h.trim());
          const dayIndex = headers.indexOf('day');
          const startIndex = headers.indexOf('start');
          const endIndex = headers.indexOf('end');

          if(dayIndex === -1 || startIndex === -1 || endIndex === -1) {
            throw new Error('CSV must contain "day", "start", and "end" columns.');
          }

          const parsedShifts = lines.slice(1).map((line, index) => {
            const values = line.split(',');
            return {
              day: values[dayIndex].trim(),
              start: values[startIndex].trim(),
              end: values[endIndex].trim(),
              id: Date.now() + index,
            };
          });
          setShifts(parsedShifts);
        } catch (error) {
          alert(`Error parsing CSV file: ${error instanceof Error ? error.message : 'Unknown error'}`);
        }
      };
      reader.readAsText(file);
    }
    if(event.target) event.target.value = '';
  };

  return (
    <div className="flex flex-col sm:flex-row gap-4">
      <input type="file" accept=".json" ref={jsonInputRef} onChange={handleJsonUpload} className="hidden" />
      <button onClick={() => jsonInputRef.current?.click()} className="flex items-center justify-center gap-2 w-full sm:w-auto bg-orange-500 text-white font-semibold py-2 px-4 rounded-lg hover:bg-orange-600 transition-colors">
        <JsonIcon />
        Upload JSON
      </button>

      <input type="file" accept=".csv" ref={csvInputRef} onChange={handleCsvUpload} className="hidden" />
      <button onClick={() => csvInputRef.current?.click()} className="flex items-center justify-center gap-2 w-full sm:w-auto bg-green-500 text-white font-semibold py-2 px-4 rounded-lg hover:bg-green-600 transition-colors">
        <CsvIcon />
        Upload CSV
      </button>
    </div>
  );
};

export default UploadSection;

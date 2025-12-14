
import React from 'react';
import { Shift } from '../types';
import { TrashIcon } from './Icons';

interface InputTableProps {
  shifts: Shift[];
  setShifts: React.Dispatch<React.SetStateAction<Shift[]>>;
}

const validDays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const InputTable: React.FC<InputTableProps> = ({ shifts, setShifts }) => {
  const handleAddShift = () => {
    const newShift: Shift = {
      id: Date.now(),
      day: 'Mon',
      start: '09:00',
      end: '17:00',
    };
    setShifts([...shifts, newShift]);
  };

  const handleRemoveShift = (id: number) => {
    setShifts(shifts.filter(shift => shift.id !== id));
  };

  const handleUpdateShift = (id: number, field: keyof Omit<Shift, 'id'>, value: string) => {
    setShifts(
      shifts.map(shift =>
        shift.id === id ? { ...shift, [field]: value } : shift
      )
    );
  };

  return (
    <div>
      <h3 className="text-lg font-semibold text-slate-600 mb-2">Editable Shifts</h3>
      <div className="overflow-x-auto max-h-96 border border-slate-200 rounded-lg">
        <table className="w-full text-sm text-left text-slate-500">
          <thead className="text-xs text-slate-700 uppercase bg-slate-100 sticky top-0">
            <tr>
              <th scope="col" className="px-6 py-3">Day</th>
              <th scope="col" className="px-6 py-3">Start Time</th>
              <th scope="col" className="px-6 py-3">End Time</th>
              <th scope="col" className="px-6 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {shifts.map((shift) => (
              <tr key={shift.id} className="bg-white border-b hover:bg-slate-50">
                <td className="px-6 py-4">
                  <select
                    value={shift.day}
                    onChange={(e) => handleUpdateShift(shift.id!, 'day', e.target.value)}
                    className="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5"
                  >
                    {validDays.map(day => <option key={day} value={day}>{day}</option>)}
                  </select>
                </td>
                <td className="px-6 py-4">
                  <input
                    type="time"
                    value={shift.start}
                    onChange={(e) => handleUpdateShift(shift.id!, 'start', e.target.value)}
                    className="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5"
                  />
                </td>
                <td className="px-6 py-4">
                  <input
                    type="time"
                    value={shift.end}
                    onChange={(e) => handleUpdateShift(shift.id!, 'end', e.target.value)}
                    className="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5"
                  />
                </td>
                <td className="px-6 py-4 text-right">
                  <button onClick={() => handleRemoveShift(shift.id!)} className="text-red-500 hover:text-red-700">
                    <TrashIcon />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shifts.length === 0 && (
        <div className="text-center py-8 text-slate-500 bg-slate-50 rounded-b-lg">
            No shifts loaded. Upload a file or add a shift to begin.
        </div>
      )}
      <div className="mt-4">
        <button onClick={handleAddShift} className="bg-slate-200 text-slate-700 font-semibold py-2 px-4 rounded-lg hover:bg-slate-300 transition-colors">
          + Add Shift
        </button>
      </div>
    </div>
  );
};

export default InputTable;

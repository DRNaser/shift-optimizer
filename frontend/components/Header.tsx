// Header Component
// App header with title and description

import React from 'react';

const Header: React.FC = () => {
  return (
    <header className="bg-gradient-to-r from-indigo-700 via-purple-700 to-indigo-800 shadow-lg">
      <div className="container mx-auto px-4 md:px-8 py-6 max-w-7xl">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">
              ⚡ Shift Optimizer
            </h1>
            <p className="text-indigo-200 mt-1">
              Optimal weekly shift assignment powered by OR-Tools
            </p>
          </div>
          <div className="hidden md:flex items-center gap-4 text-indigo-200 text-sm">
            <span className="bg-indigo-600/50 px-3 py-1 rounded-full">
              v2.0
            </span>
            <span>CP-SAT + LNS</span>
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;

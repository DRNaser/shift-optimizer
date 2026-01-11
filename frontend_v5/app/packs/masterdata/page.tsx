// =============================================================================
// SOLVEREIGN Master Data Pack - Placeholder
// =============================================================================
// Placeholder page for Master Data Pack.
// Manages drivers, vehicles, and locations.
// =============================================================================

'use client';

import { FileText, Users, Truck, MapPin, ArrowRight } from 'lucide-react';
import Link from 'next/link';

export default function MasterDataPackPage() {
  return (
    <div className="min-h-screen bg-slate-900 flex items-center justify-center p-8">
      <div className="max-w-lg w-full text-center">
        {/* Icon */}
        <div className="inline-flex items-center justify-center h-20 w-20 rounded-2xl bg-slate-500/20 mb-6">
          <FileText className="h-10 w-10 text-slate-400" />
        </div>

        {/* Title */}
        <h1 className="text-2xl font-bold text-white mb-3">
          Master Data Pack
        </h1>
        <p className="text-slate-400 mb-8">
          Manage your core business entities: drivers, vehicles, and locations.
          Sync with external systems and maintain data quality.
        </p>

        {/* Features */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
          <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
            <Users className="h-6 w-6 text-slate-400 mx-auto mb-2" />
            <p className="text-sm text-slate-300">Driver profiles</p>
          </div>
          <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
            <Truck className="h-6 w-6 text-slate-400 mx-auto mb-2" />
            <p className="text-sm text-slate-300">Vehicle fleet</p>
          </div>
          <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700/50">
            <MapPin className="h-6 w-6 text-slate-400 mx-auto mb-2" />
            <p className="text-sm text-slate-300">Locations</p>
          </div>
        </div>

        {/* Coming Soon Badge */}
        <div className="inline-flex items-center gap-2 px-4 py-2 bg-slate-800 border border-slate-700 rounded-full mb-6">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-slate-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-slate-500"></span>
          </span>
          <span className="text-sm text-slate-300">Coming Soon</span>
        </div>

        {/* Back Link */}
        <div>
          <Link
            href="/platform/home"
            className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white transition-colors"
          >
            <ArrowRight className="h-4 w-4 rotate-180" />
            Back to Platform Home
          </Link>
        </div>
      </div>
    </div>
  );
}

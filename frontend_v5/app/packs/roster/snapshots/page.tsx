'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Camera, Clock, AlertCircle, Loader2, ChevronRight, Snowflake, User } from 'lucide-react';

interface SnapshotSummary {
  id: number;
  snapshot_id: string;
  plan_version_id: number;
  version_number: number;
  status: string;
  published_at: string;
  published_by: string;
  publish_reason: string | null;
  freeze_until: string;
  is_frozen: boolean;
}

interface SnapshotsResponse {
  success: boolean;
  snapshots: SnapshotSummary[];
  total: number;
  error?: string;
}

export default function SnapshotsListPage() {
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    async function fetchSnapshots() {
      try {
        const response = await fetch('/api/roster/snapshots');
        const data: SnapshotsResponse = await response.json();

        if (!response.ok) {
          throw new Error(data.error || 'Failed to fetch snapshots');
        }

        setSnapshots(data.snapshots || []);
        setTotal(data.total || 0);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }
    fetchSnapshots();
  }, []);

  function getStatusColor(status: string) {
    switch (status) {
      case 'ACTIVE': return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
      case 'SUPERSEDED': return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
      case 'ARCHIVED': return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
      default: return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 text-slate-400 animate-spin" />
          <p className="text-slate-400">Loading snapshots...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-900 p-8">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 flex items-center gap-3 text-red-400">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <p>{error}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Snapshots</h1>
            <p className="text-slate-400 text-sm mt-1">{total} published snapshot(s)</p>
          </div>
        </div>

        {/* Empty State */}
        {snapshots.length === 0 ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-12 text-center">
            <Camera className="w-12 h-12 text-slate-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-slate-300 mb-2">No snapshots yet</h3>
            <p className="text-slate-500 mb-6">Publish a plan to create an immutable snapshot.</p>
            <Link
              href="/packs/roster/plans"
              className="inline-flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-lg text-sm font-medium text-white transition-colors"
            >
              View Plans
            </Link>
          </div>
        ) : (
          /* Snapshots Table */
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-slate-800/80">
                <tr>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">ID</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Version</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Plan</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Status</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Published</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Freeze Until</th>
                  <th className="text-right p-4 text-sm font-medium text-slate-400"></th>
                </tr>
              </thead>
              <tbody>
                {snapshots.map((snapshot) => (
                  <tr key={snapshot.id} className="border-t border-slate-700/50 hover:bg-slate-800/30 transition-colors">
                    <td className="p-4">
                      <span className="font-mono text-slate-300">#{snapshot.id}</span>
                    </td>
                    <td className="p-4">
                      <span className="font-mono text-sm text-slate-300">v{snapshot.version_number}</span>
                    </td>
                    <td className="p-4">
                      <Link href={`/packs/roster/plans/${snapshot.plan_version_id}`} className="text-blue-400 hover:text-blue-300">
                        Plan #{snapshot.plan_version_id}
                      </Link>
                    </td>
                    <td className="p-4">
                      <div className="flex items-center gap-2">
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusColor(snapshot.status)}`}>
                          {snapshot.status}
                        </span>
                        {snapshot.is_frozen && (
                          <span className="flex items-center gap-1 text-cyan-400 text-xs">
                            <Snowflake className="w-3.5 h-3.5" />
                            FROZEN
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="p-4">
                      <div className="text-sm">
                        <div className="flex items-center gap-2 text-slate-300">
                          <Clock className="w-3.5 h-3.5 text-slate-500" />
                          {new Date(snapshot.published_at).toLocaleDateString()}
                        </div>
                        <div className="flex items-center gap-2 text-slate-500 text-xs mt-1">
                          <User className="w-3 h-3" />
                          {snapshot.published_by}
                        </div>
                      </div>
                    </td>
                    <td className="p-4">
                      <span className="text-slate-400 text-sm">
                        {new Date(snapshot.freeze_until).toLocaleString()}
                      </span>
                    </td>
                    <td className="p-4 text-right">
                      <Link
                        href={`/packs/roster/snapshots/${snapshot.id}`}
                        className="inline-flex items-center gap-1 text-sm text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        View
                        <ChevronRight className="w-4 h-4" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

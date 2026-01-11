'use client';

import { useState, useEffect, use } from 'react';
import Link from 'next/link';
import { ArrowLeft, Camera, Clock, AlertCircle, Loader2, Snowflake, Hash, ExternalLink } from 'lucide-react';

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

interface SnapshotDetailResponse {
  success: boolean;
  snapshot: SnapshotSummary;
  kpi_snapshot: Record<string, unknown> | null;
  assignments_count: number;
  hashes: {
    input_hash: string | null;
    matrix_hash: string | null;
    output_hash: string | null;
    evidence_hash: string | null;
  };
  evidence_ref: string | null;
  error?: string;
}

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function SnapshotDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const [data, setData] = useState<SnapshotDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchSnapshot() {
      try {
        const response = await fetch(`/api/roster/snapshots/${id}`);
        const result: SnapshotDetailResponse = await response.json();

        if (!response.ok) {
          throw new Error(result.error || 'Failed to fetch snapshot');
        }

        setData(result);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }
    fetchSnapshot();
  }, [id]);

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
          <p className="text-slate-400">Loading snapshot...</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen bg-slate-900 p-8">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 flex items-center gap-3 text-red-400">
            <AlertCircle className="w-5 h-5 shrink-0" />
            <p>{error || 'Snapshot not found'}</p>
          </div>
        </div>
      </div>
    );
  }

  const { snapshot, kpi_snapshot, assignments_count, hashes, evidence_ref } = data;

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link href="/packs/roster/snapshots" className="text-slate-400 hover:text-slate-200 transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <Camera className="w-6 h-6 text-slate-500" />
              Snapshot v{snapshot.version_number}
              {snapshot.is_frozen && (
                <span className="flex items-center gap-1 text-cyan-400 text-sm font-normal">
                  <Snowflake className="w-4 h-4" />
                  FROZEN
                </span>
              )}
            </h1>
            <p className="text-slate-500 text-sm">#{snapshot.id}</p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Info */}
          <div className="lg:col-span-2 space-y-6">
            {/* Status Card */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Snapshot Details</h2>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-slate-500 mb-1">Status</p>
                  <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusColor(snapshot.status)}`}>
                    {snapshot.status}
                  </span>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Plan</p>
                  <Link href={`/packs/roster/plans/${snapshot.plan_version_id}`} className="text-blue-400 hover:text-blue-300">
                    Plan #{snapshot.plan_version_id}
                  </Link>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Assignments</p>
                  <p className="text-slate-300">{assignments_count}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Published By</p>
                  <p className="text-slate-300">{snapshot.published_by}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Published At</p>
                  <p className="text-slate-300">{new Date(snapshot.published_at).toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Freeze Until</p>
                  <p className="text-slate-300">{new Date(snapshot.freeze_until).toLocaleString()}</p>
                </div>
              </div>

              {snapshot.publish_reason && (
                <div className="mt-4 pt-4 border-t border-slate-700/50">
                  <p className="text-sm text-slate-500 mb-1">Reason</p>
                  <p className="text-slate-300">{snapshot.publish_reason}</p>
                </div>
              )}
            </div>

            {/* Hashes */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <Hash className="w-5 h-5 text-slate-500" />
                Integrity Hashes
              </h2>
              <div className="space-y-3">
                {Object.entries(hashes).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between">
                    <span className="text-sm text-slate-500">{key.replace('_', ' ')}</span>
                    <span className="font-mono text-xs text-slate-400 truncate max-w-[300px]">
                      {value || '-'}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* KPIs */}
            {kpi_snapshot && Object.keys(kpi_snapshot).length > 0 && (
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6">
                <h2 className="text-lg font-semibold text-white mb-4">KPIs at Publish Time</h2>
                <pre className="text-xs text-slate-400 bg-slate-900/50 rounded p-4 overflow-auto max-h-64">
                  {JSON.stringify(kpi_snapshot, null, 2)}
                </pre>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Evidence */}
            {evidence_ref && (
              <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6">
                <h2 className="text-lg font-semibold text-white mb-4">Evidence</h2>
                <div className="bg-slate-900/50 rounded p-3">
                  <p className="font-mono text-xs text-slate-400 break-all">{evidence_ref}</p>
                </div>
                <Link
                  href={`/platform-admin/evidence`}
                  className="mt-3 flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300"
                >
                  <ExternalLink className="w-4 h-4" />
                  View in Evidence Browser
                </Link>
              </div>
            )}

            {/* Immutability Notice */}
            <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg p-4">
              <h3 className="text-sm font-medium text-amber-400 mb-2">Immutable Record</h3>
              <p className="text-xs text-amber-300/70">
                This snapshot is immutable and cannot be modified. Any changes require creating a new plan version and publishing a new snapshot.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

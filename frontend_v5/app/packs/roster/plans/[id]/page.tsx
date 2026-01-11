'use client';

import { useState, useEffect, use } from 'react';
import Link from 'next/link';
import { ArrowLeft, FileText, Clock, CheckCircle, AlertCircle, Loader2, Upload, History } from 'lucide-react';
import { generateIdempotencyKey, clearIdempotencyKey } from '@/lib/security/idempotency';

interface PlanDetail {
  id: number;
  status: string;
  plan_state: string;
  forecast_version_id: number | null;
  seed: number;
  output_hash: string | null;
  audit_passed_count: number;
  audit_failed_count: number;
  current_snapshot_id: number | null;
  publish_count: number;
  created_at: string;
}

interface SnapshotInfo {
  snapshot_id: string;
  version_number: number;
  status: string;
  published_at: string | null;
  published_by: string;
}

interface AuditEvent {
  action: string | null;
  from_state: string | null;
  to_state: string | null;
  performed_by: string;
  reason: string | null;
  created_at: string | null;
}

interface PlanDetailResponse {
  success: boolean;
  plan: PlanDetail;
  assignments_count: number;
  snapshots: SnapshotInfo[];
  evidence_ref: string | null;
  audit_events: AuditEvent[];
  error?: string;
}

interface PageProps {
  params: Promise<{ id: string }>;
}

export default function PlanDetailPage({ params }: PageProps) {
  const { id } = use(params);
  const [data, setData] = useState<PlanDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    async function fetchPlan() {
      try {
        const response = await fetch(`/api/roster/plans/${id}`);
        const result: PlanDetailResponse = await response.json();

        if (!response.ok) {
          throw new Error(result.error || 'Failed to fetch plan');
        }

        setData(result);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }
    fetchPlan();
  }, [id]);

  async function handlePublish() {
    if (!data) return;

    setPublishing(true);
    try {
      // Generate stable idempotency key based on plan_version_id
      // Same key will be used if user retries a failed request
      const idempotencyKey = generateIdempotencyKey(
        'roster.snapshot.publish',
        data.plan.id
      );

      const response = await fetch('/api/roster/snapshots/publish', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-idempotency-key': idempotencyKey,
        },
        body: JSON.stringify({
          plan_version_id: data.plan.id,
          reason: 'Published from UI',
        }),
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.error || result.detail || 'Failed to publish');
      }

      // Clear the idempotency key on success so next publish can use a new key
      clearIdempotencyKey('roster.snapshot.publish', data.plan.id);

      // Refresh the page data
      window.location.reload();
    } catch (e) {
      // Don't clear key on failure - allow retry with same key
      alert(e instanceof Error ? e.message : 'Publish failed');
    } finally {
      setPublishing(false);
    }
  }

  function getStateColor(state: string) {
    switch (state) {
      case 'PUBLISHED': return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
      case 'APPROVED': return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      case 'SOLVED': return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
      case 'DRAFT': return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
      case 'FAILED': return 'bg-red-500/20 text-red-400 border-red-500/30';
      default: return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 text-slate-400 animate-spin" />
          <p className="text-slate-400">Loading plan...</p>
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
            <p>{error || 'Plan not found'}</p>
          </div>
        </div>
      </div>
    );
  }

  const { plan, assignments_count, snapshots, evidence_ref, audit_events } = data;
  const canPublish = ['APPROVED', 'SOLVED'].includes(plan.plan_state);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <Link href="/packs/roster/plans" className="text-slate-400 hover:text-slate-200 transition-colors">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <FileText className="w-6 h-6 text-slate-500" />
              Plan #{plan.id}
            </h1>
          </div>
          {canPublish && (
            <button
              onClick={handlePublish}
              disabled={publishing}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium text-white transition-colors"
            >
              {publishing ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Upload className="w-4 h-4" />
              )}
              {publishing ? 'Publishing...' : 'Publish Snapshot'}
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Info */}
          <div className="lg:col-span-2 space-y-6">
            {/* Status Card */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Plan Details</h2>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-sm text-slate-500 mb-1">State</p>
                  <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${getStateColor(plan.plan_state)}`}>
                    {plan.plan_state}
                  </span>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Seed</p>
                  <p className="font-mono text-slate-300">{plan.seed}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Assignments</p>
                  <p className="text-slate-300">{assignments_count}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Publish Count</p>
                  <p className="text-slate-300">{plan.publish_count}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Created</p>
                  <p className="text-slate-300">{new Date(plan.created_at).toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500 mb-1">Output Hash</p>
                  <p className="font-mono text-xs text-slate-400 truncate">{plan.output_hash || '-'}</p>
                </div>
              </div>

              {/* Audit Status */}
              <div className="mt-4 pt-4 border-t border-slate-700/50">
                <p className="text-sm text-slate-500 mb-2">Audit Status</p>
                <div className="flex items-center gap-4">
                  <span className="flex items-center gap-1 text-emerald-400">
                    <CheckCircle className="w-4 h-4" />
                    {plan.audit_passed_count} passed
                  </span>
                  <span className="flex items-center gap-1 text-red-400">
                    <AlertCircle className="w-4 h-4" />
                    {plan.audit_failed_count} failed
                  </span>
                </div>
              </div>

              {evidence_ref && (
                <div className="mt-4 pt-4 border-t border-slate-700/50">
                  <p className="text-sm text-slate-500 mb-1">Evidence</p>
                  <p className="font-mono text-xs text-blue-400 truncate">{evidence_ref}</p>
                </div>
              )}
            </div>

            {/* Audit Events */}
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                <History className="w-5 h-5 text-slate-500" />
                Audit Trail
              </h2>
              {audit_events.length === 0 ? (
                <p className="text-slate-500 text-sm">No audit events yet</p>
              ) : (
                <div className="space-y-3">
                  {audit_events.map((event, idx) => (
                    <div key={idx} className="flex items-start gap-3 text-sm">
                      <div className="w-2 h-2 rounded-full bg-slate-500 mt-1.5 shrink-0" />
                      <div className="flex-1">
                        <p className="text-slate-300">
                          <span className="font-medium">{event.performed_by}</span>
                          {event.to_state && (
                            <> changed state to <span className="text-emerald-400">{event.to_state}</span></>
                          )}
                        </p>
                        {event.reason && (
                          <p className="text-slate-500 text-xs mt-1">{event.reason}</p>
                        )}
                        {event.created_at && (
                          <p className="text-slate-600 text-xs">{new Date(event.created_at).toLocaleString()}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Sidebar - Snapshots */}
          <div className="space-y-6">
            <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-6">
              <h2 className="text-lg font-semibold text-white mb-4">Snapshots</h2>
              {snapshots.length === 0 ? (
                <p className="text-slate-500 text-sm">No snapshots published yet</p>
              ) : (
                <div className="space-y-3">
                  {snapshots.map((snapshot) => (
                    <Link
                      key={snapshot.snapshot_id}
                      href={`/packs/roster/snapshots/${snapshot.snapshot_id.split('-')[0]}`}
                      className="block p-3 bg-slate-700/30 hover:bg-slate-700/50 rounded-lg transition-colors"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-medium text-white">v{snapshot.version_number}</span>
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          snapshot.status === 'ACTIVE'
                            ? 'bg-emerald-500/20 text-emerald-400'
                            : 'bg-slate-500/20 text-slate-400'
                        }`}>
                          {snapshot.status}
                        </span>
                      </div>
                      <p className="text-xs text-slate-500">
                        {snapshot.published_at ? new Date(snapshot.published_at).toLocaleString() : '-'}
                      </p>
                      <p className="text-xs text-slate-600">{snapshot.published_by}</p>
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

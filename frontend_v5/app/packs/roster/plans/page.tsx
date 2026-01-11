'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { FileText, Plus, Clock, CheckCircle, AlertCircle, Loader2, ChevronRight } from 'lucide-react';

interface PlanSummary {
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

interface PlansResponse {
  success: boolean;
  plans: PlanSummary[];
  total: number;
  error?: string;
}

export default function PlansListPage() {
  const [plans, setPlans] = useState<PlanSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    async function fetchPlans() {
      try {
        const response = await fetch('/api/roster/plans');
        const data: PlansResponse = await response.json();

        if (!response.ok) {
          throw new Error(data.error || 'Failed to fetch plans');
        }

        setPlans(data.plans || []);
        setTotal(data.total || 0);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    }
    fetchPlans();
  }, []);

  function getStateColor(state: string) {
    switch (state) {
      case 'PUBLISHED': return 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30';
      case 'APPROVED': return 'bg-blue-500/20 text-blue-400 border-blue-500/30';
      case 'SOLVED': return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
      case 'DRAFT': return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
      case 'FAILED': return 'bg-red-500/20 text-red-400 border-red-500/30';
      case 'REJECTED': return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      default: return 'bg-slate-500/20 text-slate-400 border-slate-500/30';
    }
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 text-slate-400 animate-spin" />
          <p className="text-slate-400">Loading plans...</p>
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
            <h1 className="text-2xl font-bold text-white">Plans</h1>
            <p className="text-slate-400 text-sm mt-1">{total} plan version(s)</p>
          </div>
          <Link
            href="/packs/roster/plans/new"
            className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-medium text-white transition-colors"
          >
            <Plus className="w-4 h-4" />
            Create Plan
          </Link>
        </div>

        {/* Empty State */}
        {plans.length === 0 ? (
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg p-12 text-center">
            <FileText className="w-12 h-12 text-slate-600 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-slate-300 mb-2">No plans yet</h3>
            <p className="text-slate-500 mb-6">Create your first plan to get started with scheduling.</p>
            <Link
              href="/packs/roster/plans/new"
              className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-medium text-white transition-colors"
            >
              <Plus className="w-4 h-4" />
              Create Plan
            </Link>
          </div>
        ) : (
          /* Plans Table */
          <div className="bg-slate-800/50 border border-slate-700/50 rounded-lg overflow-hidden">
            <table className="w-full">
              <thead className="bg-slate-800/80">
                <tr>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">ID</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">State</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Seed</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Audit</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Snapshots</th>
                  <th className="text-left p-4 text-sm font-medium text-slate-400">Created</th>
                  <th className="text-right p-4 text-sm font-medium text-slate-400"></th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => (
                  <tr key={plan.id} className="border-t border-slate-700/50 hover:bg-slate-800/30 transition-colors">
                    <td className="p-4">
                      <span className="font-mono text-slate-300">#{plan.id}</span>
                    </td>
                    <td className="p-4">
                      <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium border ${getStateColor(plan.plan_state)}`}>
                        {plan.plan_state}
                      </span>
                    </td>
                    <td className="p-4">
                      <span className="font-mono text-sm text-slate-400">{plan.seed}</span>
                    </td>
                    <td className="p-4">
                      <div className="flex items-center gap-2">
                        {plan.audit_passed_count > 0 && (
                          <span className="flex items-center gap-1 text-emerald-400 text-sm">
                            <CheckCircle className="w-3.5 h-3.5" />
                            {plan.audit_passed_count}
                          </span>
                        )}
                        {plan.audit_failed_count > 0 && (
                          <span className="flex items-center gap-1 text-red-400 text-sm">
                            <AlertCircle className="w-3.5 h-3.5" />
                            {plan.audit_failed_count}
                          </span>
                        )}
                        {plan.audit_passed_count === 0 && plan.audit_failed_count === 0 && (
                          <span className="text-slate-500 text-sm">-</span>
                        )}
                      </div>
                    </td>
                    <td className="p-4">
                      <span className="text-slate-400">{plan.publish_count}</span>
                    </td>
                    <td className="p-4">
                      <div className="flex items-center gap-2 text-slate-400 text-sm">
                        <Clock className="w-3.5 h-3.5" />
                        {new Date(plan.created_at).toLocaleDateString()}
                      </div>
                    </td>
                    <td className="p-4 text-right">
                      <Link
                        href={`/packs/roster/plans/${plan.id}`}
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

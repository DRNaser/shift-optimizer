// =============================================================================
// SOLVEREIGN V4.5 - Audit Log Viewer
// =============================================================================
// View audit log entries with filtering capabilities
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import { ScrollText, Search, RefreshCw, Filter, ChevronDown, X, User, Building2, Clock, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface AuditEntry {
  id: number;
  event_type: string;
  user_id: string | null;
  user_email: string | null;
  tenant_id: number | null;
  target_tenant_id: number | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

interface ApiError {
  error_code?: string;
  message?: string;
  detail?: string;
}

export default function AuditLogViewerPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [eventTypes, setEventTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [total, setTotal] = useState(0);

  // Filters
  const [filterEventType, setFilterEventType] = useState<string>('');
  const [filterUserEmail, setFilterUserEmail] = useState('');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');
  const [showFilters, setShowFilters] = useState(false);

  // Detail drawer
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null);

  const loadEventTypes = async () => {
    try {
      const res = await fetch('/api/audit/event-types');
      const data = await res.json();
      if (res.ok && data.success) {
        setEventTypes(data.event_types || []);
      }
    } catch {
      // Ignore errors loading event types
    }
  };

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set('limit', '100');
      if (filterEventType) params.set('event_type', filterEventType);
      if (filterUserEmail) params.set('user_email', filterUserEmail);
      if (filterDateFrom) params.set('date_from', filterDateFrom);
      if (filterDateTo) params.set('date_to', filterDateTo);

      const res = await fetch(`/api/audit?${params.toString()}`);
      const data = await res.json();

      if (!res.ok) {
        setError({
          error_code: data.error_code || `HTTP_${res.status}`,
          message: data.message || data.detail || 'Failed to load audit log',
        });
        return;
      }

      if (data.success) {
        setEntries(data.entries || []);
        setTotal(data.total || 0);
      }
    } catch (err) {
      setError({
        error_code: 'NETWORK_ERROR',
        message: err instanceof Error ? err.message : 'Failed to load audit log',
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEventTypes();
    loadData();
  }, []);

  const applyFilters = () => {
    loadData();
  };

  const clearFilters = () => {
    setFilterEventType('');
    setFilterUserEmail('');
    setFilterDateFrom('');
    setFilterDateTo('');
    // Reload with cleared filters
    setTimeout(() => loadData(), 0);
  };

  const hasActiveFilters = filterEventType || filterUserEmail || filterDateFrom || filterDateTo;

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const getEventTypeColor = (eventType: string) => {
    if (eventType.includes('login') || eventType.includes('session')) {
      return 'bg-blue-500/10 text-blue-400';
    }
    if (eventType.includes('create') || eventType.includes('publish')) {
      return 'bg-emerald-500/10 text-emerald-400';
    }
    if (eventType.includes('delete') || eventType.includes('revoke')) {
      return 'bg-red-500/10 text-red-400';
    }
    if (eventType.includes('update') || eventType.includes('modify')) {
      return 'bg-amber-500/10 text-amber-400';
    }
    return 'bg-[var(--sv-gray-700)] text-[var(--sv-gray-300)]';
  };

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <ScrollText className="h-6 w-6 text-[var(--sv-primary)]" />
              Audit Log
            </h1>
            <p className="text-[var(--sv-gray-400)] mt-1">
              {total} total entries
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg transition-colors',
                'border',
                hasActiveFilters
                  ? 'bg-[var(--sv-primary)]/10 border-[var(--sv-primary)] text-[var(--sv-primary)]'
                  : 'bg-[var(--sv-gray-800)] border-[var(--sv-gray-700)] text-white hover:bg-[var(--sv-gray-700)]'
              )}
            >
              <Filter className="h-4 w-4" />
              Filters
              {hasActiveFilters && (
                <span className="bg-[var(--sv-primary)] text-white text-xs px-1.5 py-0.5 rounded-full">
                  {[filterEventType, filterUserEmail, filterDateFrom, filterDateTo].filter(Boolean).length}
                </span>
              )}
              <ChevronDown className={cn('h-4 w-4 transition-transform', showFilters && 'rotate-180')} />
            </button>
            <button
              onClick={loadData}
              disabled={loading}
              className={cn(
                'flex items-center gap-2 px-4 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)]',
                'text-white hover:bg-[var(--sv-gray-700)] transition-colors',
                'disabled:opacity-50'
              )}
            >
              <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
              Refresh
            </button>
          </div>
        </div>

        {/* Filters Panel */}
        {showFilters && (
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4 mb-6">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              {/* Event Type */}
              <div>
                <label className="block text-sm text-[var(--sv-gray-400)] mb-1">Event Type</label>
                <select
                  value={filterEventType}
                  onChange={(e) => setFilterEventType(e.target.value)}
                  className={cn(
                    'w-full px-3 py-2 rounded-lg',
                    'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-700)]',
                    'text-white',
                    'focus:outline-none focus:border-[var(--sv-primary)]'
                  )}
                >
                  <option value="">All types</option>
                  {eventTypes.map((type) => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </div>

              {/* User Email */}
              <div>
                <label className="block text-sm text-[var(--sv-gray-400)] mb-1">User Email</label>
                <input
                  type="text"
                  placeholder="Filter by email..."
                  value={filterUserEmail}
                  onChange={(e) => setFilterUserEmail(e.target.value)}
                  className={cn(
                    'w-full px-3 py-2 rounded-lg',
                    'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-700)]',
                    'text-white placeholder-[var(--sv-gray-500)]',
                    'focus:outline-none focus:border-[var(--sv-primary)]'
                  )}
                />
              </div>

              {/* Date From */}
              <div>
                <label className="block text-sm text-[var(--sv-gray-400)] mb-1">From Date</label>
                <input
                  type="date"
                  value={filterDateFrom}
                  onChange={(e) => setFilterDateFrom(e.target.value)}
                  className={cn(
                    'w-full px-3 py-2 rounded-lg',
                    'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-700)]',
                    'text-white',
                    'focus:outline-none focus:border-[var(--sv-primary)]'
                  )}
                />
              </div>

              {/* Date To */}
              <div>
                <label className="block text-sm text-[var(--sv-gray-400)] mb-1">To Date</label>
                <input
                  type="date"
                  value={filterDateTo}
                  onChange={(e) => setFilterDateTo(e.target.value)}
                  className={cn(
                    'w-full px-3 py-2 rounded-lg',
                    'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-700)]',
                    'text-white',
                    'focus:outline-none focus:border-[var(--sv-primary)]'
                  )}
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 mt-4">
              {hasActiveFilters && (
                <button
                  onClick={clearFilters}
                  className="flex items-center gap-1 px-3 py-1.5 text-sm text-[var(--sv-gray-400)] hover:text-white transition-colors"
                >
                  <X className="h-4 w-4" />
                  Clear all
                </button>
              )}
              <button
                onClick={applyFilters}
                className={cn(
                  'flex items-center gap-2 px-4 py-2 rounded-lg',
                  'bg-[var(--sv-primary)] text-white',
                  'hover:bg-[var(--sv-primary)]/90 transition-colors'
                )}
              >
                <Search className="h-4 w-4" />
                Apply Filters
              </button>
            </div>
          </div>
        )}

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 border-4 border-[var(--sv-primary)]/30 border-t-[var(--sv-primary)] rounded-full animate-spin" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
            <div className="text-red-400 font-medium">Failed to load audit log</div>
            <div className="text-red-400/80 text-sm mt-1">
              <span className="font-mono">{error.error_code}</span>: {error.message}
            </div>
          </div>
        )}

        {/* Content */}
        {!loading && !error && (
          <div className="flex gap-6">
            {/* Entries List */}
            <div className={cn(
              'bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden',
              selectedEntry ? 'flex-1' : 'w-full'
            )}>
              {entries.length === 0 ? (
                <div className="p-8 text-center text-[var(--sv-gray-400)]">
                  <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-50" />
                  {hasActiveFilters ? 'No entries match your filters' : 'No audit log entries'}
                </div>
              ) : (
                <div className="divide-y divide-[var(--sv-gray-700)] max-h-[700px] overflow-y-auto">
                  {entries.map((entry) => (
                    <div
                      key={entry.id}
                      onClick={() => setSelectedEntry(entry)}
                      className={cn(
                        'p-4 hover:bg-[var(--sv-gray-700)]/30 transition-colors cursor-pointer',
                        selectedEntry?.id === entry.id && 'bg-[var(--sv-gray-700)]/50'
                      )}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className={cn(
                          'px-2 py-0.5 rounded text-xs font-medium',
                          getEventTypeColor(entry.event_type)
                        )}>
                          {entry.event_type}
                        </span>
                        <span className="flex items-center gap-1 text-xs text-[var(--sv-gray-500)]">
                          <Clock className="h-3 w-3" />
                          {formatDate(entry.created_at)}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 text-sm">
                        {entry.user_email && (
                          <span className="flex items-center gap-1 text-[var(--sv-gray-300)]">
                            <User className="h-3.5 w-3.5 text-[var(--sv-gray-500)]" />
                            {entry.user_email}
                          </span>
                        )}
                        {entry.tenant_id && (
                          <span className="flex items-center gap-1 text-[var(--sv-gray-400)]">
                            <Building2 className="h-3.5 w-3.5 text-[var(--sv-gray-500)]" />
                            Tenant {entry.tenant_id}
                          </span>
                        )}
                        {entry.target_tenant_id && entry.target_tenant_id !== entry.tenant_id && (
                          <span className="text-xs text-purple-400">
                            → Target: Tenant {entry.target_tenant_id}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Detail Drawer */}
            {selectedEntry && (
              <div className="w-96 bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden">
                <div className="border-b border-[var(--sv-gray-700)] px-4 py-3 flex items-center justify-between">
                  <h3 className="font-medium text-white">Entry Details</h3>
                  <button
                    onClick={() => setSelectedEntry(null)}
                    className="p-1 rounded hover:bg-[var(--sv-gray-700)] text-[var(--sv-gray-400)] hover:text-white transition-colors"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <div className="p-4 space-y-4 max-h-[650px] overflow-y-auto">
                  <div>
                    <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">Event ID</label>
                    <p className="text-white font-mono">{selectedEntry.id}</p>
                  </div>
                  <div>
                    <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">Event Type</label>
                    <p className={cn(
                      'inline-block px-2 py-0.5 rounded text-xs font-medium mt-1',
                      getEventTypeColor(selectedEntry.event_type)
                    )}>
                      {selectedEntry.event_type}
                    </p>
                  </div>
                  <div>
                    <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">Timestamp</label>
                    <p className="text-white">{formatDate(selectedEntry.created_at)}</p>
                  </div>
                  {selectedEntry.user_email && (
                    <div>
                      <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">User</label>
                      <p className="text-white">{selectedEntry.user_email}</p>
                      <p className="text-xs text-[var(--sv-gray-500)] font-mono">{selectedEntry.user_id}</p>
                    </div>
                  )}
                  {selectedEntry.tenant_id && (
                    <div>
                      <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">Tenant ID</label>
                      <p className="text-white">{selectedEntry.tenant_id}</p>
                    </div>
                  )}
                  {selectedEntry.target_tenant_id && (
                    <div>
                      <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">Target Tenant ID</label>
                      <p className="text-purple-400">{selectedEntry.target_tenant_id}</p>
                    </div>
                  )}
                  {selectedEntry.ip_address && (
                    <div>
                      <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">IP Address</label>
                      <p className="text-white font-mono text-sm">{selectedEntry.ip_address}</p>
                    </div>
                  )}
                  {selectedEntry.user_agent && (
                    <div>
                      <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">User Agent</label>
                      <p className="text-[var(--sv-gray-400)] text-xs break-all">{selectedEntry.user_agent}</p>
                    </div>
                  )}
                  {selectedEntry.details && Object.keys(selectedEntry.details).length > 0 && (
                    <div>
                      <label className="text-xs text-[var(--sv-gray-500)] uppercase tracking-wider">Details</label>
                      <pre className="mt-1 p-2 bg-[var(--sv-gray-900)] rounded text-xs text-[var(--sv-gray-300)] font-mono overflow-auto max-h-48">
                        {JSON.stringify(selectedEntry.details, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

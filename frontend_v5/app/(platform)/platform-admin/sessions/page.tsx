// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Sessions List
// =============================================================================
// View and manage active sessions.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import { Monitor, Search, RefreshCw, XCircle, Clock, User, Building2 } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Session {
  id: string;
  user_id: string;
  user_email: string;
  tenant_id: number | null;
  site_id: number | null;
  role_name: string;
  created_at: string;
  expires_at: string;
  last_activity_at: string | null;
  is_platform_scope: boolean;
}

interface ApiError {
  error_code?: string;
  message?: string;
  detail?: string;
}

export default function SessionsListPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [revoking, setRevoking] = useState<string | null>(null);

  const loadSessions = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/platform-admin/sessions?active_only=true');
      const data = await res.json();

      if (!res.ok) {
        setError({
          error_code: data.error_code || `HTTP_${res.status}`,
          message: data.message || data.detail || 'Failed to load sessions',
        });
        return;
      }

      setSessions(data);
    } catch (err) {
      setError({
        error_code: 'NETWORK_ERROR',
        message: err instanceof Error ? err.message : 'Failed to load sessions',
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSessions();
  }, []);

  const revokeSession = async (userId: string, userEmail: string) => {
    if (!confirm(`Revoke all sessions for ${userEmail}?`)) return;

    setRevoking(userId);
    try {
      const res = await fetch('/api/platform-admin/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          reason: 'admin_revoke',
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.message || data.detail || 'Failed to revoke sessions');
      }

      // Reload sessions
      await loadSessions();
    } catch (err) {
      alert(err instanceof Error ? err.message : 'Failed to revoke sessions');
    } finally {
      setRevoking(null);
    }
  };

  const filteredSessions = sessions.filter((session) =>
    session.user_email.toLowerCase().includes(searchQuery.toLowerCase()) ||
    session.role_name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const isExpiringSoon = (expiresAt: string) => {
    const expiry = new Date(expiresAt);
    const now = new Date();
    const hoursLeft = (expiry.getTime() - now.getTime()) / (1000 * 60 * 60);
    return hoursLeft < 1;
  };

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <Monitor className="h-6 w-6 text-[var(--sv-primary)]" />
              Active Sessions
            </h1>
            <p className="text-[var(--sv-gray-400)] mt-1">
              Monitor and manage user sessions
            </p>
          </div>
          <button
            onClick={loadSessions}
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

        {/* Search */}
        <div className="mb-6">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[var(--sv-gray-500)]" />
            <input
              type="text"
              placeholder="Search by email or role..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={cn(
                'w-full pl-10 pr-4 py-2 rounded-lg',
                'bg-[var(--sv-gray-800)] border border-[var(--sv-gray-700)]',
                'text-white placeholder-[var(--sv-gray-500)]',
                'focus:outline-none focus:border-[var(--sv-primary)]'
              )}
            />
          </div>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
            <div className="text-[var(--sv-gray-400)] text-sm">Active Sessions</div>
            <div className="text-2xl font-bold text-white mt-1">{sessions.length}</div>
          </div>
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
            <div className="text-[var(--sv-gray-400)] text-sm">Platform Admins</div>
            <div className="text-2xl font-bold text-purple-400 mt-1">
              {sessions.filter(s => s.is_platform_scope).length}
            </div>
          </div>
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
            <div className="text-[var(--sv-gray-400)] text-sm">Expiring Soon</div>
            <div className="text-2xl font-bold text-orange-400 mt-1">
              {sessions.filter(s => isExpiringSoon(s.expires_at)).length}
            </div>
          </div>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <div className="h-8 w-8 border-4 border-[var(--sv-primary)]/30 border-t-[var(--sv-primary)] rounded-full animate-spin" />
          </div>
        )}

        {/* Error State */}
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4">
            <div className="text-red-400 font-medium">Failed to load sessions</div>
            <div className="text-red-400/80 text-sm mt-1">
              <span className="font-mono">{error.error_code}</span>: {error.message}
            </div>
            <div className="text-[var(--sv-gray-500)] text-xs mt-2 font-mono">
              GET /api/platform-admin/sessions
            </div>
          </div>
        )}

        {/* Sessions List */}
        {!loading && !error && (
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] overflow-hidden">
            {filteredSessions.length === 0 ? (
              <div className="p-8 text-center text-[var(--sv-gray-400)]">
                {searchQuery ? 'No sessions match your search' : 'No active sessions'}
              </div>
            ) : (
              <div className="divide-y divide-[var(--sv-gray-700)]">
                {filteredSessions.map((session) => (
                  <div
                    key={session.id}
                    className="flex items-center justify-between p-4 hover:bg-[var(--sv-gray-700)]/30 transition-colors"
                  >
                    <div className="flex items-center gap-4">
                      <div className={cn(
                        'p-2 rounded-lg',
                        session.is_platform_scope ? 'bg-purple-500/10' : 'bg-blue-500/10'
                      )}>
                        <User className={cn(
                          'h-5 w-5',
                          session.is_platform_scope ? 'text-purple-400' : 'text-blue-400'
                        )} />
                      </div>
                      <div>
                        <div className="font-medium text-white">{session.user_email}</div>
                        <div className="flex items-center gap-3 text-sm text-[var(--sv-gray-400)]">
                          <span className={cn(
                            'px-1.5 py-0.5 rounded text-xs',
                            session.is_platform_scope
                              ? 'bg-purple-500/10 text-purple-400'
                              : 'bg-blue-500/10 text-blue-400'
                          )}>
                            {session.role_name}
                          </span>
                          {session.tenant_id && (
                            <span className="flex items-center gap-1">
                              <Building2 className="h-3 w-3" />
                              Tenant {session.tenant_id}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="text-right text-sm">
                        <div className="flex items-center gap-1 text-[var(--sv-gray-400)]">
                          <Clock className="h-3 w-3" />
                          Created: {formatDate(session.created_at)}
                        </div>
                        <div className={cn(
                          'text-xs mt-0.5',
                          isExpiringSoon(session.expires_at) ? 'text-orange-400' : 'text-[var(--sv-gray-500)]'
                        )}>
                          Expires: {formatDate(session.expires_at)}
                        </div>
                      </div>
                      <button
                        onClick={() => revokeSession(session.user_id, session.user_email)}
                        disabled={revoking === session.user_id}
                        className={cn(
                          'p-2 rounded-lg text-red-400 hover:bg-red-500/10 transition-colors',
                          'disabled:opacity-50'
                        )}
                        title="Revoke all sessions for this user"
                      >
                        {revoking === session.user_id ? (
                          <div className="h-4 w-4 border-2 border-red-400/30 border-t-red-400 rounded-full animate-spin" />
                        ) : (
                          <XCircle className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

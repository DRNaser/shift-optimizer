// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Home
// =============================================================================
// Dashboard for platform administrators.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Building2, Users, Settings, Activity, Shield, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';

interface DashboardStats {
  tenantCount: number;
  userCount: number;
  activeSessionCount: number;
}

export default function PlatformAdminHome() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadStats() {
      try {
        const [tenantsRes, usersRes, sessionsRes] = await Promise.all([
          fetch('/api/platform-admin/tenants?include_counts=true'),
          fetch('/api/platform-admin/users'),
          fetch('/api/platform-admin/sessions?active_only=true'),
        ]);

        const tenants = tenantsRes.ok ? await tenantsRes.json() : [];
        const users = usersRes.ok ? await usersRes.json() : [];
        const sessions = sessionsRes.ok ? await sessionsRes.json() : [];

        setStats({
          tenantCount: Array.isArray(tenants) ? tenants.length : 0,
          userCount: Array.isArray(users) ? users.length : 0,
          activeSessionCount: Array.isArray(sessions) ? sessions.length : 0,
        });
      } catch (error) {
        console.error('Failed to load stats:', error);
      } finally {
        setLoading(false);
      }
    }

    loadStats();
  }, []);

  const quickActions = [
    {
      title: 'Tenants',
      description: 'Manage tenants and their configurations',
      href: '/platform-admin/tenants',
      icon: Building2,
      color: 'bg-blue-500/10 text-blue-400',
    },
    {
      title: 'Users',
      description: 'Manage users and role assignments',
      href: '/platform-admin/users',
      icon: Users,
      color: 'bg-green-500/10 text-green-400',
    },
    {
      title: 'System Settings',
      description: 'Configure platform-wide settings',
      href: '/platform-admin/settings',
      icon: Settings,
      color: 'bg-purple-500/10 text-purple-400',
    },
  ];

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-[var(--sv-primary)]/10">
              <Shield className="h-6 w-6 text-[var(--sv-primary)]" />
            </div>
            <h1 className="text-2xl font-bold text-white">Platform Administration</h1>
          </div>
          <p className="text-[var(--sv-gray-400)]">
            Manage tenants, users, and platform-wide settings
          </p>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-blue-500/10">
                <Building2 className="h-5 w-5 text-blue-400" />
              </div>
              <div>
                <p className="text-sm text-[var(--sv-gray-400)]">Tenants</p>
                <p className="text-2xl font-bold text-white">
                  {loading ? '...' : stats?.tenantCount || 0}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-green-500/10">
                <Users className="h-5 w-5 text-green-400" />
              </div>
              <div>
                <p className="text-sm text-[var(--sv-gray-400)]">Users</p>
                <p className="text-2xl font-bold text-white">
                  {loading ? '...' : stats?.userCount || 0}
                </p>
              </div>
            </div>
          </div>

          <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-lg bg-yellow-500/10">
                <Activity className="h-5 w-5 text-yellow-400" />
              </div>
              <div>
                <p className="text-sm text-[var(--sv-gray-400)]">Active Sessions</p>
                <p className="text-2xl font-bold text-white">
                  {loading ? '...' : stats?.activeSessionCount || 0}
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Quick Actions */}
        <h2 className="text-lg font-semibold text-white mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          {quickActions.map((action) => (
            <Link
              key={action.href}
              href={action.href}
              className={cn(
                'bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-4',
                'hover:border-[var(--sv-primary)]/50 transition-colors'
              )}
            >
              <div className="flex items-start gap-3">
                <div className={cn('p-2 rounded-lg', action.color)}>
                  <action.icon className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="font-medium text-white">{action.title}</h3>
                  <p className="text-sm text-[var(--sv-gray-400)]">{action.description}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>

        {/* Quick Create Buttons */}
        <h2 className="text-lg font-semibold text-white mb-4">Quick Create</h2>
        <div className="flex gap-4">
          <Link
            href="/platform-admin/tenants/new"
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg',
              'bg-[var(--sv-primary)] text-white',
              'hover:bg-[var(--sv-primary-dark)] transition-colors'
            )}
          >
            <Plus className="h-4 w-4" />
            New Tenant
          </Link>
          <Link
            href="/platform-admin/users/new"
            className={cn(
              'flex items-center gap-2 px-4 py-2 rounded-lg',
              'bg-[var(--sv-gray-700)] text-white',
              'hover:bg-[var(--sv-gray-600)] transition-colors'
            )}
          >
            <Plus className="h-4 w-4" />
            New User
          </Link>
        </div>
      </div>
    </div>
  );
}

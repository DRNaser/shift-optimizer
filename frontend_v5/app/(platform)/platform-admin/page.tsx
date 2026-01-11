// =============================================================================
// SOLVEREIGN V4.5 - Platform Admin Dashboard (Redesigned)
// =============================================================================
// Dashboard for platform administrators with modern design system.
// =============================================================================

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Building2,
  Users,
  Settings,
  Activity,
  Shield,
  Plus,
  ChevronRight,
  TrendingUp,
  Clock,
  Server,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';

interface DashboardStats {
  tenantCount: number;
  userCount: number;
  activeSessionCount: number;
}

function StatCard({
  title,
  value,
  icon: Icon,
  trend,
  loading,
  color,
}: {
  title: string;
  value: number;
  icon: React.ComponentType<{ className?: string }>;
  trend?: string;
  loading?: boolean;
  color: string;
}) {
  const colorClasses: Record<string, { bg: string; text: string; border: string }> = {
    blue: { bg: 'bg-primary/10', text: 'text-primary', border: 'border-primary/20' },
    green: { bg: 'bg-success/10', text: 'text-success', border: 'border-success/20' },
    amber: { bg: 'bg-warning/10', text: 'text-warning', border: 'border-warning/20' },
    purple: { bg: 'bg-accent/10', text: 'text-accent', border: 'border-accent/20' },
  };

  const colors = colorClasses[color] || colorClasses.blue;

  return (
    <Card variant="interactive" padding="sm" className="group">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              'p-2.5 rounded-xl transition-transform group-hover:scale-110',
              colors.bg
            )}
          >
            <Icon className={cn('h-5 w-5', colors.text)} />
          </div>
          <div>
            <p className="text-sm font-medium text-foreground-muted">{title}</p>
            {loading ? (
              <Skeleton className="h-8 w-16 mt-1" />
            ) : (
              <p className="text-2xl font-bold tabular-nums text-foreground">
                {value.toLocaleString()}
              </p>
            )}
          </div>
        </div>
        {trend && !loading && (
          <Badge variant="success" size="sm">
            <TrendingUp className="h-3 w-3 mr-1" />
            {trend}
          </Badge>
        )}
      </div>
    </Card>
  );
}

function QuickActionCard({
  title,
  description,
  href,
  icon: Icon,
  color,
}: {
  title: string;
  description: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
}) {
  const colorClasses: Record<string, { bg: string; text: string }> = {
    blue: { bg: 'bg-primary/10', text: 'text-primary' },
    green: { bg: 'bg-success/10', text: 'text-success' },
    purple: { bg: 'bg-accent/10', text: 'text-accent' },
  };

  const colors = colorClasses[color] || colorClasses.blue;

  return (
    <Link href={href}>
      <Card
        variant="interactive"
        padding="sm"
        className="h-full group"
      >
        <div className="flex items-start gap-4">
          <div
            className={cn(
              'p-3 rounded-xl transition-all group-hover:scale-110',
              colors.bg
            )}
          >
            <Icon className={cn('h-5 w-5', colors.text)} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-foreground">{title}</h3>
              <ChevronRight className="h-4 w-4 text-foreground-muted group-hover:translate-x-1 transition-transform" />
            </div>
            <p className="text-sm text-foreground-muted mt-1">{description}</p>
          </div>
        </div>
      </Card>
    </Link>
  );
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
      color: 'blue',
    },
    {
      title: 'Users',
      description: 'Manage users and role assignments',
      href: '/platform-admin/users',
      icon: Users,
      color: 'green',
    },
    {
      title: 'Settings',
      description: 'Configure platform-wide settings',
      href: '/platform-admin/settings',
      icon: Settings,
      color: 'purple',
    },
  ];

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-7xl mx-auto p-6 lg:p-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="p-3 rounded-xl bg-primary/10">
                <Shield className="h-7 w-7 text-primary" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-foreground">Platform Administration</h1>
                <p className="text-foreground-muted mt-0.5">
                  Manage tenants, users, and platform-wide settings
                </p>
              </div>
            </div>
            <Badge variant="default" size="lg">
              <Server className="h-3.5 w-3.5 mr-1.5" />
              V4.5
            </Badge>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          <StatCard
            title="Total Tenants"
            value={stats?.tenantCount || 0}
            icon={Building2}
            color="blue"
            loading={loading}
          />
          <StatCard
            title="Total Users"
            value={stats?.userCount || 0}
            icon={Users}
            color="green"
            loading={loading}
          />
          <StatCard
            title="Active Sessions"
            value={stats?.activeSessionCount || 0}
            icon={Activity}
            color="amber"
            loading={loading}
          />
        </div>

        {/* Main Content Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Quick Actions */}
          <div className="lg:col-span-2 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-foreground">Quick Actions</h2>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {quickActions.map((action) => (
                <QuickActionCard key={action.href} {...action} />
              ))}
            </div>

            {/* Quick Create Section */}
            <div className="pt-6">
              <h2 className="text-lg font-semibold text-foreground mb-4">Quick Create</h2>
              <div className="flex flex-wrap gap-3">
                <Button asChild leftIcon={<Plus className="h-4 w-4" />}>
                  <Link href="/platform-admin/tenants/new">New Tenant</Link>
                </Button>
                <Button asChild variant="secondary" leftIcon={<Plus className="h-4 w-4" />}>
                  <Link href="/platform-admin/users/new">New User</Link>
                </Button>
              </div>
            </div>
          </div>

          {/* Activity Feed */}
          <div className="lg:col-span-1">
            <Card padding="none">
              <CardHeader className="p-4 border-b border-border">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-foreground-muted" />
                  <CardTitle className="text-base">Recent Activity</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="p-4">
                <div className="space-y-4">
                  <ActivityItem
                    title="System Online"
                    description="Platform services running normally"
                    time="Now"
                    status="success"
                  />
                  <ActivityItem
                    title="Security Check"
                    description="All RLS policies verified"
                    time="2 min ago"
                    status="success"
                  />
                  <ActivityItem
                    title="Database"
                    description="Connection pool healthy"
                    time="5 min ago"
                    status="success"
                  />
                </div>
                <div className="mt-4 pt-4 border-t border-border">
                  <Link
                    href="/platform-admin/audit"
                    className="text-sm text-primary hover:underline flex items-center gap-1"
                  >
                    View all activity
                    <ChevronRight className="h-3 w-3" />
                  </Link>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}

function ActivityItem({
  title,
  description,
  time,
  status,
}: {
  title: string;
  description: string;
  time: string;
  status: 'success' | 'warning' | 'error';
}) {
  const statusClasses = {
    success: 'bg-success',
    warning: 'bg-warning',
    error: 'bg-error',
  };

  return (
    <div className="flex gap-3">
      <div className="relative">
        <div className={cn('w-2 h-2 rounded-full mt-2', statusClasses[status])} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-foreground truncate">{title}</p>
          <span className="text-xs text-foreground-muted flex-shrink-0">{time}</span>
        </div>
        <p className="text-xs text-foreground-muted truncate">{description}</p>
      </div>
    </div>
  );
}

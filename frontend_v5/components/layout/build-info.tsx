// =============================================================================
// SOLVEREIGN Build Info Component
// =============================================================================
// Displays environment, git SHA, and app version from build metadata.
// Single source of truth for version display across the platform.
// =============================================================================

'use client';

import { useState, useEffect } from 'react';
import { Info } from 'lucide-react';
import { cn } from '@/lib/utils';

interface BuildInfo {
  env: 'local' | 'staging' | 'prod';
  version: string;
  gitSha: string;
  buildTime?: string;
}

// Environment colors
const ENV_COLORS = {
  local: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  staging: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  prod: 'bg-green-500/20 text-green-400 border-green-500/30',
};

const ENV_LABELS = {
  local: 'LOCAL',
  staging: 'STAGING',
  prod: 'PROD',
};

export function BuildInfo({ className }: { className?: string }) {
  const [info, setInfo] = useState<BuildInfo | null>(null);

  useEffect(() => {
    // Fetch build info from API or use env vars
    const fetchBuildInfo = async () => {
      try {
        const res = await fetch('/api/build-info');
        if (res.ok) {
          const data = await res.json();
          setInfo(data);
        } else {
          // Fallback to client-side detection
          setInfo({
            env: detectEnvironment(),
            version: process.env.NEXT_PUBLIC_APP_VERSION || '4.6.0',
            gitSha: process.env.NEXT_PUBLIC_GIT_SHA || 'dev',
          });
        }
      } catch {
        setInfo({
          env: detectEnvironment(),
          version: process.env.NEXT_PUBLIC_APP_VERSION || '4.6.0',
          gitSha: process.env.NEXT_PUBLIC_GIT_SHA || 'dev',
        });
      }
    };
    fetchBuildInfo();
  }, []);

  if (!info) return null;

  return (
    <div className={cn('flex items-center gap-2 text-xs', className)}>
      {/* Environment Badge */}
      <span className={cn(
        'px-2 py-0.5 rounded border font-medium',
        ENV_COLORS[info.env]
      )}>
        {ENV_LABELS[info.env]}
      </span>

      {/* Version + SHA */}
      <span className="text-[var(--sv-gray-500)]">
        v{info.version}
        <span className="mx-1">·</span>
        <code className="font-mono">{info.gitSha.slice(0, 7)}</code>
      </span>
    </div>
  );
}

// Compact version for footer
export function BuildInfoCompact({ className }: { className?: string }) {
  const [info, setInfo] = useState<BuildInfo | null>(null);

  useEffect(() => {
    const fetchBuildInfo = async () => {
      try {
        const res = await fetch('/api/build-info');
        if (res.ok) {
          setInfo(await res.json());
        } else {
          setInfo({
            env: detectEnvironment(),
            version: process.env.NEXT_PUBLIC_APP_VERSION || '4.6.0',
            gitSha: process.env.NEXT_PUBLIC_GIT_SHA || 'dev',
          });
        }
      } catch {
        setInfo({
          env: detectEnvironment(),
          version: process.env.NEXT_PUBLIC_APP_VERSION || '4.6.0',
          gitSha: process.env.NEXT_PUBLIC_GIT_SHA || 'dev',
        });
      }
    };
    fetchBuildInfo();
  }, []);

  if (!info) return null;

  return (
    <p className={cn('text-xs text-slate-500 text-center', className)}>
      SOLVEREIGN Platform v{info.version} | {ENV_LABELS[info.env]} | {info.gitSha.slice(0, 7)}
    </p>
  );
}

// Detect environment from hostname
function detectEnvironment(): 'local' | 'staging' | 'prod' {
  if (typeof window === 'undefined') return 'local';

  const hostname = window.location.hostname;
  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    return 'local';
  }
  if (hostname.includes('staging') || hostname.includes('test')) {
    return 'staging';
  }
  return 'prod';
}

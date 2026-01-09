// =============================================================================
// SOLVEREIGN Platform Login Page
// =============================================================================
// Login page for platform administration.
// TODO: Integrate with Entra ID for production.
// =============================================================================

'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { Shield, LogIn, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = searchParams.get('returnTo') || '/platform/orgs';

  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      // TODO: Replace with real Entra ID auth flow
      // For now, set dev cookies via API
      const res = await fetch('/api/platform/auth/dev-login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error?.message || 'Login failed');
      }

      // Redirect to return URL
      router.push(returnTo);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[var(--sv-gray-900)] flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        {/* Logo / Branding */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-[var(--sv-primary)]/10 mb-4">
            <Shield className="h-8 w-8 text-[var(--sv-primary)]" />
          </div>
          <h1 className="text-2xl font-bold text-white">SOLVEREIGN Platform</h1>
          <p className="text-sm text-[var(--sv-gray-400)] mt-1">
            Platform Administration Login
          </p>
        </div>

        {/* Login Form */}
        <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-6">
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Email Address
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@solvereign.com"
                className={cn(
                  'w-full px-3 py-2 rounded-lg',
                  'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                  'text-white placeholder-[var(--sv-gray-500)]',
                  'focus:outline-none focus:border-[var(--sv-primary)]'
                )}
                required
              />
            </div>

            {error && (
              <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !email}
              className={cn(
                'w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg',
                'bg-[var(--sv-primary)] text-white font-medium',
                'hover:bg-[var(--sv-primary-dark)] transition-colors',
                'disabled:opacity-50 disabled:cursor-not-allowed'
              )}
            >
              {loading ? (
                <>
                  <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Signing in...
                </>
              ) : (
                <>
                  <LogIn className="h-4 w-4" />
                  Sign In
                </>
              )}
            </button>
          </form>

          {/* Entra ID SSO Button (TODO) */}
          <div className="mt-6 pt-6 border-t border-[var(--sv-gray-700)]">
            <button
              type="button"
              disabled
              className={cn(
                'w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg',
                'bg-[var(--sv-gray-700)] text-[var(--sv-gray-400)]',
                'cursor-not-allowed'
              )}
            >
              <svg className="h-4 w-4" viewBox="0 0 21 21" fill="currentColor">
                <path d="M0 0h10v10H0zM11 0h10v10H11zM0 11h10v10H0zM11 11h10v10H11z" />
              </svg>
              Sign in with Microsoft Entra ID
              <span className="text-xs">(Coming Soon)</span>
            </button>
          </div>
        </div>

        {/* Help Text */}
        <p className="text-center text-xs text-[var(--sv-gray-500)] mt-4">
          Contact IT support if you need access to platform administration.
        </p>
      </div>
    </div>
  );
}

export default function PlatformLoginPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-[var(--sv-gray-900)] flex items-center justify-center">
        <div className="h-8 w-8 border-4 border-[var(--sv-primary)]/30 border-t-[var(--sv-primary)] rounded-full animate-spin" />
      </div>
    }>
      <LoginForm />
    </Suspense>
  );
}

// =============================================================================
// SOLVEREIGN V4.4 - Platform Login Page
// =============================================================================
// Login page for platform administration using internal RBAC.
// Email + Password authentication with HttpOnly session cookie.
// =============================================================================

'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { Shield, LogIn, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { cn } from '@/lib/utils';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const returnTo = searchParams.get('returnTo') || '/platform/home';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
      });

      const data = await res.json();

      if (!res.ok) {
        // Handle specific error codes
        if (data.error_code === 'INVALID_CREDENTIALS') {
          throw new Error('Ungültige E-Mail oder Passwort');
        } else if (data.error_code === 'ACCOUNT_LOCKED') {
          throw new Error('Konto gesperrt. Bitte kontaktieren Sie den Administrator.');
        } else if (data.error_code === 'ACCOUNT_INACTIVE') {
          throw new Error('Konto inaktiv. Bitte kontaktieren Sie den Administrator.');
        } else {
          throw new Error(data.message || 'Anmeldung fehlgeschlagen');
        }
      }

      // Redirect to return URL on success
      router.push(returnTo);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Anmeldung fehlgeschlagen');
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
            Portal Administration
          </p>
        </div>

        {/* Login Form */}
        <div className="bg-[var(--sv-gray-800)] rounded-lg border border-[var(--sv-gray-700)] p-6">
          <form onSubmit={handleLogin} className="space-y-4">
            {/* Email Field */}
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                E-Mail-Adresse
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@example.com"
                autoComplete="email"
                className={cn(
                  'w-full px-3 py-2 rounded-lg',
                  'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                  'text-white placeholder-[var(--sv-gray-500)]',
                  'focus:outline-none focus:border-[var(--sv-primary)]'
                )}
                required
              />
            </div>

            {/* Password Field */}
            <div>
              <label className="block text-sm font-medium text-[var(--sv-gray-300)] mb-1">
                Passwort
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  className={cn(
                    'w-full px-3 py-2 pr-10 rounded-lg',
                    'bg-[var(--sv-gray-900)] border border-[var(--sv-gray-600)]',
                    'text-white placeholder-[var(--sv-gray-500)]',
                    'focus:outline-none focus:border-[var(--sv-primary)]'
                  )}
                  required
                  minLength={8}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--sv-gray-400)] hover:text-white"
                >
                  {showPassword ? (
                    <EyeOff className="h-5 w-5" />
                  ) : (
                    <Eye className="h-5 w-5" />
                  )}
                </button>
              </div>
            </div>

            {/* Error Message */}
            {error && (
              <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg p-3">
                <AlertCircle className="h-4 w-4 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading || !email || !password}
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
                  Anmeldung...
                </>
              ) : (
                <>
                  <LogIn className="h-4 w-4" />
                  Anmelden
                </>
              )}
            </button>
          </form>
        </div>

        {/* Help Text */}
        <p className="text-center text-xs text-[var(--sv-gray-500)] mt-4">
          Kontaktieren Sie Ihren Administrator für Zugangsdaten.
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

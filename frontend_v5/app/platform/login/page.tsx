// =============================================================================
// SOLVEREIGN V4.5 - Platform Login Page (Redesigned)
// =============================================================================
// Professional login page with modern design system.
// Email + Password authentication with HttpOnly session cookie.
// =============================================================================

'use client';

import { useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense } from 'react';
import { Shield, LogIn, AlertCircle, Eye, EyeOff, Lock, Mail, ArrowRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Spinner } from '@/components/ui/spinner';

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

      router.push(returnTo);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Anmeldung fehlgeschlagen');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left Panel - Branding */}
      <div className="hidden lg:flex lg:w-1/2 xl:w-[55%] bg-gradient-to-br from-primary via-primary-hover to-accent relative overflow-hidden">
        {/* Decorative elements */}
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-20 left-20 w-64 h-64 rounded-full bg-white blur-3xl" />
          <div className="absolute bottom-40 right-20 w-96 h-96 rounded-full bg-white blur-3xl" />
        </div>

        {/* Grid pattern overlay */}
        <div
          className="absolute inset-0 opacity-5"
          style={{
            backgroundImage: `linear-gradient(rgba(255,255,255,0.1) 1px, transparent 1px),
                              linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px)`,
            backgroundSize: '60px 60px',
          }}
        />

        {/* Content */}
        <div className="relative z-10 flex flex-col justify-center px-12 xl:px-20 text-white">
          <div className="mb-8">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-xl bg-white/20 backdrop-blur-sm mb-6">
              <Shield className="h-7 w-7 text-white" />
            </div>
            <h1 className="text-4xl xl:text-5xl font-bold mb-4 leading-tight">
              SOLVEREIGN
            </h1>
            <p className="text-xl xl:text-2xl text-white/80 font-light">
              Enterprise Shift Optimization
            </p>
          </div>

          <div className="space-y-6 mt-8">
            <FeatureItem
              icon={<Lock className="h-5 w-5" />}
              title="Secure by Design"
              description="Multi-tenant isolation with enterprise-grade security"
            />
            <FeatureItem
              icon={<Shield className="h-5 w-5" />}
              title="Role-Based Access"
              description="Granular permissions for every operation"
            />
          </div>

          <div className="mt-auto pt-12">
            <p className="text-sm text-white/50">
              V4.5 | SaaS Admin Core
            </p>
          </div>
        </div>
      </div>

      {/* Right Panel - Login Form */}
      <div className="flex-1 flex items-center justify-center p-6 sm:p-8 lg:p-12 bg-background">
        <div className="w-full max-w-md animate-fade-in">
          {/* Mobile Logo */}
          <div className="lg:hidden text-center mb-8">
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-xl bg-primary/10 mb-4">
              <Shield className="h-7 w-7 text-primary" />
            </div>
            <h1 className="text-2xl font-bold text-foreground">SOLVEREIGN</h1>
            <p className="text-sm text-foreground-muted mt-1">Platform Administration</p>
          </div>

          {/* Login Card */}
          <Card variant="elevated" className="p-8">
            <div className="mb-6">
              <h2 className="text-xl font-semibold text-foreground">Willkommen</h2>
              <p className="text-sm text-foreground-muted mt-1">
                Melden Sie sich an, um fortzufahren
              </p>
            </div>

            <form onSubmit={handleLogin} className="space-y-5">
              {/* Email Field */}
              <div className="space-y-2">
                <Label htmlFor="email">E-Mail-Adresse</Label>
                <Input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="email@example.com"
                  autoComplete="email"
                  leftIcon={<Mail className="h-4 w-4" />}
                  error={!!error}
                  required
                />
              </div>

              {/* Password Field */}
              <div className="space-y-2">
                <Label htmlFor="password">Passwort</Label>
                <div className="relative">
                  <Input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Ihr Passwort eingeben"
                    autoComplete="current-password"
                    leftIcon={<Lock className="h-4 w-4" />}
                    error={!!error}
                    required
                    minLength={8}
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-foreground-muted hover:text-foreground transition-colors"
                    tabIndex={-1}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>

              {/* Error Message */}
              {error && (
                <div className="flex items-start gap-3 text-sm bg-error-light text-error border border-error/20 rounded-lg p-3 animate-fade-in">
                  <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                  <span>{error}</span>
                </div>
              )}

              {/* Submit Button */}
              <Button
                type="submit"
                size="lg"
                className="w-full"
                disabled={loading || !email || !password}
                isLoading={loading}
                rightIcon={!loading && <ArrowRight className="h-4 w-4" />}
              >
                {loading ? 'Anmeldung...' : 'Anmelden'}
              </Button>
            </form>
          </Card>

          {/* Help Text */}
          <p className="text-center text-sm text-foreground-muted mt-6">
            Kontaktieren Sie Ihren Administrator für Zugangsdaten.
          </p>
        </div>
      </div>
    </div>
  );
}

function FeatureItem({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-4">
      <div className="flex-shrink-0 w-10 h-10 rounded-lg bg-white/10 backdrop-blur-sm flex items-center justify-center">
        {icon}
      </div>
      <div>
        <h3 className="font-medium text-white">{title}</h3>
        <p className="text-sm text-white/60 mt-0.5">{description}</p>
      </div>
    </div>
  );
}

export default function PlatformLoginPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <LoginForm />
    </Suspense>
  );
}

function LoadingState() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <Spinner size="lg" />
        <p className="text-sm text-foreground-muted">Laden...</p>
      </div>
    </div>
  );
}

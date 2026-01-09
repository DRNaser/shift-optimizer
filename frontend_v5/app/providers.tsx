// =============================================================================
// SOLVEREIGN Application Providers
// =============================================================================
// Root providers wrapper for the application.
// Includes: Authentication (Entra ID), Tenant context
// =============================================================================

'use client';

import { type ReactNode } from 'react';
import { AuthProvider } from '@/lib/auth';
import { TenantProvider } from '@/lib/hooks/use-tenant';

interface ProvidersProps {
  children: ReactNode;
}

export function Providers({ children }: ProvidersProps) {
  return (
    <AuthProvider>
      <TenantProvider>
        {children}
      </TenantProvider>
    </AuthProvider>
  );
}

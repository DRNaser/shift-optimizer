// =============================================================================
// SOLVEREIGN Tenant Context Hook
// =============================================================================
// React Context for multi-tenant state management.
//
// SECURITY ARCHITECTURE:
// - Tenant/Site context is SERVER-AUTHORITATIVE via /api/tenant/me
// - Browser reads from BFF, never from localStorage as source of truth
// - Site switching requires server ACK before UI updates
// - All data flows: Browser → BFF (session cookie) → Backend
// =============================================================================

'use client';

import {
  createContext,
  useContext,
  useCallback,
  useMemo,
  useReducer,
  useEffect,
  useState,
  type ReactNode,
} from 'react';

import type {
  Tenant,
  Site,
  User,
  Pack,
  PackId,
  Permission,
  TenantContext,
  TenantContextState,
  TenantMeResponse,
} from '../tenant-types';

// =============================================================================
// CONTEXT
// =============================================================================

const TenantCtx = createContext<TenantContext | null>(null);

// =============================================================================
// REDUCER
// =============================================================================

type TenantAction =
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_SWITCHING_SITE'; payload: boolean }
  | { type: 'SET_ERROR'; payload: Error | null }
  | { type: 'SET_TENANT_DATA'; payload: TenantMeResponse }
  | { type: 'SET_CURRENT_SITE'; payload: Site }
  | { type: 'CLEAR' };

interface ExtendedTenantContextState extends TenantContextState {
  isSwitchingSite: boolean;
}

const initialState: ExtendedTenantContextState = {
  tenant: null,
  sites: [],
  currentSite: null,
  user: null,
  enabledPacks: [],
  isLoading: true,
  isSwitchingSite: false,
  error: null,
};

function tenantReducer(state: ExtendedTenantContextState, action: TenantAction): ExtendedTenantContextState {
  switch (action.type) {
    case 'SET_LOADING':
      return { ...state, isLoading: action.payload };

    case 'SET_SWITCHING_SITE':
      return { ...state, isSwitchingSite: action.payload };

    case 'SET_ERROR':
      return { ...state, error: action.payload, isLoading: false, isSwitchingSite: false };

    case 'SET_TENANT_DATA': {
      const { tenant, sites, user, enabled_packs, current_site_id } = action.payload;

      // Build enabled packs - Core is ALWAYS enabled
      const enabledPacks = buildEnabledPacks(enabled_packs);

      // CRITICAL: Current site comes from SERVER, not localStorage
      // Server returns current_site_id based on session state
      const currentSite = current_site_id
        ? sites.find((s) => s.id === current_site_id) || sites[0]
        : sites[0] || null;

      return {
        ...state,
        tenant,
        sites,
        currentSite,
        user,
        enabledPacks,
        isLoading: false,
        isSwitchingSite: false,
        error: null,
      };
    }

    case 'SET_CURRENT_SITE': {
      return { ...state, currentSite: action.payload, isSwitchingSite: false };
    }

    case 'CLEAR':
      return initialState;

    default:
      return state;
  }
}

// =============================================================================
// PACK REGISTRY (Core is ALWAYS included)
// =============================================================================

function buildEnabledPacks(enabledPackIds: PackId[]): Pack[] {
  const REGISTRY: Record<PackId, Omit<Pack, 'is_enabled'>> = {
    // CORE: Always enabled, contains Audits/Lock/Freeze/Evidence/Repair
    core: {
      id: 'core',
      name: 'SOLVEREIGN Core',
      description: 'Shift scheduling, audits, lock/freeze, evidence, repair',
      icon: 'Calendar',
      entitlements: ['scenarios', 'plans', 'audits', 'evidence', 'lock', 'freeze', 'repair'],
      version: '3.3',
    },
    // OPTIONAL PACKS: Domain-specific extensions
    routing: {
      id: 'routing',
      name: 'Routing Pack',
      description: 'Vehicle routing and tour optimization',
      icon: 'MapPin',
      entitlements: ['routing-scenarios', 'routes', 'depots'],
      version: '1.0',
    },
    forecasting: {
      id: 'forecasting',
      name: 'Forecasting Pack',
      description: 'Demand forecasting and capacity planning',
      icon: 'TrendingUp',
      entitlements: ['forecasts', 'predictions', 'capacity'],
      version: '0.9',
    },
    compliance: {
      id: 'compliance',
      name: 'Compliance Dashboard',
      description: 'Extended compliance reporting (domain-specific audit rules)',
      icon: 'Shield',
      entitlements: ['compliance-dashboard', 'labor-law-reports'],
      version: '1.0',
    },
  };

  // Core is ALWAYS included, regardless of enabled_packs
  const packs: Pack[] = [{ ...REGISTRY.core, is_enabled: true }];

  // Add optional packs if enabled
  for (const packId of enabledPackIds) {
    if (packId !== 'core' && packId in REGISTRY) {
      packs.push({ ...REGISTRY[packId], is_enabled: true });
    }
  }

  return packs;
}

// =============================================================================
// PROVIDER
// =============================================================================

interface TenantProviderProps {
  children: ReactNode;
  initialData?: TenantMeResponse;
}

export function TenantProvider({ children, initialData }: TenantProviderProps) {
  const [state, dispatch] = useReducer(tenantReducer, initialState);

  // Fetch tenant data on mount (if not provided via SSR)
  useEffect(() => {
    if (initialData) {
      dispatch({ type: 'SET_TENANT_DATA', payload: initialData });
      return;
    }

    const fetchTenantData = async () => {
      try {
        dispatch({ type: 'SET_LOADING', payload: true });

        // BFF endpoint extracts tenant from __Host-sv_tenant cookie
        // Returns current_site_id from server session
        const res = await fetch('/api/tenant/me', {
          credentials: 'include', // Send __Host- cookies
        });

        if (!res.ok) {
          if (res.status === 401) {
            window.location.href = '/login';
            return;
          }
          throw new Error(`Failed to fetch tenant: ${res.status}`);
        }

        const data: TenantMeResponse = await res.json();
        dispatch({ type: 'SET_TENANT_DATA', payload: data });
      } catch (err) {
        dispatch({ type: 'SET_ERROR', payload: err instanceof Error ? err : new Error(String(err)) });
      }
    };

    fetchTenantData();
  }, [initialData]);

  // ==========================================================================
  // SITE SWITCHING - SERVER AUTHORITATIVE
  // ==========================================================================
  // CRITICAL: Site switch is NOT immediate. We:
  // 1. Call /api/tenant/switch-site
  // 2. Wait for server ACK (sets session.current_site_id)
  // 3. Only THEN update local state
  // 4. localStorage is ONLY for "last used" hint, never source of truth
  // ==========================================================================
  const switchSite = useCallback(async (siteId: string): Promise<boolean> => {
    // Validate site exists in our list
    const targetSite = state.sites.find((s) => s.id === siteId);
    if (!targetSite) {
      console.error(`[TenantContext] Invalid site ID: ${siteId}`);
      return false;
    }

    // Already on this site
    if (state.currentSite?.id === siteId) {
      return true;
    }

    dispatch({ type: 'SET_SWITCHING_SITE', payload: true });

    try {
      // Server must ACK site switch - this updates session
      const res = await fetch('/api/tenant/switch-site', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ site_id: siteId }),
        credentials: 'include',
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({ message: 'Site switch failed' }));
        throw new Error(error.message || `Site switch failed: ${res.status}`);
      }

      // Server ACK received - now update local state
      dispatch({ type: 'SET_CURRENT_SITE', payload: targetSite });

      // localStorage only as UI preference hint for NEXT session
      // Never used as current source of truth
      if (typeof window !== 'undefined') {
        localStorage.setItem('sv_site_preference', siteId);
      }

      return true;
    } catch (err) {
      dispatch({ type: 'SET_ERROR', payload: err instanceof Error ? err : new Error(String(err)) });
      dispatch({ type: 'SET_SWITCHING_SITE', payload: false });
      return false;
    }
  }, [state.sites, state.currentSite?.id]);

  const refreshTenant = useCallback(async () => {
    dispatch({ type: 'SET_LOADING', payload: true });
    try {
      const res = await fetch('/api/tenant/me', { credentials: 'include' });
      if (!res.ok) throw new Error(`Refresh failed: ${res.status}`);
      const data: TenantMeResponse = await res.json();
      dispatch({ type: 'SET_TENANT_DATA', payload: data });
    } catch (err) {
      dispatch({ type: 'SET_ERROR', payload: err instanceof Error ? err : new Error(String(err)) });
    }
  }, []);

  // ==========================================================================
  // PERMISSION CHECK - UX ONLY
  // ==========================================================================
  // WARNING: This is UI-level gating only.
  // Backend/BFF MUST enforce permissions on every API call.
  // This function exists for conditional rendering, NOT security.
  // ==========================================================================
  const hasPermission = useCallback((permission: Permission): boolean => {
    if (!state.user) return false;
    return state.user.permissions.includes(permission);
  }, [state.user]);

  // ==========================================================================
  // PACK ACCESS CHECK - UX ONLY
  // ==========================================================================
  // WARNING: This is UI-level gating only.
  // Backend/BFF MUST enforce pack entitlements on every API call.
  // This function exists for conditional rendering, NOT security.
  // ==========================================================================
  const hasPackAccess = useCallback((packId: PackId): boolean => {
    // Core is ALWAYS accessible
    if (packId === 'core') return true;
    return state.enabledPacks.some((p) => p.id === packId);
  }, [state.enabledPacks]);

  // Memoized context value
  const contextValue = useMemo<TenantContext>(() => ({
    ...state,
    switchSite,
    refreshTenant,
    hasPermission,
    hasPackAccess,
  }), [state, switchSite, refreshTenant, hasPermission, hasPackAccess]);

  return (
    <TenantCtx.Provider value={contextValue}>
      {children}
    </TenantCtx.Provider>
  );
}

// =============================================================================
// HOOKS
// =============================================================================

export function useTenant(): TenantContext {
  const context = useContext(TenantCtx);
  if (!context) {
    throw new Error('useTenant must be used within a TenantProvider');
  }
  return context;
}

export function useCurrentSite() {
  const { currentSite, sites, switchSite, isSwitchingSite } = useTenant() as TenantContext & { isSwitchingSite: boolean };
  return { currentSite, sites, switchSite, isSwitchingSite };
}

export function useUser() {
  const { user, hasPermission } = useTenant();
  return { user, hasPermission };
}

export function usePacks() {
  const { enabledPacks, hasPackAccess } = useTenant();
  return { enabledPacks, hasPackAccess };
}

// =============================================================================
// PERMISSION GUARD COMPONENT
// =============================================================================
// ⚠️ SECURITY WARNING: This guard is for UX ONLY.
// It hides UI elements but does NOT provide security.
// Backend endpoints MUST enforce role/permission checks independently.
// Never rely on this for access control - only for conditional rendering.
// =============================================================================

interface PermissionGuardProps {
  permission: Permission;
  children: ReactNode;
  fallback?: ReactNode;
}

export function PermissionGuard({ permission, children, fallback = null }: PermissionGuardProps) {
  const { hasPermission } = useTenant();

  // UX-only: hides children if permission missing
  // Backend MUST still reject unauthorized API calls
  if (!hasPermission(permission)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}

// =============================================================================
// PACK GUARD COMPONENT
// =============================================================================
// ⚠️ SECURITY WARNING: This guard is for UX ONLY.
// It hides UI elements but does NOT provide security.
// Backend endpoints MUST enforce pack entitlements independently.
// Never rely on this for access control - only for conditional rendering.
// =============================================================================

interface PackGuardProps {
  packId: PackId;
  children: ReactNode;
  fallback?: ReactNode;
}

export function PackGuard({ packId, children, fallback = null }: PackGuardProps) {
  const { hasPackAccess } = useTenant();

  // UX-only: hides children if pack not enabled
  // Backend MUST still reject unauthorized API calls
  if (!hasPackAccess(packId)) {
    return <>{fallback}</>;
  }

  return <>{children}</>;
}

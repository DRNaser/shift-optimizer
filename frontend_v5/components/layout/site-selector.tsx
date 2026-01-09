// =============================================================================
// SOLVEREIGN Site Selector Component
// =============================================================================
// Dropdown component for switching between sites within a tenant.
//
// SECURITY: Site switching is server-authoritative.
// - Click triggers /api/tenant/switch-site
// - UI only updates AFTER server ACK
// - Loading state shown during switch
// =============================================================================

'use client';

import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Building2, Check, MapPin, Loader2 } from 'lucide-react';
import { useCurrentSite } from '@/lib/hooks/use-tenant';
import { cn } from '@/lib/utils';
import type { Site } from '@/lib/tenant-types';

interface SiteSelectorProps {
  className?: string;
  compact?: boolean;
}

export function SiteSelector({ className, compact = false }: SiteSelectorProps) {
  const { currentSite, sites, switchSite, isSwitchingSite } = useCurrentSite();
  const [isOpen, setIsOpen] = useState(false);
  const [pendingSiteId, setPendingSiteId] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Close on Escape key
  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false);
      }
    }

    if (isOpen) {
      document.addEventListener('keydown', handleEscape);
      return () => document.removeEventListener('keydown', handleEscape);
    }
  }, [isOpen]);

  // Single site - no dropdown needed
  if (sites.length <= 1) {
    return (
      <div className={cn(
        'flex items-center gap-2 px-3 py-2 rounded-md bg-[var(--muted)]',
        className
      )}>
        <Building2 className="h-4 w-4 text-[var(--muted-foreground)]" />
        <span className="text-sm font-medium">
          {currentSite?.name || 'Kein Standort'}
        </span>
      </div>
    );
  }

  // Handle site selection - ASYNC with server ACK
  const handleSelect = async (site: Site) => {
    if (site.id === currentSite?.id) {
      setIsOpen(false);
      return;
    }

    setPendingSiteId(site.id);

    try {
      // Wait for server ACK before closing dropdown
      const success = await switchSite(site.id);

      if (success) {
        setIsOpen(false);
      } else {
        // Show error toast or message
        console.error('[SiteSelector] Site switch failed');
      }
    } finally {
      setPendingSiteId(null);
    }
  };

  const isLoading = isSwitchingSite || pendingSiteId !== null;

  return (
    <div ref={dropdownRef} className={cn('relative', className)}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => !isLoading && setIsOpen(!isOpen)}
        disabled={isLoading}
        className={cn(
          'flex items-center gap-2 px-3 py-2 rounded-md',
          'bg-[var(--muted)] hover:bg-[var(--sv-gray-200)]',
          'transition-colors duration-150',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--sv-primary)]',
          compact ? 'min-w-[140px]' : 'min-w-[200px]',
          isLoading && 'opacity-70 cursor-not-allowed'
        )}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        aria-busy={isLoading}
      >
        {isLoading ? (
          <Loader2 className="h-4 w-4 text-[var(--sv-primary)] flex-shrink-0 animate-spin" />
        ) : (
          <Building2 className="h-4 w-4 text-[var(--sv-primary)] flex-shrink-0" />
        )}
        <span className="text-sm font-medium truncate flex-1 text-left">
          {compact ? currentSite?.code : currentSite?.name || 'Standort wählen'}
        </span>
        <ChevronDown
          className={cn(
            'h-4 w-4 text-[var(--muted-foreground)] transition-transform duration-200',
            isOpen && 'transform rotate-180'
          )}
        />
      </button>

      {/* Dropdown Menu */}
      {isOpen && !isLoading && (
        <div
          className={cn(
            'absolute z-50 mt-1 w-full min-w-[240px]',
            'bg-[var(--card)] border border-[var(--border)] rounded-lg',
            'shadow-[var(--sv-shadow-lg)]',
            'py-1 max-h-[300px] overflow-auto'
          )}
          role="listbox"
          aria-label="Standort auswählen"
        >
          {/* Header */}
          <div className="px-3 py-2 text-xs font-medium text-[var(--muted-foreground)] uppercase tracking-wide border-b border-[var(--border)]">
            Standorte
          </div>

          {/* Site Options */}
          {sites.map((site) => {
            const isSelected = site.id === currentSite?.id;
            const isPending = site.id === pendingSiteId;

            return (
              <button
                key={site.id}
                type="button"
                onClick={() => handleSelect(site)}
                disabled={isPending}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2',
                  'hover:bg-[var(--muted)] transition-colors duration-150',
                  'focus:outline-none focus-visible:bg-[var(--muted)]',
                  isSelected && 'bg-[var(--sv-primary)]/5',
                  isPending && 'opacity-70 cursor-not-allowed'
                )}
                role="option"
                aria-selected={isSelected}
              >
                {/* Site Icon */}
                <div className={cn(
                  'flex-shrink-0 h-8 w-8 rounded-md flex items-center justify-center',
                  isSelected
                    ? 'bg-[var(--sv-primary)] text-white'
                    : 'bg-[var(--muted)] text-[var(--muted-foreground)]'
                )}>
                  {isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <MapPin className="h-4 w-4" />
                  )}
                </div>

                {/* Site Info */}
                <div className="flex-1 text-left">
                  <div className="text-sm font-medium text-[var(--foreground)]">
                    {site.name}
                  </div>
                  <div className="text-xs text-[var(--muted-foreground)]">
                    {site.code}
                  </div>
                </div>

                {/* Selected Check */}
                {isSelected && (
                  <Check className="h-4 w-4 text-[var(--sv-primary)] flex-shrink-0" />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// SITE BADGE COMPONENT
// =============================================================================

interface SiteBadgeProps {
  site: Site;
  className?: string;
}

export function SiteBadge({ site, className }: SiteBadgeProps) {
  return (
    <span className={cn(
      'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
      'bg-[var(--sv-primary)]/10 text-[var(--sv-primary)]',
      className
    )}>
      <MapPin className="h-3 w-3" />
      {site.code}
    </span>
  );
}

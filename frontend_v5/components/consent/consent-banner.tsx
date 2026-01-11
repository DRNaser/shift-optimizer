'use client';

/**
 * GDPR Consent Banner (P2.3)
 * ==========================
 *
 * Cookie/consent banner for GDPR compliance.
 * Shows on first visit and allows users to manage preferences.
 */

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface ConsentPurpose {
  code: string;
  name: string;
  description: string;
  isRequired: boolean;
}

const DEFAULT_PURPOSES: ConsentPurpose[] = [
  {
    code: 'necessary',
    name: 'Notwendig',
    description: 'Für Authentifizierung und Sicherheit erforderlich',
    isRequired: true,
  },
  {
    code: 'analytics',
    name: 'Analyse',
    description: 'Anonymisierte Nutzungsstatistiken zur Verbesserung des Dienstes',
    isRequired: false,
  },
  {
    code: 'notifications',
    name: 'Benachrichtigungen',
    description: 'E-Mail/WhatsApp Benachrichtigungen über Schichtpläne',
    isRequired: false,
  },
];

const CONSENT_STORAGE_KEY = 'solvereign_consent';
const CONSENT_VERSION = '1.0';

interface ConsentState {
  version: string;
  timestamp: string;
  purposes: Record<string, boolean>;
}

export function ConsentBanner() {
  const [showBanner, setShowBanner] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [purposes, setPurposes] = useState<Record<string, boolean>>({
    necessary: true,
    analytics: false,
    notifications: false,
  });

  useEffect(() => {
    // Check if consent has been given
    const stored = localStorage.getItem(CONSENT_STORAGE_KEY);
    if (!stored) {
      setShowBanner(true);
      return;
    }

    try {
      const consent: ConsentState = JSON.parse(stored);
      // Show banner if version changed
      if (consent.version !== CONSENT_VERSION) {
        setShowBanner(true);
      } else {
        setPurposes(consent.purposes);
      }
    } catch {
      setShowBanner(true);
    }
  }, []);

  const saveConsent = (newPurposes: Record<string, boolean>) => {
    const consent: ConsentState = {
      version: CONSENT_VERSION,
      timestamp: new Date().toISOString(),
      purposes: newPurposes,
    };
    localStorage.setItem(CONSENT_STORAGE_KEY, JSON.stringify(consent));

    // Send to backend (optional, for audit)
    try {
      fetch('/api/consent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(consent),
      });
    } catch {
      // Silently fail - localStorage is the source of truth
    }

    setPurposes(newPurposes);
    setShowBanner(false);
  };

  const acceptAll = () => {
    const all: Record<string, boolean> = {};
    DEFAULT_PURPOSES.forEach((p) => {
      all[p.code] = true;
    });
    saveConsent(all);
  };

  const acceptNecessary = () => {
    const necessary: Record<string, boolean> = {};
    DEFAULT_PURPOSES.forEach((p) => {
      necessary[p.code] = p.isRequired;
    });
    saveConsent(necessary);
  };

  const saveCustom = () => {
    saveConsent(purposes);
  };

  const togglePurpose = (code: string, required: boolean) => {
    if (required) return; // Can't toggle required purposes
    setPurposes((prev) => ({ ...prev, [code]: !prev[code] }));
  };

  if (!showBanner) return null;

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 bg-white border-t shadow-lg">
      <div className="max-w-7xl mx-auto px-4 py-4 sm:px-6 lg:px-8">
        {!showDetails ? (
          // Simple banner
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex-1">
              <p className="text-sm text-gray-700">
                Wir verwenden Cookies und ähnliche Technologien, um unseren Dienst
                bereitzustellen und zu verbessern. Einige sind für den Betrieb
                erforderlich, andere helfen uns bei der Analyse.{' '}
                <Link href="/legal/privacy" className="text-blue-600 hover:underline">
                  Mehr erfahren
                </Link>
              </p>
            </div>
            <div className="flex flex-col sm:flex-row gap-2 sm:gap-3">
              <button
                onClick={() => setShowDetails(true)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
              >
                Einstellungen
              </button>
              <button
                onClick={acceptNecessary}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
              >
                Nur Notwendige
              </button>
              <button
                onClick={acceptAll}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors"
              >
                Alle akzeptieren
              </button>
            </div>
          </div>
        ) : (
          // Detailed settings
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900">
                Cookie-Einstellungen
              </h3>
              <button
                onClick={() => setShowDetails(false)}
                className="text-gray-400 hover:text-gray-600"
                aria-label="Schließen"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="space-y-3">
              {DEFAULT_PURPOSES.map((purpose) => (
                <div
                  key={purpose.code}
                  className="flex items-start space-x-3 p-3 bg-gray-50 rounded-lg"
                >
                  <div className="flex-shrink-0 pt-0.5">
                    <button
                      onClick={() => togglePurpose(purpose.code, purpose.isRequired)}
                      disabled={purpose.isRequired}
                      className={`
                        w-10 h-6 rounded-full transition-colors relative
                        ${purposes[purpose.code] ? 'bg-blue-600' : 'bg-gray-300'}
                        ${purpose.isRequired ? 'cursor-not-allowed opacity-75' : 'cursor-pointer'}
                      `}
                      aria-label={`${purpose.name} ${purposes[purpose.code] ? 'deaktivieren' : 'aktivieren'}`}
                    >
                      <span
                        className={`
                          absolute top-1 w-4 h-4 bg-white rounded-full transition-transform
                          ${purposes[purpose.code] ? 'left-5' : 'left-1'}
                        `}
                      />
                    </button>
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-900">{purpose.name}</span>
                      {purpose.isRequired && (
                        <span className="text-xs text-gray-500 bg-gray-200 px-2 py-0.5 rounded">
                          Erforderlich
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 mt-1">{purpose.description}</p>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                onClick={acceptNecessary}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md transition-colors"
              >
                Nur Notwendige
              </button>
              <button
                onClick={saveCustom}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md transition-colors"
              >
                Auswahl speichern
              </button>
            </div>

            <p className="text-xs text-gray-500 pt-2 border-t">
              Sie können Ihre Einstellungen jederzeit in den{' '}
              <Link href="/legal/privacy" className="text-blue-600 hover:underline">
                Datenschutzeinstellungen
              </Link>{' '}
              ändern.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Hook to check consent status
 */
export function useConsent(purposeCode: string): boolean {
  const [hasConsent, setHasConsent] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(CONSENT_STORAGE_KEY);
    if (!stored) {
      setHasConsent(false);
      return;
    }

    try {
      const consent: ConsentState = JSON.parse(stored);
      setHasConsent(consent.purposes[purposeCode] ?? false);
    } catch {
      setHasConsent(false);
    }
  }, [purposeCode]);

  return hasConsent;
}

/**
 * Check consent synchronously (for non-React contexts)
 */
export function checkConsent(purposeCode: string): boolean {
  if (typeof window === 'undefined') return false;

  const stored = localStorage.getItem(CONSENT_STORAGE_KEY);
  if (!stored) return false;

  try {
    const consent: ConsentState = JSON.parse(stored);
    return consent.purposes[purposeCode] ?? false;
  } catch {
    return false;
  }
}

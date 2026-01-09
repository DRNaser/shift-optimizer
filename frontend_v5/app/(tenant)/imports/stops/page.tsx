// =============================================================================
// SOLVEREIGN Tenant - Stops Import Page
// =============================================================================
// /tenant/imports/stops
//
// FLS Export Import Flow:
//   1. Upload CSV file
//   2. Validate (shows errors/warnings)
//   3. Accept (loads into scenario)
//
// BLOCKED STATUS: If tenant is blocked, upload is disabled.
// =============================================================================

'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  Upload,
  FileSpreadsheet,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Clock,
  Loader2,
  RefreshCw,
  Eye,
  Check,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTenant } from '@/lib/hooks/use-tenant';
import { BlockedButton, useTenantStatus } from '@/components/tenant';
import type { StopImportJob, ValidationError } from '@/lib/tenant-api';

// =============================================================================
// STATUS BADGE
// =============================================================================

function ImportStatusBadge({ status }: { status: StopImportJob['status'] }) {
  const config: Record<StopImportJob['status'], { icon: typeof Clock; color: string; label: string }> = {
    PENDING: { icon: Clock, color: 'text-[var(--sv-gray-500)] bg-[var(--sv-gray-100)]', label: 'Ausstehend' },
    VALIDATING: { icon: Loader2, color: 'text-[var(--sv-info)] bg-[var(--sv-info-light)]', label: 'Validierung...' },
    VALIDATED: { icon: CheckCircle, color: 'text-[var(--sv-warning)] bg-[var(--sv-warning-light)]', label: 'Validiert' },
    ACCEPTED: { icon: Check, color: 'text-[var(--sv-success)] bg-[var(--sv-success-light)]', label: 'Akzeptiert' },
    REJECTED: { icon: X, color: 'text-[var(--sv-error)] bg-[var(--sv-error-light)]', label: 'Abgelehnt' },
    FAILED: { icon: XCircle, color: 'text-[var(--sv-error)] bg-[var(--sv-error-light)]', label: 'Fehler' },
  };

  const { icon: Icon, color, label } = config[status];

  return (
    <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium', color)}>
      <Icon className={cn('h-3.5 w-3.5', status === 'VALIDATING' && 'animate-spin')} />
      {label}
    </span>
  );
}

// =============================================================================
// VALIDATION ERRORS TABLE
// =============================================================================

function ValidationErrorsTable({ errors }: { errors: ValidationError[] }) {
  if (errors.length === 0) return null;

  return (
    <div className="mt-4 border border-[var(--border)] rounded-lg overflow-hidden">
      <div className="bg-[var(--sv-error-light)] px-4 py-2 border-b border-[var(--border)]">
        <span className="text-sm font-medium text-[var(--sv-error)]">
          {errors.length} Validierungsfehler
        </span>
      </div>
      <div className="max-h-[200px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="bg-[var(--muted)]">
            <tr>
              <th className="px-4 py-2 text-left font-medium">Zeile</th>
              <th className="px-4 py-2 text-left font-medium">Feld</th>
              <th className="px-4 py-2 text-left font-medium">Fehlercode</th>
              <th className="px-4 py-2 text-left font-medium">Nachricht</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {errors.map((err, idx) => (
              <tr key={idx} className="hover:bg-[var(--muted)]">
                <td className="px-4 py-2 font-mono">{err.row}</td>
                <td className="px-4 py-2">{err.field}</td>
                <td className="px-4 py-2">
                  <code className="px-1.5 py-0.5 bg-[var(--sv-error-light)] text-[var(--sv-error)] text-xs rounded">
                    {err.error_code}
                  </code>
                </td>
                <td className="px-4 py-2 text-[var(--muted-foreground)]">{err.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// =============================================================================
// IMPORT CARD
// =============================================================================

function ImportCard({
  importJob,
  onValidate,
  onAccept,
  onReject,
  isLoading,
}: {
  importJob: StopImportJob;
  onValidate: (id: string) => void;
  onAccept: (id: string) => void;
  onReject: (id: string) => void;
  isLoading: boolean;
}) {
  const [showErrors, setShowErrors] = useState(false);

  return (
    <div className="border border-[var(--border)] rounded-lg bg-[var(--card)]">
      <div className="p-4">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-lg bg-[var(--muted)]">
              <FileSpreadsheet className="h-5 w-5 text-[var(--sv-primary)]" />
            </div>
            <div>
              <h3 className="font-medium">{importJob.filename}</h3>
              <p className="text-sm text-[var(--muted-foreground)]">
                {new Date(importJob.created_at).toLocaleString('de-DE')}
              </p>
            </div>
          </div>
          <ImportStatusBadge status={importJob.status} />
        </div>

        {/* Stats */}
        <div className="mt-4 grid grid-cols-3 gap-4 text-center">
          <div className="p-2 bg-[var(--muted)] rounded-md">
            <div className="text-lg font-semibold">{importJob.total_rows}</div>
            <div className="text-xs text-[var(--muted-foreground)]">Gesamt</div>
          </div>
          <div className="p-2 bg-[var(--sv-success-light)] rounded-md">
            <div className="text-lg font-semibold text-[var(--sv-success)]">{importJob.valid_rows}</div>
            <div className="text-xs text-[var(--muted-foreground)]">Gueltig</div>
          </div>
          <div className="p-2 bg-[var(--sv-error-light)] rounded-md">
            <div className="text-lg font-semibold text-[var(--sv-error)]">{importJob.invalid_rows}</div>
            <div className="text-xs text-[var(--muted-foreground)]">Ungueltig</div>
          </div>
        </div>

        {/* Validation Errors Toggle */}
        {importJob.validation_errors.length > 0 && (
          <button
            type="button"
            onClick={() => setShowErrors(!showErrors)}
            className="mt-4 flex items-center gap-2 text-sm text-[var(--sv-error)] hover:underline"
          >
            <Eye className="h-4 w-4" />
            {showErrors ? 'Fehler ausblenden' : `${importJob.validation_errors.length} Fehler anzeigen`}
          </button>
        )}

        {showErrors && <ValidationErrorsTable errors={importJob.validation_errors} />}

        {/* Actions */}
        <div className="mt-4 flex gap-2">
          {importJob.status === 'PENDING' && (
            <BlockedButton
              onClick={() => onValidate(importJob.id)}
              disabled={isLoading}
              className="flex-1 px-4 py-2 bg-[var(--sv-primary)] text-white rounded-md hover:bg-[var(--sv-primary-dark)] disabled:opacity-50"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Validieren'}
            </BlockedButton>
          )}
          {importJob.status === 'VALIDATED' && (
            <>
              <BlockedButton
                onClick={() => onAccept(importJob.id)}
                disabled={isLoading || importJob.invalid_rows > 0}
                className="flex-1 px-4 py-2 bg-[var(--sv-success)] text-white rounded-md hover:bg-green-700 disabled:opacity-50"
              >
                {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Akzeptieren'}
              </BlockedButton>
              <button
                type="button"
                onClick={() => onReject(importJob.id)}
                disabled={isLoading}
                className="flex-1 px-4 py-2 border border-[var(--sv-error)] text-[var(--sv-error)] rounded-md hover:bg-[var(--sv-error-light)] disabled:opacity-50"
              >
                Ablehnen
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// UPLOAD DROPZONE
// =============================================================================

function UploadDropzone({ onUpload, isLoading }: { onUpload: (file: File) => void; isLoading: boolean }) {
  const [isDragging, setIsDragging] = useState(false);
  const { isWriteBlocked } = useTenantStatus();

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (isWriteBlocked || isLoading) return;

    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith('.csv')) {
      onUpload(file);
    }
  }, [onUpload, isWriteBlocked, isLoading]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onUpload(file);
    }
  }, [onUpload]);

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      className={cn(
        'border-2 border-dashed rounded-lg p-8 text-center transition-colors',
        isDragging ? 'border-[var(--sv-primary)] bg-[var(--sv-primary)]/5' : 'border-[var(--border)]',
        isWriteBlocked && 'opacity-50 cursor-not-allowed'
      )}
    >
      <input
        type="file"
        accept=".csv"
        onChange={handleFileSelect}
        disabled={isWriteBlocked || isLoading}
        className="hidden"
        id="file-upload"
      />
      <label
        htmlFor="file-upload"
        className={cn(
          'cursor-pointer',
          isWriteBlocked && 'pointer-events-none'
        )}
      >
        <div className="mx-auto h-12 w-12 rounded-full bg-[var(--muted)] flex items-center justify-center mb-4">
          {isLoading ? (
            <Loader2 className="h-6 w-6 text-[var(--sv-primary)] animate-spin" />
          ) : (
            <Upload className="h-6 w-6 text-[var(--sv-primary)]" />
          )}
        </div>
        <p className="text-sm font-medium">
          {isWriteBlocked
            ? 'Upload blockiert (Tenant gesperrt)'
            : 'CSV-Datei hier ablegen oder klicken zum Hochladen'}
        </p>
        <p className="text-xs text-[var(--muted-foreground)] mt-1">
          FLS Export Format (.csv)
        </p>
      </label>
    </div>
  );
}

// =============================================================================
// MAIN PAGE
// =============================================================================

export default function StopsImportPage() {
  const { currentSite } = useTenant();
  const [imports, setImports] = useState<StopImportJob[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  // Fetch imports
  const fetchImports = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/tenant/imports');
      if (res.ok) {
        const data = await res.json();
        setImports(data);
      }
    } catch (err) {
      console.error('Failed to fetch imports:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchImports();
  }, [fetchImports]);

  // Upload handler
  const handleUpload = async (file: File) => {
    setActionLoading('upload');
    try {
      const content = await file.text();
      const res = await fetch('/api/tenant/imports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename: file.name, content }),
      });
      if (res.ok) {
        fetchImports();
      }
    } catch (err) {
      console.error('Upload failed:', err);
    } finally {
      setActionLoading(null);
    }
  };

  // Action handlers
  const handleValidate = async (id: string) => {
    setActionLoading(id);
    try {
      await fetch(`/api/tenant/imports/${id}/validate`, { method: 'POST' });
      fetchImports();
    } finally {
      setActionLoading(null);
    }
  };

  const handleAccept = async (id: string) => {
    setActionLoading(id);
    try {
      await fetch(`/api/tenant/imports/${id}/accept`, { method: 'POST' });
      fetchImports();
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async (id: string) => {
    setActionLoading(id);
    try {
      await fetch(`/api/tenant/imports/${id}/reject`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Manually rejected' }),
      });
      fetchImports();
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Stops Import</h1>
          <p className="text-sm text-[var(--muted-foreground)]">
            FLS Export hochladen und validieren - {currentSite?.name}
          </p>
        </div>
        <button
          type="button"
          onClick={fetchImports}
          disabled={isLoading}
          className="flex items-center gap-2 px-3 py-2 text-sm border border-[var(--border)] rounded-md hover:bg-[var(--muted)]"
        >
          <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          Aktualisieren
        </button>
      </div>

      {/* Upload Dropzone */}
      <UploadDropzone onUpload={handleUpload} isLoading={actionLoading === 'upload'} />

      {/* Imports List */}
      <div>
        <h2 className="text-lg font-medium mb-4">Aktuelle Imports</h2>
        {imports.length === 0 ? (
          <div className="text-center py-12 text-[var(--muted-foreground)]">
            <FileSpreadsheet className="h-12 w-12 mx-auto mb-4 opacity-50" />
            <p>Noch keine Imports vorhanden</p>
          </div>
        ) : (
          <div className="space-y-4">
            {imports.map((imp) => (
              <ImportCard
                key={imp.id}
                importJob={imp}
                onValidate={handleValidate}
                onAccept={handleAccept}
                onReject={handleReject}
                isLoading={actionLoading === imp.id}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

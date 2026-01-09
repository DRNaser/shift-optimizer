// =============================================================================
// SOLVEREIGN BFF - Teams Daily Import
// =============================================================================
// POST /api/tenant/teams/daily/import - Import team assignments for a date
//
// Accepts JSON with base64-encoded CSV + SHA256 hash for integrity
// (Avoids multipart/form-data HMAC issues)
// =============================================================================

import { NextRequest, NextResponse } from 'next/server';
import crypto from 'crypto';
import {
  getTenantContext,
  requirePermission,
  requireIdempotencyKey,
} from '@/lib/tenant-rbac';

interface ImportRequest {
  date: string;           // ISO date YYYY-MM-DD
  filename: string;
  content_base64: string; // Base64 encoded CSV
  content_sha256: string; // SHA256 of original content (pre-base64)
}

interface ImportResponse {
  import_id: string;
  date: string;
  filename: string;
  status: 'PENDING' | 'VALIDATING';
  row_count: number;
  created_at: string;
}

export async function POST(request: NextRequest) {
  // ==========================================================================
  // RBAC CHECK: upload:teams (also checks blocked tenant)
  // ==========================================================================
  const permissionDenied = await requirePermission('upload:teams');
  if (permissionDenied) return permissionDenied;

  // ==========================================================================
  // IDEMPOTENCY KEY CHECK
  // ==========================================================================
  const idempotencyKey = request.headers.get('X-Idempotency-Key');
  const idempotencyError = requireIdempotencyKey(idempotencyKey);
  if (idempotencyError) return idempotencyError;

  // ==========================================================================
  // GET TENANT CONTEXT
  // ==========================================================================
  const { tenantCode, siteCode, userEmail } = await getTenantContext();

  try {
    const body: ImportRequest = await request.json();
    const { date, filename, content_base64, content_sha256 } = body;

    if (!date || !filename || !content_base64 || !content_sha256) {
      return NextResponse.json(
        { code: 'VALIDATION_ERROR', message: 'date, filename, content_base64, content_sha256 required' },
        { status: 400 }
      );
    }

    // Verify content integrity
    const decodedContent = Buffer.from(content_base64, 'base64').toString('utf-8');
    const computedHash = crypto.createHash('sha256').update(decodedContent, 'utf-8').digest('hex');

    if (computedHash !== content_sha256) {
      return NextResponse.json(
        { code: 'INTEGRITY_ERROR', message: 'Content SHA256 mismatch - possible tampering' },
        { status: 400 }
      );
    }

    // Parse CSV to count rows
    const lines = decodedContent.split('\n').filter(line => line.trim());
    const rowCount = Math.max(0, lines.length - 1); // Exclude header

    // In production: Call backend with signed request
    // const response = await tenantFetch<ImportResponse>(
    //   `/api/v1/tenants/${tenantCode}/sites/${siteCode}/teams/daily/import`,
    //   {
    //     tenantCode,
    //     siteCode,
    //     method: 'POST',
    //     body: { date, filename, content: decodedContent },
    //     idempotencyKey
    //   }
    // );

    // Mock response
    const importResponse: ImportResponse = {
      import_id: `imp-${Date.now()}`,
      date,
      filename,
      status: 'PENDING',
      row_count: rowCount,
      created_at: new Date().toISOString(),
    };

    return NextResponse.json(importResponse, { status: 201 });
  } catch (err) {
    return NextResponse.json(
      { code: 'PARSE_ERROR', message: 'Invalid JSON body' },
      { status: 400 }
    );
  }
}

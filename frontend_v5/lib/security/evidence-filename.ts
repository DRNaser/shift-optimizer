/**
 * Evidence Filename Security
 * ==========================
 *
 * Defense-in-depth validation for evidence file access.
 *
 * NON-NEGOTIABLES:
 * - Block path traversal (../, ..\, URL-encoded variants)
 * - Whitelist extensions (.json only)
 * - Validate filename format matches expected pattern
 * - No absolute paths
 */

/**
 * Result of filename validation
 */
export interface FilenameValidationResult {
  valid: boolean;
  error?: string;
  sanitized?: string;
  parsed?: {
    eventType: string;
    tenantId: number;
    siteId?: number;
    entityId?: number;
    timestamp?: string;
  };
}

/**
 * Allowed file extensions for evidence files
 */
const ALLOWED_EXTENSIONS = ['.json'];

/**
 * Expected filename pattern: roster_{action}_{tenant}_{site}_{id}_{ts}.json
 * Also supports: routing_evidence_{tenant}_{site}_{run}_{ts}.json
 */
const FILENAME_PATTERN = /^[a-z]+_[a-z]+_\d+_\d+_\d+_[0-9T]+\.json$/i;

/**
 * Patterns that indicate path traversal attempts
 */
const TRAVERSAL_PATTERNS = [
  '..',           // Direct traversal
  '/',            // Unix path separator
  '\\',           // Windows path separator
  '%2e',          // URL-encoded .
  '%2f',          // URL-encoded /
  '%5c',          // URL-encoded \
  '%252e',        // Double-encoded .
  '%252f',        // Double-encoded /
  '%255c',        // Double-encoded \
  '\x00',         // Null byte
  '%00',          // URL-encoded null byte
];

/**
 * Validate and sanitize an evidence filename.
 *
 * @param filename - The filename to validate (already URL-decoded by framework)
 * @returns Validation result with error message or parsed components
 */
export function validateEvidenceFilename(filename: string): FilenameValidationResult {
  // 1. Reject empty or whitespace-only filenames
  if (!filename || !filename.trim()) {
    return { valid: false, error: 'Empty filename' };
  }

  // 2. Decode any remaining URL encoding (defense-in-depth)
  let decoded = filename;
  try {
    // Multiple decode passes to catch double/triple encoding
    for (let i = 0; i < 3; i++) {
      const newDecoded = decodeURIComponent(decoded);
      if (newDecoded === decoded) break;
      decoded = newDecoded;
    }
  } catch {
    // If decoding fails, the string may contain invalid sequences
    return { valid: false, error: 'Invalid filename encoding' };
  }

  // 3. Check for traversal patterns (case-insensitive)
  const lowerDecoded = decoded.toLowerCase();
  for (const pattern of TRAVERSAL_PATTERNS) {
    if (lowerDecoded.includes(pattern.toLowerCase())) {
      return { valid: false, error: 'Path traversal detected' };
    }
  }

  // 4. Reject absolute paths
  if (decoded.startsWith('/') || decoded.startsWith('\\') || /^[a-zA-Z]:/.test(decoded)) {
    return { valid: false, error: 'Absolute paths not allowed' };
  }

  // 5. Check file extension whitelist
  const hasAllowedExtension = ALLOWED_EXTENSIONS.some(ext =>
    decoded.toLowerCase().endsWith(ext)
  );
  if (!hasAllowedExtension) {
    return { valid: false, error: 'Invalid file extension' };
  }

  // 6. Validate filename pattern
  if (!FILENAME_PATTERN.test(decoded)) {
    return { valid: false, error: 'Invalid filename format' };
  }

  // 7. Parse filename components
  try {
    const parts = decoded.replace('.json', '').split('_');
    if (parts.length < 5) {
      return { valid: false, error: 'Invalid filename structure' };
    }

    const tenantId = parseInt(parts[2], 10);
    if (isNaN(tenantId) || tenantId <= 0) {
      return { valid: false, error: 'Invalid tenant ID in filename' };
    }

    const siteId = parts[3] ? parseInt(parts[3], 10) : undefined;
    const entityId = parts[4] ? parseInt(parts[4], 10) : undefined;

    return {
      valid: true,
      sanitized: decoded,
      parsed: {
        eventType: parts[1],
        tenantId,
        siteId: siteId && !isNaN(siteId) ? siteId : undefined,
        entityId: entityId && !isNaN(entityId) ? entityId : undefined,
        timestamp: parts[5],
      },
    };
  } catch {
    return { valid: false, error: 'Failed to parse filename' };
  }
}

/**
 * Check if a user can access an evidence file based on tenant context.
 *
 * @param filename - Validated filename
 * @param userTenantId - The user's tenant ID from session
 * @param isPlatformAdmin - Whether user is platform admin
 * @returns true if access is allowed
 */
export function canAccessEvidenceFile(
  parsedFilename: NonNullable<FilenameValidationResult['parsed']>,
  userTenantId: number | null,
  isPlatformAdmin: boolean
): boolean {
  // Platform admins can access all evidence
  if (isPlatformAdmin) {
    return true;
  }

  // Regular users can only access their tenant's evidence
  if (!userTenantId) {
    return false;
  }

  return parsedFilename.tenantId === userTenantId;
}

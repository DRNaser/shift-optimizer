/**
 * Evidence Filename Security Tests
 *
 * Tests for path traversal prevention and filename validation.
 */

import { validateEvidenceFilename, canAccessEvidenceFile } from './evidence-filename';

describe('validateEvidenceFilename', () => {
  // Valid filenames
  describe('valid filenames', () => {
    it('accepts valid roster evidence filename', () => {
      const result = validateEvidenceFilename('roster_publish_1_10_123_20260110T120000.json');
      expect(result.valid).toBe(true);
      expect(result.sanitized).toBe('roster_publish_1_10_123_20260110T120000.json');
      expect(result.parsed).toEqual({
        eventType: 'publish',
        tenantId: 1,
        siteId: 10,
        entityId: 123,
        timestamp: '20260110T120000',
      });
    });

    it('accepts valid routing evidence filename', () => {
      const result = validateEvidenceFilename('routing_solve_2_20_456_20260110T143000.json');
      expect(result.valid).toBe(true);
      expect(result.parsed?.tenantId).toBe(2);
    });
  });

  // Path traversal attacks
  describe('path traversal prevention', () => {
    it('blocks ../ traversal', () => {
      const result = validateEvidenceFilename('../../../etc/passwd');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });

    it('blocks ..\\ traversal', () => {
      const result = validateEvidenceFilename('..\\..\\Windows\\win.ini');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });

    it('blocks URL-encoded ../', () => {
      const result = validateEvidenceFilename('%2e%2e%2fetc/passwd');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });

    it('blocks double-encoded ../', () => {
      const result = validateEvidenceFilename('%252e%252e%252f');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });

    it('blocks URL-encoded backslash', () => {
      const result = validateEvidenceFilename('%5c%5cserver%5cshare');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });

    it('blocks null byte injection', () => {
      const result = validateEvidenceFilename('valid.json\x00.exe');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });

    it('blocks URL-encoded null byte', () => {
      const result = validateEvidenceFilename('valid.json%00.exe');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });
  });

  // Absolute paths
  describe('absolute path prevention', () => {
    it('blocks Unix absolute path', () => {
      const result = validateEvidenceFilename('/etc/passwd');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });

    it('blocks Windows absolute path', () => {
      const result = validateEvidenceFilename('C:\\Windows\\win.ini');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Path traversal detected');
    });
  });

  // Extension whitelist
  describe('extension whitelist', () => {
    it('rejects non-.json extensions', () => {
      const result = validateEvidenceFilename('roster_publish_1_10_123_ts.exe');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Invalid file extension');
    });

    it('rejects .json.exe double extension', () => {
      const result = validateEvidenceFilename('roster_publish_1_10_123_ts.json.exe');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Invalid file extension');
    });

    it('rejects .txt extension', () => {
      const result = validateEvidenceFilename('roster_publish_1_10_123_ts.txt');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Invalid file extension');
    });
  });

  // Invalid format
  describe('filename format validation', () => {
    it('rejects empty filename', () => {
      const result = validateEvidenceFilename('');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Empty filename');
    });

    it('rejects filename with too few parts', () => {
      const result = validateEvidenceFilename('roster_publish.json');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Invalid filename format');
    });

    it('rejects filename without proper structure', () => {
      const result = validateEvidenceFilename('somefile.json');
      expect(result.valid).toBe(false);
      expect(result.error).toBe('Invalid filename format');
    });

    it('rejects filename with invalid tenant ID', () => {
      const result = validateEvidenceFilename('roster_publish_abc_10_123_ts.json');
      expect(result.valid).toBe(false);
    });
  });
});

describe('canAccessEvidenceFile', () => {
  it('allows platform admin to access any tenant evidence', () => {
    const parsed = { eventType: 'publish', tenantId: 99, siteId: 10, entityId: 1 };
    expect(canAccessEvidenceFile(parsed, null, true)).toBe(true);
  });

  it('allows user to access their own tenant evidence', () => {
    const parsed = { eventType: 'publish', tenantId: 1, siteId: 10, entityId: 1 };
    expect(canAccessEvidenceFile(parsed, 1, false)).toBe(true);
  });

  it('blocks user from accessing other tenant evidence', () => {
    const parsed = { eventType: 'publish', tenantId: 2, siteId: 10, entityId: 1 };
    expect(canAccessEvidenceFile(parsed, 1, false)).toBe(false);
  });

  it('blocks user without tenant context', () => {
    const parsed = { eventType: 'publish', tenantId: 1, siteId: 10, entityId: 1 };
    expect(canAccessEvidenceFile(parsed, null, false)).toBe(false);
  });
});

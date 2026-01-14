/**
 * Whitelist Guard Test
 *
 * This test ensures that the error whitelist configuration in playwright.config.ts
 * does not accidentally whitelist server errors (500, 502, 503, etc.).
 *
 * If this test fails, it means someone tried to whitelist a server error pattern,
 * which would hide real bugs.
 */

import { test, expect } from '@playwright/test';
import {
  WHITELISTED_ERROR_PATTERNS,
  FORBIDDEN_ERROR_PATTERNS,
  isWhitelistedError,
  isForbiddenError,
} from '../playwright.config';

test.describe('Whitelist Configuration Guard', () => {
  test('500 errors are NEVER whitelisted', () => {
    const testCases = [
      '500 Internal Server Error',
      'Error: 500',
      'Response status: 500',
      'HTTP 500',
      'Failed with status 500',
    ];

    for (const errorMsg of testCases) {
      const isWhitelisted = isWhitelistedError(errorMsg);
      expect(isWhitelisted).toBe(false);
    }
  });

  test('Internal Server Error is NEVER whitelisted', () => {
    const testCases = [
      'Internal Server Error',
      'internal server error',
      'INTERNAL SERVER ERROR',
    ];

    for (const errorMsg of testCases) {
      const isWhitelisted = isWhitelistedError(errorMsg);
      expect(isWhitelisted).toBe(false);
    }
  });

  test('502/503 errors are NEVER whitelisted', () => {
    const testCases = [
      '502 Bad Gateway',
      '503 Service Unavailable',
      'Error: 502',
      'Error: 503',
    ];

    for (const errorMsg of testCases) {
      const isWhitelisted = isWhitelistedError(errorMsg);
      expect(isWhitelisted).toBe(false);
    }
  });

  test('isForbiddenError correctly identifies server errors', () => {
    expect(isForbiddenError('500 Internal Server Error')).toBe(true);
    expect(isForbiddenError('502 Bad Gateway')).toBe(true);
    expect(isForbiddenError('503 Service Unavailable')).toBe(true);
    expect(isForbiddenError('Internal Server Error')).toBe(true);
  });

  test('isForbiddenError does not flag auth errors', () => {
    expect(isForbiddenError('401 Unauthorized')).toBe(false);
    expect(isForbiddenError('403 Forbidden')).toBe(false);
    expect(isForbiddenError('Failed to fetch')).toBe(false);
  });

  test('401/403 errors ARE whitelisted (expected auth flow)', () => {
    expect(isWhitelistedError('401 Unauthorized')).toBe(true);
    expect(isWhitelistedError('403 Forbidden')).toBe(true);
    expect(isWhitelistedError('Error: 401')).toBe(true);
    expect(isWhitelistedError('Error: 403')).toBe(true);
  });

  test('Whitelist patterns do not include any 5xx codes', () => {
    // Verify the actual WHITELISTED_ERROR_PATTERNS array doesn't contain 5xx
    const patternsAsStrings = WHITELISTED_ERROR_PATTERNS.map(p => p.source);

    for (const patternStr of patternsAsStrings) {
      // Check that no pattern would match 500, 502, 503, etc.
      expect(patternStr).not.toContain('500');
      expect(patternStr).not.toContain('502');
      expect(patternStr).not.toContain('503');
      expect(patternStr).not.toMatch(/5\d\d/);
      expect(patternStr.toLowerCase()).not.toContain('internal server error');
    }
  });

  test('FORBIDDEN_ERROR_PATTERNS includes all critical server errors', () => {
    // Verify that FORBIDDEN_ERROR_PATTERNS catches what we expect
    expect(FORBIDDEN_ERROR_PATTERNS.length).toBeGreaterThanOrEqual(4);

    // Verify each forbidden pattern works
    const mustCatch = ['500', 'Internal Server Error', '502', '503'];
    for (const errorCode of mustCatch) {
      const caught = FORBIDDEN_ERROR_PATTERNS.some(p => p.test(errorCode));
      expect(caught).toBe(true);
    }
  });
});

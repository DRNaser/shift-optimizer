// =============================================================================
// SOLVEREIGN - Playwright E2E Test Configuration
// =============================================================================
//
// ENV VARS:
//   SV_E2E_BASE_URL - Frontend URL (default: http://localhost:3002)
//   E2E_BASE_URL    - Legacy alias for SV_E2E_BASE_URL
//   SV_E2E_USER     - Test user email (required for auth-flow.spec.ts)
//   SV_E2E_PASS     - Test user password (required for auth-flow.spec.ts)
//
// GLOBAL ERROR CAPTURE:
//   Tests will fail on unexpected console.error or pageerror unless whitelisted.
//   Whitelist patterns: 401, 403, Failed to fetch (expected auth errors)
//

import { defineConfig, devices } from '@playwright/test';

// Support both env var names, prefer SV_E2E_BASE_URL
const BASE_URL = process.env.SV_E2E_BASE_URL || process.env.E2E_BASE_URL || 'http://localhost:3002';

// =============================================================================
// WHITELISTED ERROR PATTERNS - STRICT MODE
// =============================================================================
// CRITICAL: 500 errors are NEVER whitelisted. If a 500 error occurs, it means
// the backend has a bug that must be fixed.
//
// These patterns represent EXPECTED console errors that occur during normal
// operation and should NOT cause test failures:
//
export const WHITELISTED_ERROR_PATTERNS = [
  /401/,              // Expected: Unauthenticated requests before login
  /403/,              // Expected: Unauthorized requests (RBAC working correctly)
  /Failed to fetch/,  // Expected: AbortController cancellations during navigation
  /Unauthorized/,     // Expected: Auth error messages
  /NetworkError/,     // Expected: Network failures during navigation
  /net::ERR_/,        // Expected: Chrome network errors during navigation
];

// =============================================================================
// FORBIDDEN PATTERNS - These must NEVER be whitelisted
// =============================================================================
// If any of these appear in console, it indicates a real bug.
export const FORBIDDEN_ERROR_PATTERNS = [
  /500/,                    // Server crash - ALWAYS a bug
  /Internal Server Error/i, // Server crash - ALWAYS a bug
  /502/,                    // Bad gateway - infrastructure issue
  /503/,                    // Service unavailable - infrastructure issue
  /ECONNREFUSED/,           // Backend not running - startup issue
];

export function isWhitelistedError(message: string): boolean {
  // First check if it's a forbidden pattern (always fail)
  if (FORBIDDEN_ERROR_PATTERNS.some(pattern => pattern.test(message))) {
    return false;
  }
  // Then check if it's a whitelisted pattern
  return WHITELISTED_ERROR_PATTERNS.some(pattern => pattern.test(message));
}

export function isForbiddenError(message: string): boolean {
  return FORBIDDEN_ERROR_PATTERNS.some(pattern => pattern.test(message));
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Limit workers to avoid overwhelming the dev server - Next.js dev mode is slow
  workers: process.env.CI ? 1 : 4,
  reporter: [
    ['html'],
    ['list'],
  ],

  // Fail fast on unexpected errors
  expect: {
    timeout: 10000,
  },

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Dev server auto-start
  // - Local: uses 'dev' (faster, no build needed)
  // - CI: uses 'start' (requires build step before tests)
  webServer: {
    command: process.env.CI
      ? 'npm run start -- -p 3002'
      : 'npm run dev -- -p 3002',
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120 * 1000,
    stdout: 'pipe',
    stderr: 'pipe',
  },
});

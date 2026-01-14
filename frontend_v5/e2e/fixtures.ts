/**
 * SOLVEREIGN - E2E Test Fixtures
 *
 * Shared test fixtures for consistent error capture and page setup.
 *
 * Usage:
 *   import { test, expect } from './fixtures';
 *   // Instead of '@playwright/test'
 */

import { test as base, expect, Page } from '@playwright/test';
import { isWhitelistedError } from '../playwright.config';

// Collected errors during test
export interface CollectedErrors {
  console: string[];
  page: string[];
}

// Extended test with automatic error capture
export const test = base.extend<{
  errorCapture: CollectedErrors;
  autoFailOnErrors: boolean;
}>({
  // Collect errors throughout the test
  errorCapture: async ({ page }, use) => {
    const errors: CollectedErrors = {
      console: [],
      page: [],
    };

    // Capture console errors
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        if (!isWhitelistedError(text)) {
          errors.console.push(text);
        }
      }
    });

    // Capture page errors (uncaught exceptions)
    page.on('pageerror', (error) => {
      const text = error.message;
      if (!isWhitelistedError(text)) {
        errors.page.push(text);
      }
    });

    await use(errors);
  },

  // Auto-fail on unexpected errors (enabled by default)
  autoFailOnErrors: [true, { option: true }],
});

// Re-export expect for convenience
export { expect };

/**
 * Helper: Setup error capture on a page and return collector
 */
export function setupErrorCapture(page: Page): CollectedErrors {
  const errors: CollectedErrors = {
    console: [],
    page: [],
  };

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (!isWhitelistedError(text)) {
        errors.console.push(text);
      }
    }
  });

  page.on('pageerror', (error) => {
    const text = error.message;
    if (!isWhitelistedError(text)) {
      errors.page.push(text);
    }
  });

  return errors;
}

/**
 * Helper: Assert no unexpected errors occurred
 */
export function assertNoErrors(errors: CollectedErrors, context?: string): void {
  const allErrors = [...errors.console, ...errors.page];
  if (allErrors.length > 0) {
    const prefix = context ? `${context}: ` : '';
    throw new Error(`${prefix}Unexpected errors:\n${allErrors.join('\n')}`);
  }
}

/**
 * Helper: Filter only crash-causing errors (Cannot read properties, TypeError, etc.)
 */
export function getCriticalErrors(errors: CollectedErrors): string[] {
  const allErrors = [...errors.console, ...errors.page];
  return allErrors.filter(
    (e) =>
      e.includes('Cannot read properties') ||
      e.includes('undefined') ||
      e.includes('TypeError') ||
      e.includes('ReferenceError')
  );
}

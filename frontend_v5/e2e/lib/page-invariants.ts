/**
 * SOLVEREIGN - E2E Page Invariants
 *
 * Helper functions to wait for business UI invariants in E2E tests.
 * These ensure pages are ACTUALLY ready, not just DOM-loaded.
 */

import { Page, expect } from '@playwright/test';

/**
 * Wait for a page to show meaningful business content.
 * This goes beyond waitForLoadState('domcontentloaded') to ensure
 * actual data is rendered.
 */
export async function waitForBusinessContent(
  page: Page,
  options: {
    /** Timeout in ms (default: 15000) */
    timeout?: number;
    /** If true, accepts empty state as valid (e.g., "No data") */
    allowEmpty?: boolean;
  } = {}
): Promise<void> {
  const { timeout = 15000, allowEmpty = true } = options;

  // Wait for DOM content first
  await page.waitForLoadState('domcontentloaded', { timeout });

  // Then wait for one of these business-ready indicators:
  // 1. A data table/grid
  // 2. KPI cards with values
  // 3. An "empty state" message (if allowEmpty)
  // 4. A form ready for input
  const businessIndicators = [
    // Data tables (roster matrix, user lists, etc.)
    'table tbody tr',
    '[role="grid"] [role="row"]',
    // KPI cards with actual values
    '[data-testid="kpi-card"]',
    '.kpi-card',
    // Form elements ready for input
    'form input:not([type="hidden"])',
    'form select',
  ];

  const emptyStateIndicators = [
    'text=No data',
    'text=No results',
    'text=No items',
    'text=Empty',
    'text=Ready to optimize',
    'text=Upload',
    'text=Get started',
  ];

  // Build locator for business content
  const businessLocator = page.locator(businessIndicators.join(', ')).first();
  const emptyLocator = page.locator(emptyStateIndicators.join(', ')).first();

  // Wait for either business content or empty state
  try {
    await Promise.race([
      businessLocator.waitFor({ state: 'visible', timeout }),
      ...(allowEmpty ? [emptyLocator.waitFor({ state: 'visible', timeout })] : []),
    ]);
  } catch {
    // If nothing matched, check if we at least have a meaningful page
    const bodyText = await page.locator('body').textContent();
    const hasContent = bodyText && bodyText.length > 100;

    if (!hasContent) {
      throw new Error('Page did not render business content within timeout');
    }
  }
}

/**
 * Wait for roster workbench to be ready for interaction.
 */
export async function waitForWorkbenchReady(page: Page, timeout = 15000): Promise<void> {
  await page.waitForLoadState('domcontentloaded', { timeout });

  // Workbench-specific indicators
  const readyIndicators = [
    // Status badge (Ready/Running/Completed)
    'text=Ready',
    'text=Running',
    'text=Completed',
    // Upload button
    'text=Upload CSV',
    // Optimize button
    'button:has-text("Optimize")',
  ];

  const locator = page.locator(readyIndicators.join(', ')).first();
  await locator.waitFor({ state: 'visible', timeout });
}

/**
 * Wait for platform admin page to be ready.
 */
export async function waitForPlatformAdminReady(page: Page, timeout = 15000): Promise<void> {
  await page.waitForLoadState('domcontentloaded', { timeout });

  // Platform admin indicators
  const readyIndicators = [
    // Dashboard cards
    '[data-testid="stat-card"]',
    '.stat-card',
    // Navigation
    'nav a[href*="platform"]',
    // Tables
    'table tbody tr',
    // Action buttons
    'button:has-text("Create")',
    'button:has-text("New")',
  ];

  const locator = page.locator(readyIndicators.join(', ')).first();

  try {
    await locator.waitFor({ state: 'visible', timeout });
  } catch {
    // Check for forbidden access (expected for non-admins)
    const is403 = await page.locator('text=403').isVisible().catch(() => false);
    const isForbidden = await page.locator('text=Forbidden').isVisible().catch(() => false);

    if (!is403 && !isForbidden) {
      throw new Error('Platform admin page did not render expected content');
    }
  }
}

/**
 * Verify that a page does NOT show an error state.
 * Use this after navigation to ensure the page loaded successfully.
 */
export async function assertNoErrorState(page: Page): Promise<void> {
  // Check for error indicators
  const errorPatterns = [
    /500/,
    /Internal Server Error/i,
    /Something went wrong/i,
    /Error loading/i,
    /Failed to load/i,
    /ECONNREFUSED/,
  ];

  const bodyText = await page.locator('body').textContent() || '';

  for (const pattern of errorPatterns) {
    if (pattern.test(bodyText)) {
      throw new Error(`Page shows error state: ${pattern}`);
    }
  }
}

/**
 * Wait for a download to complete and return the path.
 * Use this for testing evidence/CSV export functionality.
 */
export async function waitForDownload(
  page: Page,
  triggerAction: () => Promise<void>,
  options: {
    timeout?: number;
    expectedFilename?: string | RegExp;
  } = {}
): Promise<string> {
  const { timeout = 30000, expectedFilename } = options;

  // Set up download listener before triggering
  const downloadPromise = page.waitForEvent('download', { timeout });

  // Trigger the download
  await triggerAction();

  // Wait for download
  const download = await downloadPromise;

  // Verify filename if specified
  if (expectedFilename) {
    const filename = download.suggestedFilename();
    if (typeof expectedFilename === 'string') {
      expect(filename).toContain(expectedFilename);
    } else {
      expect(filename).toMatch(expectedFilename);
    }
  }

  // Save to temp location
  const path = await download.path();
  if (!path) {
    throw new Error('Download failed - no path returned');
  }

  return path;
}

/**
 * Assert that a table/grid has at least N rows of data.
 */
export async function assertTableHasRows(
  page: Page,
  minRows: number,
  tableSelector = 'table tbody tr, [role="grid"] [role="row"]'
): Promise<void> {
  const rows = page.locator(tableSelector);
  const count = await rows.count();

  expect(count).toBeGreaterThanOrEqual(minRows);
}

/**
 * Wait for API response to complete.
 * Useful for pages that load data asynchronously.
 */
export async function waitForApiResponse(
  page: Page,
  urlPattern: string | RegExp,
  options: {
    timeout?: number;
    status?: number;
  } = {}
): Promise<void> {
  const { timeout = 15000, status = 200 } = options;

  await page.waitForResponse(
    (response) => {
      const matches = typeof urlPattern === 'string'
        ? response.url().includes(urlPattern)
        : urlPattern.test(response.url());

      return matches && response.status() === status;
    },
    { timeout }
  );
}

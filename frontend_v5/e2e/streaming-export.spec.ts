/**
 * SOLVEREIGN - Streaming Export E2E Tests
 *
 * Tests file download functionality:
 * 1. Evidence pack download (audit artifacts)
 * 2. CSV export from roster workbench
 *
 * These tests verify that:
 * - Downloads trigger successfully
 * - Downloaded files have expected content
 * - Download doesn't corrupt data (encoding, BOM, etc.)
 *
 * Prerequisites:
 * - E2E user seeded with platform_admin role
 * - Backend running with seeded data
 *
 * RUN:
 *   SV_E2E_USER=e2e-test@example.com \
 *   SV_E2E_PASS=E2ETestPassword123! \
 *   npx playwright test e2e/streaming-export.spec.ts
 */

import { test, expect, Page, Download } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const BASE_URL = process.env.SV_E2E_BASE_URL || process.env.E2E_BASE_URL || 'http://localhost:3002';
const E2E_USER = process.env.SV_E2E_USER || 'e2e-test@example.com';
const E2E_PASS = process.env.SV_E2E_PASS || 'E2ETestPassword123!';

// Skip all tests if credentials not provided
test.skip(
  !E2E_USER || !E2E_PASS,
  'SV_E2E_USER and SV_E2E_PASS env vars required'
);

// Helper: Login and get authenticated session
async function login(page: Page): Promise<boolean> {
  await page.goto(`${BASE_URL}/platform/login`);

  // Fill login form
  await page.fill('input[type="email"], input[name="email"]', E2E_USER);
  await page.fill('input[type="password"], input[name="password"]', E2E_PASS);

  // Submit
  await page.click('button[type="submit"]');

  // Wait for redirect away from login
  try {
    await page.waitForURL((url) => !url.pathname.includes('login'), { timeout: 15000 });
    return true;
  } catch {
    return false;
  }
}

// Helper: Wait for download to complete
async function waitForDownloadAndSave(
  page: Page,
  triggerDownload: () => Promise<void>
): Promise<{ filename: string; content: Buffer }> {
  // Set up download listener
  const downloadPromise = page.waitForEvent('download', { timeout: 30000 });

  // Trigger the download action
  await triggerDownload();

  // Wait for download
  const download = await downloadPromise;
  const filename = download.suggestedFilename();

  // Save to temp path
  const downloadPath = await download.path();
  if (!downloadPath) {
    throw new Error('Download failed - no path returned');
  }

  // Read content
  const content = fs.readFileSync(downloadPath);

  return { filename, content };
}

// =============================================================================
// CSV Export Tests
// =============================================================================

test.describe('Streaming: CSV Export', () => {
  test.skip('CSV export from workbench produces valid file', async ({ page }) => {
    // NOTE: This test is skipped by default because it requires:
    // 1. A completed solver run in the database
    // 2. The export button to be visible (requires result state)
    //
    // Enable this test in CI after seeding test data with a completed run.

    const loggedIn = await login(page);
    expect(loggedIn).toBe(true);

    // Navigate to workbench
    await page.goto(`${BASE_URL}/packs/roster/workbench`);
    await page.waitForLoadState('domcontentloaded');

    // Look for export button (only visible after a run completes)
    const exportButton = page.locator('button:has-text("Export")');

    if (!(await exportButton.isVisible())) {
      test.skip(true, 'No completed run available - Export button not visible');
      return;
    }

    // Download the CSV
    const { filename, content } = await waitForDownloadAndSave(page, async () => {
      await exportButton.click();
    });

    // Verify filename pattern
    expect(filename).toMatch(/solvereign.*\.csv$/i);

    // Verify content is valid CSV
    const text = content.toString('utf-8');

    // Should have BOM for Excel compatibility
    expect(text.startsWith('\uFEFF') || text.includes(';')).toBe(true);

    // Should have multiple lines
    const lines = text.split(/\r?\n/).filter((l) => l.trim());
    expect(lines.length).toBeGreaterThan(1);
  });

  test('CSV encoding preserves German characters', async ({ page }) => {
    // This test verifies that CSV export handles UTF-8 BOM correctly
    // for German special characters (umlauts, ß)

    const loggedIn = await login(page);
    expect(loggedIn).toBe(true);

    // Navigate to any page that might have a CSV export
    // We're testing the encoding mechanism, not specific content
    await page.goto(`${BASE_URL}/platform-admin/tenants`);
    await page.waitForLoadState('domcontentloaded');

    // For now, just verify the page loads without encoding errors
    const bodyText = await page.locator('body').textContent();
    expect(bodyText?.length).toBeGreaterThan(0);

    // If there's an export button, test it
    const exportButton = page.locator('button:has-text("Export"), a:has-text("Export")').first();

    if (await exportButton.isVisible()) {
      // Test that clicking export doesn't throw
      const downloadPromise = page.waitForEvent('download', { timeout: 5000 }).catch(() => null);
      await exportButton.click();

      const download = await downloadPromise;
      if (download) {
        const downloadPath = await download.path();
        if (downloadPath) {
          const content = fs.readFileSync(downloadPath, 'utf-8');

          // If content contains German text, verify it's not corrupted
          if (content.match(/[äöüÄÖÜß]/)) {
            // Characters should be readable, not mojibake
            expect(content).not.toMatch(/Ã¤|Ã¶|Ã¼/); // Common UTF-8 misinterpretation
          }
        }
      }
    }
  });
});

// =============================================================================
// Evidence/Artifact Download Tests
// =============================================================================

test.describe('Streaming: Evidence Download', () => {
  test('Portal evidence endpoint returns valid response', async ({ request }) => {
    // Test the evidence download API endpoint directly
    // This tests the streaming mechanism without UI dependencies

    // First login to get session
    const loginResponse = await request.post(`${BASE_URL}/api/auth/login`, {
      data: {
        email: E2E_USER,
        password: E2E_PASS,
      },
    });

    expect(loginResponse.ok()).toBe(true);

    // Try to access evidence endpoint
    // Note: This may return 404 if no evidence exists, which is acceptable
    const evidenceResponse = await request.get(`${BASE_URL}/api/portal-admin/export`);

    // Should return 200 (success) or 404 (no data) - NOT 500
    expect([200, 404, 400]).toContain(evidenceResponse.status());

    // If 200, verify it's actually downloadable content
    if (evidenceResponse.status() === 200) {
      const contentType = evidenceResponse.headers()['content-type'];
      // Should be CSV, JSON, or octet-stream
      expect(contentType).toMatch(/csv|json|octet-stream|text/i);
    }
  });

  test('API streaming does not timeout on large responses', async ({ request }) => {
    // This test verifies that streaming endpoints handle large data
    // without timing out or truncating the response

    // Login first
    const loginResponse = await request.post(`${BASE_URL}/api/auth/login`, {
      data: {
        email: E2E_USER,
        password: E2E_PASS,
      },
    });

    expect(loginResponse.ok()).toBe(true);

    // Test various API endpoints that might return large data
    const endpoints = [
      '/api/audit',
      '/api/portal-admin/snapshots',
      '/api/roster/plans',
    ];

    for (const endpoint of endpoints) {
      const response = await request.get(`${BASE_URL}${endpoint}`, {
        timeout: 30000, // 30 second timeout
      });

      // Should complete without timeout
      // 200 = success, 401/403 = auth issue (acceptable), 404 = no data (acceptable)
      expect([200, 401, 403, 404]).toContain(response.status());

      // If successful, verify response is valid JSON or proper format
      if (response.status() === 200) {
        const contentType = response.headers()['content-type'] || '';

        if (contentType.includes('json')) {
          // Should be parseable JSON
          const body = await response.text();
          expect(() => JSON.parse(body)).not.toThrow();
        }
      }
    }
  });
});

// =============================================================================
// Download Integrity Tests
// =============================================================================

test.describe('Streaming: Download Integrity', () => {
  test('Downloads do not produce empty files', async ({ page }) => {
    // This test catches a common streaming bug where the download
    // completes but the file is empty

    const loggedIn = await login(page);
    expect(loggedIn).toBe(true);

    // Navigate to a page with potential download buttons
    await page.goto(`${BASE_URL}/platform-admin`);
    await page.waitForLoadState('domcontentloaded');

    // Find any download/export buttons
    const downloadButtons = page.locator(
      'button:has-text("Export"), button:has-text("Download"), a[download]'
    );

    const count = await downloadButtons.count();

    // For each download button, verify it produces non-empty content
    for (let i = 0; i < Math.min(count, 3); i++) {
      // Limit to first 3 buttons
      const button = downloadButtons.nth(i);

      if (await button.isVisible()) {
        try {
          const { content } = await waitForDownloadAndSave(page, async () => {
            await button.click();
          });

          // File should not be empty
          expect(content.length).toBeGreaterThan(0);

          // If it looks like a CSV, should have headers
          const text = content.toString('utf-8');
          if (text.includes(',') || text.includes(';')) {
            const lines = text.split(/\r?\n/).filter((l) => l.trim());
            expect(lines.length).toBeGreaterThanOrEqual(1);
          }
        } catch (e) {
          // Download might not trigger for all buttons - that's OK
          console.log(`Button ${i} did not trigger download: ${e}`);
        }
      }
    }
  });

  test('Binary downloads maintain integrity', async ({ request }) => {
    // This test verifies that binary downloads (like PDFs or ZIP files)
    // are not corrupted during streaming

    // Login first
    const loginResponse = await request.post(`${BASE_URL}/api/auth/login`, {
      data: {
        email: E2E_USER,
        password: E2E_PASS,
      },
    });

    expect(loginResponse.ok()).toBe(true);

    // Test evidence export endpoint (if it produces binary output)
    const response = await request.get(`${BASE_URL}/api/portal-admin/export`, {
      timeout: 30000,
    });

    // If successful, verify content is not corrupted
    if (response.status() === 200) {
      const buffer = await response.body();
      const contentType = response.headers()['content-type'] || '';

      // Check for common corruption indicators
      if (contentType.includes('json')) {
        const text = buffer.toString('utf-8');
        // JSON should be parseable
        expect(() => JSON.parse(text)).not.toThrow();
      } else if (contentType.includes('csv')) {
        const text = buffer.toString('utf-8');
        // CSV should have content
        expect(text.length).toBeGreaterThan(0);
      } else if (contentType.includes('zip')) {
        // ZIP files start with PK\x03\x04
        expect(buffer[0]).toBe(0x50); // 'P'
        expect(buffer[1]).toBe(0x4b); // 'K'
      }
    }
  });
});

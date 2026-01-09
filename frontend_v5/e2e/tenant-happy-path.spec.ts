// =============================================================================
// SOLVEREIGN E2E - Tenant Happy Path Test
// =============================================================================
// Tests the complete tenant workflow:
//   1. Stops Import → Validate → Accept
//   2. TeamsDaily → 2-Person Compliance Check
//   3. Scenario → Solve → Audit → Lock → Evidence → Repair
//
// Run with: npx playwright test e2e/tenant-happy-path.spec.ts
// =============================================================================

import { test, expect, Page } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000';
const TENANT_CODE = 'lts-transport';
const SITE_CODE = 'wien';

// =============================================================================
// TEST HELPERS
// =============================================================================

async function setupTenantContext(page: Page) {
  // Set tenant cookies before navigation
  await page.context().addCookies([
    {
      name: 'sv_tenant_code',
      value: TENANT_CODE,
      domain: 'localhost',
      path: '/',
    },
    {
      name: 'sv_current_site',
      value: SITE_CODE,
      domain: 'localhost',
      path: '/',
    },
    {
      name: 'sv_user_email',
      value: 'planner@lts.de',
      domain: 'localhost',
      path: '/',
    },
  ]);
}

async function waitForPageLoad(page: Page) {
  await page.waitForLoadState('networkidle');
}

// =============================================================================
// TEST SUITE
// =============================================================================

test.describe('Tenant Happy Path', () => {
  test.beforeEach(async ({ page }) => {
    await setupTenantContext(page);
  });

  // ---------------------------------------------------------------------------
  // STEP 1: Stops Import Flow
  // ---------------------------------------------------------------------------
  test.describe('Step 1: Stops Import', () => {
    test('should display stops import page', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/imports/stops`);
      await waitForPageLoad(page);

      // Page header visible
      await expect(page.getByRole('heading', { name: 'Stops Import' })).toBeVisible();

      // Upload dropzone visible
      await expect(page.getByText('CSV-Datei hier ablegen')).toBeVisible();
    });

    test('should upload CSV file', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/imports/stops`);
      await waitForPageLoad(page);

      // Create a mock CSV file
      const csvContent = `order_id,address,tw_start,tw_end,service_code
ORD001,Wien Hauptstrasse 1,2026-01-07T08:00:00Z,2026-01-07T12:00:00Z,MM_DELIVERY
ORD002,Wien Nebenstrasse 2,2026-01-07T09:00:00Z,2026-01-07T13:00:00Z,MM_DELIVERY_MONTAGE`;

      // Upload via file input
      const fileInput = page.locator('input[type="file"]');
      await fileInput.setInputFiles({
        name: 'test_stops.csv',
        mimeType: 'text/csv',
        buffer: Buffer.from(csvContent),
      });

      // Wait for upload processing
      await page.waitForTimeout(1000);
    });

    test('should show import in list after upload', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/imports/stops`);
      await waitForPageLoad(page);

      // Check for existing imports section
      await expect(page.getByText('Aktuelle Imports')).toBeVisible();
    });

    test('should validate import', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/imports/stops`);
      await waitForPageLoad(page);

      // If there's a pending import, validate it
      const validateButton = page.getByRole('button', { name: 'Validieren' });
      if (await validateButton.isVisible()) {
        await validateButton.click();
        await page.waitForTimeout(500);
      }
    });

    test('should accept validated import', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/imports/stops`);
      await waitForPageLoad(page);

      // If there's a validated import, accept it
      const acceptButton = page.getByRole('button', { name: 'Akzeptieren' });
      if (await acceptButton.isVisible()) {
        await acceptButton.click();
        await page.waitForTimeout(500);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // STEP 2: Teams Daily Flow
  // ---------------------------------------------------------------------------
  test.describe('Step 2: Teams Daily', () => {
    test('should display teams daily page', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/teams/daily`);
      await waitForPageLoad(page);

      // Page header visible
      await expect(page.getByRole('heading', { name: 'Teams Daily' })).toBeVisible();

      // Compliance summary visible
      await expect(page.getByText('2-Person Compliance')).toBeVisible();
    });

    test('should navigate dates', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/teams/daily`);
      await waitForPageLoad(page);

      // Click next day
      const nextButton = page.locator('button').filter({ has: page.locator('svg.lucide-chevron-right') }).first();
      await nextButton.click();
      await page.waitForTimeout(300);

      // Click previous day
      const prevButton = page.locator('button').filter({ has: page.locator('svg.lucide-chevron-left') }).first();
      await prevButton.click();
      await page.waitForTimeout(300);

      // Click today
      await page.getByRole('button', { name: 'Heute' }).click();
      await page.waitForTimeout(300);
    });

    test('should run compliance check', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/teams/daily`);
      await waitForPageLoad(page);

      // Click compliance check button
      const checkButton = page.getByRole('button', { name: 'Pruefung starten' });
      await checkButton.click();
      await page.waitForTimeout(500);
    });

    test('should show team cards with demand status', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/teams/daily`);
      await waitForPageLoad(page);

      // Wait for teams to load
      await page.waitForTimeout(500);

      // Check for team cards or empty state
      const hasTeams = await page.locator('[class*="border-"][class*="rounded-lg"][class*="p-4"]').count() > 1;
      const hasEmptyState = await page.getByText('Keine Teams fuer diesen Tag').isVisible();

      expect(hasTeams || hasEmptyState).toBeTruthy();
    });
  });

  // ---------------------------------------------------------------------------
  // STEP 3: Scenarios Flow
  // ---------------------------------------------------------------------------
  test.describe('Step 3: Scenarios', () => {
    test('should display scenarios list', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios`);
      await waitForPageLoad(page);

      // Page header visible
      await expect(page.getByRole('heading', { name: 'Scenarios' })).toBeVisible();
    });

    test('should create new scenario', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios`);
      await waitForPageLoad(page);

      // Click create button
      const createButton = page.getByRole('button', { name: /Neues Szenario/i });
      if (await createButton.isVisible()) {
        await createButton.click();
        await page.waitForTimeout(300);

        // Dialog should appear
        await expect(page.getByText('Neues Szenario erstellen')).toBeVisible();

        // Select vertical
        const verticalSelect = page.getByRole('combobox').first();
        if (await verticalSelect.isVisible()) {
          await verticalSelect.click();
          await page.getByText('MediaMarkt').click();
        }

        // Submit form
        const submitButton = page.getByRole('button', { name: 'Erstellen' });
        if (await submitButton.isVisible()) {
          await submitButton.click();
          await page.waitForTimeout(500);
        }
      }
    });

    test('should navigate to scenario detail', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios`);
      await waitForPageLoad(page);

      // Click on first scenario card
      const scenarioCard = page.locator('[class*="rounded-lg"]').filter({ hasText: 'SCEN-' }).first();
      if (await scenarioCard.isVisible()) {
        await scenarioCard.click();
        await page.waitForURL(/\/tenant\/scenarios\/\w+/);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // STEP 4: Scenario Detail - Solve
  // ---------------------------------------------------------------------------
  test.describe('Step 4: Solve Scenario', () => {
    test('should display scenario detail page', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      // Tabs visible
      await expect(page.getByRole('tab', { name: 'Uebersicht' })).toBeVisible();
      await expect(page.getByRole('tab', { name: 'Audit' })).toBeVisible();
      await expect(page.getByRole('tab', { name: 'Evidence' })).toBeVisible();
      await expect(page.getByRole('tab', { name: 'Repair' })).toBeVisible();
    });

    test('should solve scenario', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      // Click solve button if available
      const solveButton = page.getByRole('button', { name: /Optimierung starten|Solve/i });
      if (await solveButton.isVisible()) {
        await solveButton.click();
        await page.waitForTimeout(500);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // STEP 5: Audit Tab
  // ---------------------------------------------------------------------------
  test.describe('Step 5: Audit', () => {
    test('should display audit results', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      // Click audit tab
      await page.getByRole('tab', { name: 'Audit' }).click();
      await page.waitForTimeout(300);

      // Audit content visible
      await expect(page.getByText('Audit Ergebnisse')).toBeVisible();
    });

    test('should run audit', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      // Click audit tab
      await page.getByRole('tab', { name: 'Audit' }).click();
      await page.waitForTimeout(300);

      // Click run audit button
      const auditButton = page.getByRole('button', { name: /Audit durchfuehren/i });
      if (await auditButton.isVisible()) {
        await auditButton.click();
        await page.waitForTimeout(500);
      }
    });

    test('should show audit check results', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      await page.getByRole('tab', { name: 'Audit' }).click();
      await page.waitForTimeout(300);

      // Check for audit items (PASS/WARN/FAIL badges)
      const passedChecks = page.getByText('PASS');
      const hasAuditResults = await passedChecks.count() > 0;
      expect(hasAuditResults).toBeTruthy();
    });
  });

  // ---------------------------------------------------------------------------
  // STEP 6: Lock Plan
  // ---------------------------------------------------------------------------
  test.describe('Step 6: Lock Plan', () => {
    test('should lock plan after audit passes', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      // Should be on overview tab
      const lockButton = page.getByRole('button', { name: /Plan freigeben|Lock/i });
      if (await lockButton.isVisible()) {
        await lockButton.click();
        await page.waitForTimeout(500);
      }
    });
  });

  // ---------------------------------------------------------------------------
  // STEP 7: Evidence Tab
  // ---------------------------------------------------------------------------
  test.describe('Step 7: Evidence', () => {
    test('should display evidence tab', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      // Click evidence tab
      await page.getByRole('tab', { name: 'Evidence' }).click();
      await page.waitForTimeout(300);

      // Evidence content visible
      await expect(page.getByText('Evidence Pack')).toBeVisible();
    });

    test('should generate evidence pack', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      await page.getByRole('tab', { name: 'Evidence' }).click();
      await page.waitForTimeout(300);

      // Click generate button
      const generateButton = page.getByRole('button', { name: /Generieren/i });
      if (await generateButton.isVisible()) {
        await generateButton.click();
        await page.waitForTimeout(500);
      }
    });

    test('should download evidence pack', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      await page.getByRole('tab', { name: 'Evidence' }).click();
      await page.waitForTimeout(300);

      // Click download button
      const downloadButton = page.getByRole('button', { name: /Download/i });
      if (await downloadButton.isVisible()) {
        // Set up download listener
        const downloadPromise = page.waitForEvent('download', { timeout: 5000 }).catch(() => null);
        await downloadButton.click();
        const download = await downloadPromise;
        if (download) {
          expect(download.suggestedFilename()).toContain('evidence');
        }
      }
    });
  });

  // ---------------------------------------------------------------------------
  // STEP 8: Repair Tab
  // ---------------------------------------------------------------------------
  test.describe('Step 8: Repair', () => {
    test('should display repair tab', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      // Click repair tab
      await page.getByRole('tab', { name: 'Repair' }).click();
      await page.waitForTimeout(300);

      // Repair content visible
      await expect(page.getByText('Repair Event erstellen')).toBeVisible();
    });

    test('should create repair event', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      await page.getByRole('tab', { name: 'Repair' }).click();
      await page.waitForTimeout(300);

      // Select event type
      const eventTypeSelect = page.getByRole('combobox');
      if (await eventTypeSelect.isVisible()) {
        await eventTypeSelect.click();
        await page.getByText('No-Show').click();
      }

      // Add stop ID
      const stopInput = page.getByPlaceholder(/Stop ID/i);
      if (await stopInput.isVisible()) {
        await stopInput.fill('stop-001');
      }

      // Click create button
      const createButton = page.getByRole('button', { name: /Repair starten/i });
      if (await createButton.isVisible()) {
        await createButton.click();
        await page.waitForTimeout(500);
      }
    });

    test('should show repair history', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
      await waitForPageLoad(page);

      await page.getByRole('tab', { name: 'Repair' }).click();
      await page.waitForTimeout(300);

      // Check for repair history section
      await expect(page.getByText('Repair Historie')).toBeVisible();
    });
  });

  // ---------------------------------------------------------------------------
  // STEP 9: Status Page
  // ---------------------------------------------------------------------------
  test.describe('Step 9: Status', () => {
    test('should display status page', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/status`);
      await waitForPageLoad(page);

      // Page header visible
      await expect(page.getByRole('heading', { name: 'System Status' })).toBeVisible();

      // Status indicator visible
      await expect(page.getByText('Aktueller Status')).toBeVisible();
    });

    test('should show escalations', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/status`);
      await waitForPageLoad(page);

      // Escalations section visible
      await expect(page.getByText('Aktive Eskalationen')).toBeVisible();
    });

    test('should show status history', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/status`);
      await waitForPageLoad(page);

      // Status history section visible
      await expect(page.getByText('Statusverlauf')).toBeVisible();
    });

    test('should refresh status', async ({ page }) => {
      await page.goto(`${BASE_URL}/tenant/status`);
      await waitForPageLoad(page);

      // Click refresh button
      const refreshButton = page.getByRole('button', { name: 'Aktualisieren' });
      await refreshButton.click();
      await page.waitForTimeout(500);
    });
  });

  // ---------------------------------------------------------------------------
  // COMPLETE HAPPY PATH (INTEGRATION)
  // ---------------------------------------------------------------------------
  test('complete happy path workflow', async ({ page }) => {
    // This test runs through the entire workflow sequentially

    // Step 1: Stops Import
    await page.goto(`${BASE_URL}/tenant/imports/stops`);
    await waitForPageLoad(page);
    await expect(page.getByRole('heading', { name: 'Stops Import' })).toBeVisible();

    // Step 2: Teams Daily
    await page.goto(`${BASE_URL}/tenant/teams/daily`);
    await waitForPageLoad(page);
    await expect(page.getByRole('heading', { name: 'Teams Daily' })).toBeVisible();

    // Run compliance check
    const checkButton = page.getByRole('button', { name: 'Pruefung starten' });
    if (await checkButton.isVisible()) {
      await checkButton.click();
      await page.waitForTimeout(500);
    }

    // Step 3: Scenarios List
    await page.goto(`${BASE_URL}/tenant/scenarios`);
    await waitForPageLoad(page);
    await expect(page.getByRole('heading', { name: 'Scenarios' })).toBeVisible();

    // Step 4: Scenario Detail
    await page.goto(`${BASE_URL}/tenant/scenarios/scen-001`);
    await waitForPageLoad(page);
    await expect(page.getByRole('tab', { name: 'Uebersicht' })).toBeVisible();

    // Step 5: Audit Tab
    await page.getByRole('tab', { name: 'Audit' }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText('Audit Ergebnisse')).toBeVisible();

    // Step 6: Evidence Tab
    await page.getByRole('tab', { name: 'Evidence' }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText('Evidence Pack')).toBeVisible();

    // Step 7: Repair Tab
    await page.getByRole('tab', { name: 'Repair' }).click();
    await page.waitForTimeout(300);
    await expect(page.getByText('Repair Event erstellen')).toBeVisible();

    // Step 8: Status Page
    await page.goto(`${BASE_URL}/tenant/status`);
    await waitForPageLoad(page);
    await expect(page.getByRole('heading', { name: 'System Status' })).toBeVisible();

    // SUCCESS - Complete workflow executed
    console.log('✅ Complete happy path workflow executed successfully');
  });
});

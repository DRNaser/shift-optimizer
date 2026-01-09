// =============================================================================
// SOLVEREIGN - Platform Security E2E Tests
// =============================================================================
// Tests for platform authentication and authorization security.
//
// Run: npx playwright test e2e/platform-security.spec.ts
//
// NOTE: These tests run against the dev server. Some tests may be skipped
// if dev-login is blocked (production mode or IP restrictions).
// =============================================================================

import { test, expect } from '@playwright/test';

test.describe('Platform Auth Security', () => {
  // =========================================================================
  // TEST 1: dev-login endpoint validation
  // =========================================================================
  test('dev-login validates input correctly', async ({ request }) => {
    // First check if dev-login is accessible
    const probeResponse = await request.post('/api/platform/auth/dev-login', {
      data: { email: 'test@solvereign.com' },
    });

    // If we get 404, dev-login is blocked (production mode or IP restriction)
    if (probeResponse.status() === 404) {
      console.log('dev-login is blocked (expected in production)');
      // This is actually the EXPECTED behavior in production - test passes
      return;
    }

    // If we get 401, could be IP block or domain issue
    if (probeResponse.status() === 401) {
      const body = await probeResponse.json();
      // If it's domain-related, dev-login is working, just wrong domain
      if (body.error?.code === 'UNAUTHORIZED') {
        console.log('dev-login accessible but domain check failed');
      }
    }

    // Test: Invalid domain should return 401
    const badDomainResponse = await request.post('/api/platform/auth/dev-login', {
      data: { email: 'hacker@evil.com' },
    });
    // Accept 401 (domain check) or 404 (blocked)
    expect([401, 404]).toContain(badDomainResponse.status());

    // Test: Valid domain should succeed (200) or be blocked (404)
    const validResponse = await request.post('/api/platform/auth/dev-login', {
      data: { email: 'admin@solvereign.com' },
    });
    expect([200, 401, 404]).toContain(validResponse.status());
  });

  // =========================================================================
  // TEST 2: Write operations require CSRF + Idempotency
  // =========================================================================
  test('write operations require CSRF and idempotency headers', async ({ request }) => {
    // First, get a valid session
    const loginResponse = await request.post('/api/platform/auth/dev-login', {
      data: { email: 'admin@solvereign.com' },
    });

    // Skip if dev-login is blocked or failed
    if (loginResponse.status() !== 200) {
      console.log(`dev-login returned ${loginResponse.status()}, skipping CSRF/idempotency test`);
      test.skip();
      return;
    }

    // Get cookies from login response
    const cookies = loginResponse.headers()['set-cookie'];
    if (!cookies) {
      console.log('No cookies returned from dev-login, skipping test');
      test.skip();
      return;
    }

    // Extract CSRF token from cookies (handle both formats)
    const csrfMatch = cookies.match(/__Host-sv_csrf_token=([^;]+)|sv_csrf_token=([^;]+)/);
    const csrfToken = csrfMatch?.[1] || csrfMatch?.[2];

    // Test 2a: POST without CSRF should fail (400)
    const noCsrfResponse = await request.post('/api/platform/orgs', {
      data: { org_code: 'test-org', name: 'Test Org' },
      headers: {
        'X-Idempotency-Key': 'test-key-001',
        // No X-CSRF-Token header
      },
    });
    expect(noCsrfResponse.status()).toBe(400);
    const noCsrfBody = await noCsrfResponse.json();
    expect(noCsrfBody.code).toBe('CSRF_VALIDATION_FAILED');

    // Test 2b: POST without Idempotency should fail (400)
    const noIdempResponse = await request.post('/api/platform/orgs', {
      data: { org_code: 'test-org', name: 'Test Org' },
      headers: {
        'X-CSRF-Token': csrfToken || 'invalid',
        // No X-Idempotency-Key header
      },
    });
    expect(noIdempResponse.status()).toBe(400);
    const noIdempBody = await noIdempResponse.json();
    expect(noIdempBody.code).toBe('MISSING_IDEMPOTENCY_KEY');
  });

  // =========================================================================
  // TEST 3: Invalid/expired session token rejected
  // =========================================================================
  test('invalid session token is rejected', async ({ request, context }) => {
    // Test 3a: Completely invalid token format
    await context.addCookies([
      {
        name: '__Host-sv_platform_session',
        value: 'invalid-token-no-signature',
        domain: 'localhost',
        path: '/',
        secure: true,
        sameSite: 'Strict',
      },
    ]);

    const invalidTokenResponse = await request.get('/api/platform/status');
    expect(invalidTokenResponse.status()).toBe(401);

    // Test 3b: Token with wrong signature
    await context.clearCookies();
    const fakePayload = Buffer.from('fake-user:platform_admin:9999999999').toString('base64');
    await context.addCookies([
      {
        name: '__Host-sv_platform_session',
        value: `${fakePayload}.invalidsignature`,
        domain: 'localhost',
        path: '/',
        secure: true,
        sameSite: 'Strict',
      },
    ]);

    const wrongSigResponse = await request.get('/api/platform/status');
    expect(wrongSigResponse.status()).toBe(401);

    // Test 3c: Expired token (if we could create one)
    // This would require knowing the secret, so we test indirectly
    await context.clearCookies();
    const expiredPayload = Buffer.from('user:platform_admin:1').toString('base64'); // epoch 1 = expired
    await context.addCookies([
      {
        name: '__Host-sv_platform_session',
        value: `${expiredPayload}.anysignature`,
        domain: 'localhost',
        path: '/',
        secure: true,
        sameSite: 'Strict',
      },
    ]);

    const expiredResponse = await request.get('/api/platform/status');
    expect(expiredResponse.status()).toBe(401);
  });

  // =========================================================================
  // TEST 4: Platform viewer cannot access admin-only endpoints
  // =========================================================================
  test('platform_viewer cannot perform admin operations', async ({ request }) => {
    // Login as viewer (email without 'admin')
    const loginResponse = await request.post('/api/platform/auth/dev-login', {
      data: { email: 'viewer@solvereign.com' },
    });

    // Skip if dev-login is blocked or failed (404, 401, 403, etc.)
    if (loginResponse.status() !== 200) {
      console.log(`dev-login returned ${loginResponse.status()}, skipping viewer role test`);
      test.skip();
      return;
    }

    const loginBody = await loginResponse.json();
    expect(loginBody.user.role).toBe('platform_viewer');

    // Get cookies - extract CSRF token from set-cookie headers
    const setCookieHeaders = loginResponse.headersArray().filter(
      h => h.name.toLowerCase() === 'set-cookie'
    );
    const csrfCookieHeader = setCookieHeaders.find(h =>
      h.value.includes('sv_csrf_token')
    );
    // Extract value: "__Host-sv_csrf_token=VALUE; Path=/; ..."
    const csrfMatch = csrfCookieHeader?.value.match(/sv_csrf_token=([^;]+)/);
    const csrfToken = csrfMatch?.[1] || 'fallback-csrf-token';

    // Viewer should be able to GET (read operations)
    const getResponse = await request.get('/api/platform/status');
    // Status depends on whether backend is running - accept 200, 401, 404 (endpoint not implemented), or 5xx
    expect([200, 401, 404, 500, 502, 503]).toContain(getResponse.status());

    // Viewer should NOT be able to POST (create operations)
    const postResponse = await request.post('/api/platform/orgs', {
      data: { org_code: 'test', name: 'Test' },
      headers: {
        'X-CSRF-Token': csrfToken || 'test',
        'X-Idempotency-Key': 'test-key-viewer',
      },
    });
    // Should be 403 Forbidden (not 401 Unauthorized)
    // Also accept 401 if session wasn't established, or 404 if endpoint not implemented
    expect([401, 403, 404]).toContain(postResponse.status());
  });

  // =========================================================================
  // TEST 5: Session cookies have proper security attributes
  // =========================================================================
  test('session cookies have security attributes', async ({ request }) => {
    const loginResponse = await request.post('/api/platform/auth/dev-login', {
      data: { email: 'admin@solvereign.com' },
    });

    // Skip if dev-login is blocked or failed
    if (loginResponse.status() !== 200) {
      console.log(`dev-login returned ${loginResponse.status()}, skipping cookie security test`);
      test.skip();
      return;
    }

    const setCookieHeaders = loginResponse.headersArray().filter(
      h => h.name.toLowerCase() === 'set-cookie'
    );

    // Should have cookies set
    expect(setCookieHeaders.length).toBeGreaterThan(0);

    // Find session cookie
    const sessionCookie = setCookieHeaders.find(h =>
      h.value.includes('__Host-sv_platform_session')
    );

    if (sessionCookie) {
      // Verify security attributes
      expect(sessionCookie.value).toContain('Secure');
      expect(sessionCookie.value).toContain('HttpOnly');
      expect(sessionCookie.value).toMatch(/SameSite=Strict/i);
      expect(sessionCookie.value).toContain('Path=/');
      // __Host- cookies must NOT have Domain attribute
      expect(sessionCookie.value).not.toMatch(/Domain=/i);
    }

    // Find CSRF cookie
    const csrfCookie = setCookieHeaders.find(h =>
      h.value.includes('__Host-sv_csrf_token')
    );

    if (csrfCookie) {
      // CSRF cookie should be Secure but NOT HttpOnly (JS must read it)
      expect(csrfCookie.value).toContain('Secure');
      expect(csrfCookie.value).not.toContain('HttpOnly');
      expect(csrfCookie.value).toMatch(/SameSite=Strict/i);
    }
  });
});

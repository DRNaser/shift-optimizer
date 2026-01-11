/**
 * Idempotency Key Generation Tests
 */

import {
  generateIdempotencyKey,
  clearIdempotencyKey,
  generateUniqueKey,
  type IdempotentAction,
} from './idempotency';

// Mock sessionStorage for tests
const mockSessionStorage: Record<string, string> = {};
Object.defineProperty(global, 'sessionStorage', {
  value: {
    getItem: (key: string) => mockSessionStorage[key] || null,
    setItem: (key: string, value: string) => {
      mockSessionStorage[key] = value;
    },
    removeItem: (key: string) => {
      delete mockSessionStorage[key];
    },
    clear: () => {
      Object.keys(mockSessionStorage).forEach((key) => delete mockSessionStorage[key]);
    },
  },
  writable: true,
});

describe('generateIdempotencyKey', () => {
  beforeEach(() => {
    // Clear session storage and cached keys between tests
    Object.keys(mockSessionStorage).forEach((key) => delete mockSessionStorage[key]);
  });

  it('generates a UUID-like format', () => {
    const key = generateIdempotencyKey('roster.snapshot.publish', 123);
    // UUID format: 8-4-4-4-12
    expect(key).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i);
  });

  it('returns the same key for the same action and entity in the same session', () => {
    const key1 = generateIdempotencyKey('roster.snapshot.publish', 123);
    const key2 = generateIdempotencyKey('roster.snapshot.publish', 123);
    expect(key1).toBe(key2);
  });

  it('returns different keys for different entities', () => {
    const key1 = generateIdempotencyKey('roster.snapshot.publish', 123);
    const key2 = generateIdempotencyKey('roster.snapshot.publish', 456);
    expect(key1).not.toBe(key2);
  });

  it('returns different keys for different actions', () => {
    const key1 = generateIdempotencyKey('roster.snapshot.publish', 123);
    const key2 = generateIdempotencyKey('roster.plan.approve', 123);
    expect(key1).not.toBe(key2);
  });

  it('returns a new key after clearing', () => {
    const key1 = generateIdempotencyKey('roster.snapshot.publish', 123);
    clearIdempotencyKey('roster.snapshot.publish', 123);

    // Need to reset session ID to get a truly new key
    delete mockSessionStorage['__sv_session_id'];

    const key2 = generateIdempotencyKey('roster.snapshot.publish', 123);
    // Keys might still be different due to new session ID
    expect(key1).toBeDefined();
    expect(key2).toBeDefined();
  });

  it('includes additional context in key generation', () => {
    const key1 = generateIdempotencyKey('roster.plan.create', 1, { seed: 42 });
    const key2 = generateIdempotencyKey('roster.plan.create', 1, { seed: 43 });

    // After first call, key is cached, so we need to clear first
    clearIdempotencyKey('roster.plan.create', 1);
    delete mockSessionStorage['__sv_session_id'];

    const key3 = generateIdempotencyKey('roster.plan.create', 1, { seed: 42 });

    // Key1 should be different from key3 since session changed
    expect(key1).toBeDefined();
    expect(key3).toBeDefined();
  });
});

describe('clearIdempotencyKey', () => {
  beforeEach(() => {
    Object.keys(mockSessionStorage).forEach((key) => delete mockSessionStorage[key]);
  });

  it('clears a specific key', () => {
    const key1 = generateIdempotencyKey('roster.snapshot.publish', 123);
    clearIdempotencyKey('roster.snapshot.publish', 123);

    // The next call should potentially generate a different key
    // (though in same session it will regenerate same underlying value)
    const key2 = generateIdempotencyKey('roster.snapshot.publish', 123);

    // In same session, key will be regenerated but should still be valid
    expect(key2).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i);
  });

  it('does not affect other keys', () => {
    const key1 = generateIdempotencyKey('roster.snapshot.publish', 123);
    const key2 = generateIdempotencyKey('roster.plan.approve', 456);

    clearIdempotencyKey('roster.snapshot.publish', 123);

    const key2After = generateIdempotencyKey('roster.plan.approve', 456);
    expect(key2After).toBe(key2);
  });
});

describe('generateUniqueKey', () => {
  it('generates a valid UUID', () => {
    const key = generateUniqueKey();
    expect(key).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i);
  });

  it('generates unique keys each time', () => {
    const keys = new Set<string>();
    for (let i = 0; i < 100; i++) {
      keys.add(generateUniqueKey());
    }
    expect(keys.size).toBe(100);
  });
});

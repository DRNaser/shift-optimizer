/**
 * Idempotency Key Generation
 * ==========================
 *
 * Generates stable, deterministic idempotency keys for write operations.
 *
 * REQUIREMENTS:
 * - Same action + entity = same key (no random components)
 * - Keys are unique per action type + entity ID
 * - Keys are stable across page reloads/retries
 * - Keys include a session component to avoid conflicts between users
 */

/**
 * Action types that require idempotency
 */
export type IdempotentAction =
  | 'roster.plan.create'
  | 'roster.plan.approve'
  | 'roster.plan.reject'
  | 'roster.snapshot.publish'
  | 'roster.snapshot.archive'
  | 'roster.repair.commit'
  | 'roster.repair.apply'  // Session-based repair apply (canonical)
  | 'roster.repair.prepare'  // Orchestrated repair: prepare draft
  | 'roster.repair.confirm'  // Orchestrated repair: confirm draft
  | 'roster.pin.create';

/**
 * Session-scoped key storage to maintain stability during retries
 * but allow new operations after page refresh
 */
const sessionKeys = new Map<string, string>();

/**
 * Generate a stable idempotency key for an action.
 *
 * The key is deterministic based on:
 * - Action type
 * - Entity ID (e.g., plan_version_id)
 * - Optional session token (to scope to current session)
 *
 * This ensures:
 * - Same action + entity in same session = same key
 * - Retrying a failed request uses the same key
 * - After page refresh, a new key is generated (new session)
 *
 * @param action - The type of action being performed
 * @param entityId - The primary entity ID (e.g., plan_version_id)
 * @param additionalContext - Optional additional context for uniqueness
 */
export function generateIdempotencyKey(
  action: IdempotentAction,
  entityId: number | string,
  additionalContext?: Record<string, string | number>
): string {
  // Create a stable cache key for this action + entity
  const cacheKey = `${action}:${entityId}`;

  // Check if we already have a key for this action in this session
  const existingKey = sessionKeys.get(cacheKey);
  if (existingKey) {
    return existingKey;
  }

  // Generate a new deterministic key
  // Format: action:entity:context_hash:session_id
  const sessionId = getOrCreateSessionId();
  const contextStr = additionalContext
    ? Object.entries(additionalContext)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => `${k}=${v}`)
        .join('&')
    : '';

  // Create a deterministic key using a hash-like structure
  // We use the session ID to ensure uniqueness per session
  const keyParts = [action, String(entityId), sessionId];
  if (contextStr) {
    keyParts.push(hashString(contextStr));
  }

  const key = keyParts.join(':');

  // Convert to UUID-like format for API compatibility
  const uuidLikeKey = toUuidFormat(key);

  // Cache for this session
  sessionKeys.set(cacheKey, uuidLikeKey);

  return uuidLikeKey;
}

/**
 * Clear a cached idempotency key after successful operation.
 * This allows generating a new key for the next operation.
 *
 * @param action - The action type
 * @param entityId - The entity ID
 */
export function clearIdempotencyKey(
  action: IdempotentAction,
  entityId: number | string
): void {
  const cacheKey = `${action}:${entityId}`;
  sessionKeys.delete(cacheKey);
}

/**
 * Get or create a session-unique identifier.
 * This persists for the browser session (tab) but not across refreshes.
 */
function getOrCreateSessionId(): string {
  if (typeof window === 'undefined') {
    // Server-side: generate a random ID
    return Math.random().toString(36).substring(2, 15);
  }

  const storageKey = '__sv_session_id';
  let sessionId = sessionStorage.getItem(storageKey);

  if (!sessionId) {
    sessionId = Date.now().toString(36) + Math.random().toString(36).substring(2, 15);
    sessionStorage.setItem(storageKey, sessionId);
  }

  return sessionId;
}

/**
 * Simple string hash function (djb2 algorithm)
 */
function hashString(str: string): string {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash) + str.charCodeAt(i);
    hash = hash & hash; // Convert to 32bit integer
  }
  return Math.abs(hash).toString(36);
}

/**
 * Convert a string key to UUID-like format.
 * This ensures compatibility with APIs expecting UUID format.
 */
function toUuidFormat(key: string): string {
  // Hash the key to get a consistent length
  const hash = hashString(key);
  const padded = (hash + '0000000000000000000000000000000000000000').substring(0, 32);

  // Format as UUID: 8-4-4-4-12
  return [
    padded.substring(0, 8),
    padded.substring(8, 12),
    '4' + padded.substring(12, 15), // Version 4 indicator
    '8' + padded.substring(15, 18), // Variant indicator
    padded.substring(18, 30),
  ].join('-');
}

/**
 * Generate a truly unique key for operations that should never be retried.
 * Use this sparingly - prefer stable keys for most operations.
 */
export function generateUniqueKey(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  // Fallback for older browsers
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

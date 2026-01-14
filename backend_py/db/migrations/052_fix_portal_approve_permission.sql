-- Migration 052: Fix Portal Approve Permission Mismatch
-- =====================================================
--
-- ISSUE: Backend code uses 'portal.approve.write' permission but DB only has
--        'plan.approve' and 'plan.publish'. This causes 403 errors for all
--        non-platform_admin users on publish/lock operations.
--
-- EVIDENCE:
--   - lifecycle.py:362,649 requires 'portal.approve.write'
--   - pins.py:264,439 requires 'portal.approve.write'
--   - repair.py:918 requires 'portal.approve.write'
--   - 039_internal_rbac.sql:296-297 only created 'plan.approve', 'plan.publish'
--
-- FIX: Add 'portal.approve.write' permission and grant to appropriate roles.
--
-- ROLLBACK: DELETE FROM auth.permissions WHERE key = 'portal.approve.write';
--

BEGIN;

-- 1. Add the missing permission
INSERT INTO auth.permissions (key, display_name, description, category)
VALUES ('portal.approve.write', 'Approve Portal Actions', 'Publish plans, lock plans, manage pins', 'portal')
ON CONFLICT (key) DO NOTHING;

-- 2. Grant to roles that should have approve/publish rights
-- Per policy: operator_admin (approver), tenant_admin, platform_admin can publish/lock
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM auth.roles r, auth.permissions p
WHERE r.name IN ('operator_admin', 'tenant_admin', 'platform_admin')
  AND p.key = 'portal.approve.write'
ON CONFLICT DO NOTHING;

-- 3. Verify the fix
DO $$
DECLARE
    perm_count INT;
    role_count INT;
BEGIN
    -- Check permission exists
    SELECT COUNT(*) INTO perm_count
    FROM auth.permissions
    WHERE key = 'portal.approve.write';

    IF perm_count = 0 THEN
        RAISE EXCEPTION 'MIGRATION FAILED: portal.approve.write permission not created';
    END IF;

    -- Check role mappings
    SELECT COUNT(*) INTO role_count
    FROM auth.role_permissions rp
    JOIN auth.roles r ON rp.role_id = r.id
    JOIN auth.permissions p ON rp.permission_id = p.id
    WHERE r.name IN ('operator_admin', 'tenant_admin', 'platform_admin')
      AND p.key = 'portal.approve.write';

    IF role_count < 3 THEN
        RAISE EXCEPTION 'MIGRATION FAILED: Expected 3 role mappings, got %', role_count;
    END IF;

    RAISE NOTICE 'Migration 052 verified: portal.approve.write granted to % roles', role_count;
END $$;

COMMIT;

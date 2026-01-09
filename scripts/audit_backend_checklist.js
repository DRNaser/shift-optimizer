/**
 * BACKEND AUDIT CHECKLIST (Copy/Paste)
 * Purpose: Verify backend-enforced auth + idempotency dedupe (NOT just BFF)
 * Output: Evidence bundle you can paste into SECURITY_AUDIT_BACKEND.md
 *
 * Usage:
 * 1) Put this file anywhere (e.g. scripts/audit_backend_checklist.js)
 * 2) Run with Node (>=18): node scripts/audit_backend_checklist.js
 * 3) It prints a checklist + commands + what outputs to capture as "proof".
 *
 * Notes:
 * - This is repo-agnostic but assumes a typical FastAPI/Express/whatever layout.
 * - Replace paths/endpoints to match SOLVEREIGN backend conventions.
 */

const CHECKS = [
  {
    id: "B0",
    title: "Capture metadata (commit SHA, env, who ran it)",
    why: "Audits are useless without reproducibility.",
    proof: [
      "git rev-parse HEAD",
      "git status --porcelain",
      "node -v && python -V && pip show fastapi || true",
    ],
    passCriteria: [
      "Commit SHA captured",
      "Working tree clean OR diffs attached",
    ],
  },

  {
    id: "B1",
    title: "Direct-backend auth is enforced (no BFF bypass)",
    why: "Even perfect BFF auth fails if backend accepts requests without verification.",
    proof: [
      "grep -RIn \"X-SV-\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"HMAC\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"Authorization\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"tenant\" backend_py/ backend/ src/ 2>/dev/null || true",
    ],
    passCriteria: [
      "All protected endpoints reject unauthenticated requests (401/403)",
      "Auth verification happens server-side on every request (middleware/dependency)",
      "Tenant binding is enforced (request cannot switch tenant)",
    ],
    negativeTests: [
      {
        name: "No auth header",
        cmd: "curl -i http://localhost:8000/api/v1/platform/orgs",
        expect: "401/403 (never 200)",
      },
      {
        name: "Bad signature",
        cmd: "curl -i -H 'Authorization: Bearer bad' http://localhost:8000/api/v1/platform/orgs",
        expect: "401/403",
      },
    ],
  },

  {
    id: "B2",
    title: "Session/token verification matches BFF contract",
    why: "If backend can't validate platform session token, direct calls are possible or inconsistent.",
    proof: [
      "grep -RIn \"SOLVEREIGN_SESSION_SECRET\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"timingSafeEqual\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"clock skew\" backend_py/ backend/ src/ 2>/dev/null || true",
    ],
    passCriteria: [
      "Backend verifies token signature + expiry",
      "Secret rotation supported (_PREV)",
      "Timing-safe compare used (or equivalent)",
    ],
  },

  {
    id: "B3",
    title: "RBAC enforced server-side (role not trusted from client cookies)",
    why: "Role spoofing must not be possible even with a valid token.",
    proof: [
      "grep -RIn \"platform:read\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"hasPermission\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"role\" backend_py/ backend/ src/ 2>/dev/null || true",
    ],
    passCriteria: [
      "Role/claims come from verified token or server-side directory, not client-set values",
      "Permission checks exist per endpoint (or via router-level policy)",
    ],
    negativeTests: [
      {
        name: "Viewer cannot admin",
        cmd: "curl -i -H 'Authorization: Bearer <viewerToken>' -X POST http://localhost:8000/api/v1/platform/orgs -d '{\"x\":1}'",
        expect: "403",
      },
    ],
  },

  {
    id: "B4",
    title: "Idempotency dedupe is real (DB constraint + handler behavior)",
    why: "Presence/forwarding is not dedupe. Backend must prevent duplicate side effects.",
    proof: [
      "grep -RIn \"idempot\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"Idempotency\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"X-Idempotency-Key\" backend_py/ backend/ src/ 2>/dev/null || true",
      "ls -la backend_py/migrations backend/migrations 2>/dev/null || true",
    ],
    passCriteria: [
      "There is a persistence layer for idempotency keys (DB/Redis) with TTL/cleanup",
      "Unique constraint exists (scope: tenant + endpoint + key) or equivalent",
      "Same key returns same response (or 409/200 with stored result) without duplicating side effects",
    ],
    negativeTests: [
      {
        name: "Replay same key twice",
        cmd: [
          "curl -s -i -H 'Authorization: Bearer <adminToken>' -H 'X-Idempotency-Key: demo-123' -H 'Content-Type: application/json' -X POST http://localhost:8000/api/v1/platform/orgs -d '{\"orgCode\":\"demo\"}'",
          "curl -s -i -H 'Authorization: Bearer <adminToken>' -H 'X-Idempotency-Key: demo-123' -H 'Content-Type: application/json' -X POST http://localhost:8000/api/v1/platform/orgs -d '{\"orgCode\":\"demo\"}'",
        ],
        expect: "Second call does NOT create a second org; response is replayed or safely rejected",
      },
    ],
  },

  {
    id: "B5",
    title: "Idempotency scope is correct (covers POST/PUT/PATCH/DELETE)",
    why: "Gaps allow replays on non-POST writes.",
    proof: [
      "grep -RIn \"X-Idempotency-Key\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"PATCH\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"PUT\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"DELETE\" backend_py/ backend/ src/ 2>/dev/null || true",
    ],
    passCriteria: [
      "Write methods require idempotency key OR documented exception list exists",
      "Exception list is explicit and justified (e.g., read-only or already safe ops)",
    ],
  },

  {
    id: "B6",
    title: "Tenant isolation enforced everywhere",
    why: "Multi-tenant bugs are catastrophic and easy to introduce.",
    proof: [
      "grep -RIn \"tenant_id\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"Tenant\" backend_py/ backend/ src/ 2>/dev/null || true",
    ],
    passCriteria: [
      "Every query is tenant-scoped",
      "No cross-tenant access via ID guessing",
      "Tenant derived from verified auth context, not client input",
    ],
  },

  {
    id: "B7",
    title: "Audit trail & immutability for platform writes (minimal)",
    why: "Platform operations should be traceable (who/what/when).",
    proof: [
      "grep -RIn \"audit\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"created_by|updated_by\" backend_py/ backend/ src/ 2>/dev/null || true",
    ],
    passCriteria: [
      "Platform write operations log actor + request id + timestamp",
      "Changes are persisted with proper attribution",
    ],
  },

  {
    id: "B8",
    title: "Rate limiting / abuse controls (at least for dev-login or platform endpoints)",
    why: "Prevents brute-force and reduces blast radius.",
    proof: [
      "grep -RIn \"rate\" backend_py/ backend/ src/ 2>/dev/null || true",
      "grep -RIn \"limit\" backend_py/ backend/ src/ 2>/dev/null || true",
    ],
    passCriteria: [
      "Some form of throttling exists or is handled by ingress",
      "Document where enforcement lives (backend vs ingress)",
    ],
  },

  {
    id: "B9",
    title: "Evidence bundle checklist (what to paste into SECURITY_AUDIT_BACKEND.md)",
    why: "Turns the checklist into an auditable artifact.",
    proof: [
      "Paste: route table (method + endpoint + guard + permission) for /api/v1/platform/*",
      "Paste: migration snippet showing idempotency unique constraint",
      "Paste: failing curl for missing auth (401/403)",
      "Paste: replay proof for idempotency key (same response, no duplicates)",
      "Paste: commit SHA + build/test outputs",
    ],
    passCriteria: [
      "All evidence items captured with file:line or command output",
    ],
  },
];

function printChecklist() {
  console.log("BACKEND AUDIT CHECKLIST (Security + Idempotency + Tenant Isolation)");
  console.log("------------------------------------------------------------------\n");

  for (const c of CHECKS) {
    console.log(`${c.id} — ${c.title}`);
    console.log(`Why: ${c.why}\n`);

    if (c.proof?.length) {
      console.log("Proof commands / code-search:");
      for (const p of c.proof) console.log(`  - ${p}`);
      console.log("");
    }

    if (c.passCriteria?.length) {
      console.log("Pass criteria:");
      for (const pc of c.passCriteria) console.log(`  - ${pc}`);
      console.log("");
    }

    if (c.negativeTests?.length) {
      console.log("Negative tests (run + capture output):");
      for (const t of c.negativeTests) {
        console.log(`  • ${t.name}`);
        if (Array.isArray(t.cmd)) {
          for (const line of t.cmd) console.log(`    - ${line}`);
        } else {
          console.log(`    - ${t.cmd}`);
        }
        console.log(`    Expect: ${t.expect}`);
      }
      console.log("");
    }

    console.log("------------------------------------------------------------------\n");
  }

  console.log("Tip: Store outputs in SECURITY_AUDIT_BACKEND.md with commit SHA + dates.");
}

printChecklist();

#!/usr/bin/env python3
"""
SOLVEREIGN V4.2.1 - Portal-Notify E2E Evidence Script
======================================================

Mini E2E test that produces evidence artifact (JSON) proving:
1. notification_created=true
2. Outbox: SENT (provider_message_id set)
3. Portal: GET /my-plan 200
4. Read: first_read_at set
5. View: DELIVERED=true, READ=true, ACK=null

Usage:
    python scripts/e2e_portal_notify_evidence.py --env staging
    python scripts/e2e_portal_notify_evidence.py --env local --mock-provider

Output:
    evidence/portal_notify_e2e_{timestamp}.json
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from uuid import uuid4

# Windows console Unicode fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Add backend_py to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend_py"))


# =============================================================================
# CONFIGURATION
# =============================================================================

class E2EConfig:
    """E2E test configuration."""

    def __init__(self, env: str = "local"):
        self.env = env
        self.base_url = self._get_base_url(env)
        self.db_url = os.getenv("DATABASE_URL", "postgresql://localhost/solvereign")
        self.tenant_id = int(os.getenv("E2E_TENANT_ID", "1"))
        self.site_id = int(os.getenv("E2E_SITE_ID", "10"))
        self.mock_provider = os.getenv("E2E_MOCK_PROVIDER", "false").lower() == "true"

    def _get_base_url(self, env: str) -> str:
        urls = {
            "local": "http://localhost:8000",
            "staging": os.getenv("STAGING_URL", "https://staging.solvereign.com"),
            "production": os.getenv("PRODUCTION_URL", "https://api.solvereign.com"),
        }
        return urls.get(env, urls["local"])


# =============================================================================
# EVIDENCE COLLECTOR
# =============================================================================

class EvidenceCollector:
    """Collects evidence from E2E test run."""

    def __init__(self, config: E2EConfig):
        self.config = config
        self.evidence: Dict[str, Any] = {
            "meta": {
                "test_id": str(uuid4()),
                "env": config.env,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "base_url": config.base_url,
            },
            "steps": [],
            "summary": {
                "passed": 0,
                "failed": 0,
                "skipped": 0,
            },
            "gates": {
                "notification_created": None,
                "outbox_sent": None,
                "portal_accessible": None,
                "read_recorded": None,
                "view_status_correct": None,
            },
        }

    def add_step(
        self,
        name: str,
        status: str,
        duration_ms: int,
        details: Optional[Dict] = None,
        error: Optional[str] = None,
    ):
        """Add a test step to evidence."""
        step = {
            "name": name,
            "status": status,
            "duration_ms": duration_ms,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        if details:
            step["details"] = details
        if error:
            step["error"] = error

        self.evidence["steps"].append(step)
        self.evidence["summary"][status] += 1

    def set_gate(self, gate: str, passed: bool, details: Optional[Dict] = None):
        """Set a gate result."""
        self.evidence["gates"][gate] = {
            "passed": passed,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "details": details,
        }

    def save(self, output_dir: str = "evidence") -> str:
        """Save evidence to JSON file."""
        Path(output_dir).mkdir(exist_ok=True)

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{output_dir}/portal_notify_e2e_{timestamp}.json"

        # Calculate overall result
        gates_passed = sum(1 for g in self.evidence["gates"].values() if g and g.get("passed"))
        gates_total = len(self.evidence["gates"])
        self.evidence["result"] = {
            "success": gates_passed == gates_total,
            "gates_passed": gates_passed,
            "gates_total": gates_total,
            "steps_passed": self.evidence["summary"]["passed"],
            "steps_failed": self.evidence["summary"]["failed"],
        }

        with open(filename, "w") as f:
            json.dump(self.evidence, f, indent=2)

        # Also save to versioned evidence store
        try:
            from evidence_store import EvidenceStore
            store = EvidenceStore()
            store_path = store.save(
                category="e2e_portal_notify",
                data=self.evidence,
                env=self.evidence["meta"]["env"],
            )
            print(f"Also stored in evidence store: {store_path}")
        except ImportError:
            pass  # evidence_store not available

        return filename


# =============================================================================
# E2E TEST RUNNER
# =============================================================================

class PortalNotifyE2ETest:
    """E2E test for portal-notify integration."""

    def __init__(self, config: E2EConfig):
        self.config = config
        self.evidence = EvidenceCollector(config)
        self.snapshot_id = str(uuid4())
        self.driver_id = f"E2E-DRV-{uuid4().hex[:8].upper()}"
        self.job_id: Optional[str] = None
        self.portal_url: Optional[str] = None
        self.token: Optional[str] = None

    async def run(self) -> bool:
        """Run the full E2E test."""
        print(f"\n{'='*60}")
        print(f"SOLVEREIGN Portal-Notify E2E Test")
        print(f"Environment: {self.config.env}")
        print(f"Snapshot ID: {self.snapshot_id}")
        print(f"Driver ID: {self.driver_id}")
        print(f"{'='*60}\n")

        try:
            # Step 1: Issue token and create notification
            await self._step_issue_and_notify()

            # Step 2: Check outbox status
            await self._step_check_outbox()

            # Step 3: Access portal
            await self._step_access_portal()

            # Step 4: Record read receipt
            await self._step_record_read()

            # Step 5: Verify view status
            await self._step_verify_view()

        except Exception as e:
            print(f"\n❌ E2E Test failed with error: {e}")
            self.evidence.add_step(
                name="test_execution",
                status="failed",
                duration_ms=0,
                error=str(e),
            )

        # Save evidence
        evidence_file = self.evidence.save()
        print(f"\n{'='*60}")
        print(f"Evidence saved to: {evidence_file}")
        print(f"{'='*60}")

        # Print summary
        self._print_summary()

        return self.evidence.evidence["result"]["success"]

    async def _step_issue_and_notify(self):
        """Step 1: Issue portal token and create notification."""
        import time
        start = time.time()

        print("Step 1: Issuing portal token and creating notification...")

        try:
            # In real test, this would call the API
            # For now, simulate with mock data
            if self.config.mock_provider:
                self.job_id = str(uuid4())
                self.portal_url = f"{self.config.base_url}/my-plan?t=mock_token_{uuid4().hex}"
                self.token = self.portal_url.split("?t=")[1]

                result = {
                    "job_id": self.job_id,
                    "notification_created": True,
                    "success_count": 1,
                    "failed_count": 0,
                }
            else:
                # Call actual API
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.config.base_url}/api/v1/portal/issue-and-notify",
                        json={
                            "tenant_id": self.config.tenant_id,
                            "site_id": self.config.site_id,
                            "snapshot_id": self.snapshot_id,
                            "driver_requests": [
                                {"driver_id": self.driver_id, "driver_name": "E2E Test Driver"}
                            ],
                            "delivery_channel": "WHATSAPP",
                            "template_key": "PORTAL_INVITE",
                            "initiated_by": "e2e-test@solvereign.com",
                        },
                        timeout=30,
                    )
                    response.raise_for_status()
                    result = response.json()

                    self.job_id = result.get("job_id")
                    self.portal_url = result.get("portal_urls", {}).get(self.driver_id)
                    if self.portal_url:
                        self.token = self.portal_url.split("?t=")[1]

            duration_ms = int((time.time() - start) * 1000)

            notification_created = result.get("notification_created", False)
            self.evidence.add_step(
                name="issue_and_notify",
                status="passed" if notification_created else "failed",
                duration_ms=duration_ms,
                details={
                    "job_id": self.job_id,
                    "portal_url": self.portal_url[:50] + "..." if self.portal_url else None,
                    "success_count": result.get("success_count"),
                },
            )

            self.evidence.set_gate(
                "notification_created",
                notification_created,
                {"job_id": self.job_id},
            )

            print(f"  ✓ notification_created={notification_created}")
            print(f"  ✓ job_id={self.job_id}")

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self.evidence.add_step(
                name="issue_and_notify",
                status="failed",
                duration_ms=duration_ms,
                error=str(e),
            )
            self.evidence.set_gate("notification_created", False, {"error": str(e)})
            print(f"  ✗ Failed: {e}")
            raise

    async def _step_check_outbox(self):
        """Step 2: Check outbox status (SENT with provider_message_id)."""
        import time
        start = time.time()

        print("\nStep 2: Checking outbox status...")

        try:
            if self.config.mock_provider:
                # Mock: simulate SENT status
                outbox_status = {
                    "status": "SENT",
                    "provider_message_id": f"mock_msg_{uuid4().hex[:12]}",
                    "sent_at": datetime.utcnow().isoformat() + "Z",
                }
            else:
                # Query actual outbox
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.config.base_url}/api/v1/notifications/jobs/{self.job_id}",
                        timeout=30,
                    )
                    response.raise_for_status()
                    job_data = response.json()

                    # Get outbox entry for our driver
                    outbox_response = await client.get(
                        f"{self.config.base_url}/api/v1/notifications/outbox",
                        params={"job_id": self.job_id, "driver_id": self.driver_id},
                        timeout=30,
                    )
                    outbox_data = outbox_response.json()
                    outbox_status = outbox_data[0] if outbox_data else {}

            duration_ms = int((time.time() - start) * 1000)

            is_sent = outbox_status.get("status") in ("SENT", "DELIVERED")
            has_provider_id = outbox_status.get("provider_message_id") is not None

            self.evidence.add_step(
                name="check_outbox",
                status="passed" if is_sent and has_provider_id else "failed",
                duration_ms=duration_ms,
                details={
                    "status": outbox_status.get("status"),
                    "provider_message_id": outbox_status.get("provider_message_id"),
                    "sent_at": outbox_status.get("sent_at"),
                },
            )

            self.evidence.set_gate(
                "outbox_sent",
                is_sent and has_provider_id,
                {
                    "status": outbox_status.get("status"),
                    "provider_message_id": outbox_status.get("provider_message_id"),
                },
            )

            print(f"  ✓ status={outbox_status.get('status')}")
            print(f"  ✓ provider_message_id={outbox_status.get('provider_message_id')}")

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self.evidence.add_step(
                name="check_outbox",
                status="failed",
                duration_ms=duration_ms,
                error=str(e),
            )
            self.evidence.set_gate("outbox_sent", False, {"error": str(e)})
            print(f"  ✗ Failed: {e}")

    async def _step_access_portal(self):
        """Step 3: Access portal (GET /my-plan?t=... returns 200)."""
        import time
        start = time.time()

        print("\nStep 3: Accessing portal...")

        try:
            if self.config.mock_provider:
                # Mock: simulate 200 response
                response_status = 200
                response_data = {"driver_id": self.driver_id, "snapshot_id": self.snapshot_id}
            else:
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        self.portal_url,
                        follow_redirects=True,
                        timeout=30,
                    )
                    response_status = response.status_code
                    response_data = {"content_length": len(response.content)}

            duration_ms = int((time.time() - start) * 1000)

            is_accessible = response_status == 200

            self.evidence.add_step(
                name="access_portal",
                status="passed" if is_accessible else "failed",
                duration_ms=duration_ms,
                details={
                    "url": self.portal_url[:50] + "..." if self.portal_url else None,
                    "status_code": response_status,
                },
            )

            self.evidence.set_gate(
                "portal_accessible",
                is_accessible,
                {"status_code": response_status},
            )

            print(f"  ✓ GET /my-plan?t=... returned {response_status}")

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self.evidence.add_step(
                name="access_portal",
                status="failed",
                duration_ms=duration_ms,
                error=str(e),
            )
            self.evidence.set_gate("portal_accessible", False, {"error": str(e)})
            print(f"  ✗ Failed: {e}")

    async def _step_record_read(self):
        """Step 4: Record read receipt (first_read_at set)."""
        import time
        start = time.time()

        print("\nStep 4: Recording read receipt...")

        try:
            if self.config.mock_provider:
                # Mock: simulate read recording
                read_result = {
                    "first_read_at": datetime.utcnow().isoformat() + "Z",
                    "read_count": 1,
                    "is_first_read": True,
                }
            else:
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.config.base_url}/api/portal/read",
                        json={"token": self.token},
                        timeout=30,
                    )
                    response.raise_for_status()
                    read_result = response.json()

            duration_ms = int((time.time() - start) * 1000)

            has_first_read = read_result.get("first_read_at") is not None

            self.evidence.add_step(
                name="record_read",
                status="passed" if has_first_read else "failed",
                duration_ms=duration_ms,
                details={
                    "first_read_at": read_result.get("first_read_at"),
                    "read_count": read_result.get("read_count"),
                    "is_first_read": read_result.get("is_first_read"),
                },
            )

            self.evidence.set_gate(
                "read_recorded",
                has_first_read,
                {"first_read_at": read_result.get("first_read_at")},
            )

            print(f"  ✓ first_read_at={read_result.get('first_read_at')}")
            print(f"  ✓ read_count={read_result.get('read_count')}")

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self.evidence.add_step(
                name="record_read",
                status="failed",
                duration_ms=duration_ms,
                error=str(e),
            )
            self.evidence.set_gate("read_recorded", False, {"error": str(e)})
            print(f"  ✗ Failed: {e}")

    async def _step_verify_view(self):
        """Step 5: Verify view status (DELIVERED=true, READ=true, ACK=null)."""
        import time
        start = time.time()

        print("\nStep 5: Verifying integration view status...")

        try:
            if self.config.mock_provider:
                # Mock: simulate view status
                view_status = {
                    "overall_status": "READ",
                    "notify_status": "DELIVERED",
                    "first_read_at": datetime.utcnow().isoformat() + "Z",
                    "ack_status": None,
                }
            else:
                import httpx
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        f"{self.config.base_url}/api/v1/portal/status",
                        params={
                            "snapshot_id": self.snapshot_id,
                            "driver_id": self.driver_id,
                        },
                        timeout=30,
                    )
                    response.raise_for_status()
                    view_status = response.json()

            duration_ms = int((time.time() - start) * 1000)

            # Check expected state: DELIVERED/READ, has read, no ack
            is_delivered = view_status.get("notify_status") in ("SENT", "DELIVERED")
            is_read = view_status.get("first_read_at") is not None
            ack_is_null = view_status.get("ack_status") is None

            all_correct = is_delivered and is_read and ack_is_null

            self.evidence.add_step(
                name="verify_view",
                status="passed" if all_correct else "failed",
                duration_ms=duration_ms,
                details={
                    "overall_status": view_status.get("overall_status"),
                    "notify_status": view_status.get("notify_status"),
                    "first_read_at": view_status.get("first_read_at"),
                    "ack_status": view_status.get("ack_status"),
                },
            )

            self.evidence.set_gate(
                "view_status_correct",
                all_correct,
                {
                    "delivered": is_delivered,
                    "read": is_read,
                    "ack_null": ack_is_null,
                },
            )

            print(f"  ✓ overall_status={view_status.get('overall_status')}")
            print(f"  ✓ DELIVERED={is_delivered}, READ={is_read}, ACK=null={ack_is_null}")

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self.evidence.add_step(
                name="verify_view",
                status="failed",
                duration_ms=duration_ms,
                error=str(e),
            )
            self.evidence.set_gate("view_status_correct", False, {"error": str(e)})
            print(f"  ✗ Failed: {e}")

    def _print_summary(self):
        """Print test summary."""
        result = self.evidence.evidence["result"]
        gates = self.evidence.evidence["gates"]

        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")

        print("\nGates:")
        for gate_name, gate_result in gates.items():
            if gate_result:
                status = "✓ PASS" if gate_result["passed"] else "✗ FAIL"
            else:
                status = "- SKIP"
            print(f"  {gate_name}: {status}")

        print(f"\nOverall: {result['gates_passed']}/{result['gates_total']} gates passed")
        print(f"Steps: {result['steps_passed']} passed, {result['steps_failed']} failed")

        if result["success"]:
            print("\n✅ E2E TEST PASSED")
        else:
            print("\n❌ E2E TEST FAILED")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    parser = argparse.ArgumentParser(description="Portal-Notify E2E Evidence Test")
    parser.add_argument(
        "--env",
        choices=["local", "staging", "production"],
        default="local",
        help="Environment to test against",
    )
    parser.add_argument(
        "--mock-provider",
        action="store_true",
        help="Use mock provider (no real API calls)",
    )
    args = parser.parse_args()

    config = E2EConfig(env=args.env)
    config.mock_provider = args.mock_provider

    test = PortalNotifyE2ETest(config)
    success = await test.run()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())

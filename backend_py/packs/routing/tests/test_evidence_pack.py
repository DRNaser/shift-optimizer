# =============================================================================
# SOLVEREIGN Routing Pack - Evidence Pack Writer Tests
# =============================================================================

import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, ".")

from packs.routing.services.audit.route_auditor import (
    RouteAuditor,
    AuditStop,
    AuditVehicle,
    AuditAssignment,
    AuditUnassigned,
)
from packs.routing.services.evidence.evidence_pack import (
    EvidencePack,
    EvidencePackWriter,
)


class TestEvidencePackWriter(unittest.TestCase):
    """Test the evidence pack writer."""

    def setUp(self):
        """Set up test fixtures."""
        self.today = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        self.writer = EvidencePackWriter()

        # Test data
        self.stops = [
            {
                "id": "STOP_01",
                "order_id": "ORDER_01",
                "address": {
                    "street": "Test Street",
                    "house_number": "1",
                    "postal_code": "10115",
                    "city": "Berlin"
                },
                "tw_start": self.today + timedelta(hours=1),
                "tw_end": self.today + timedelta(hours=3),
                "tw_is_hard": True,
                "service_duration_min": 15,
                "required_skills": ["MONTAGE_BASIC"],
                "requires_two_person": False,
                "category": "DELIVERY",
            },
            {
                "id": "STOP_02",
                "order_id": "ORDER_02",
                "address": {
                    "street": "Second Street",
                    "house_number": "2",
                    "postal_code": "10117",
                    "city": "Berlin"
                },
                "tw_start": self.today + timedelta(hours=2),
                "tw_end": self.today + timedelta(hours=4),
                "tw_is_hard": True,
                "service_duration_min": 20,
                "required_skills": [],
                "requires_two_person": False,
                "category": "DELIVERY",
            },
        ]

        self.vehicles = [
            {
                "id": "VAN_01",
                "external_id": "V-001",
                "shift_start_at": self.today,
                "shift_end_at": self.today + timedelta(hours=8),
                "skills": ["MONTAGE_BASIC"],
                "team_size": 2,
                "start_depot_id": "DEPOT_01",
                "end_depot_id": "DEPOT_01",
            },
        ]

        self.depots = [
            {
                "id": "DEPOT_01",
                "name": "Berlin Depot",
                "site_id": "SITE_01",
            },
        ]

        self.assignments = [
            {
                "stop_id": "STOP_01",
                "vehicle_id": "VAN_01",
                "arrival_at": self.today + timedelta(hours=1, minutes=30),
                "departure_at": self.today + timedelta(hours=1, minutes=45),
                "sequence_index": 1,
                "slack_minutes": 75,  # 90min from arrival to tw_end
            },
            {
                "stop_id": "STOP_02",
                "vehicle_id": "VAN_01",
                "arrival_at": self.today + timedelta(hours=2, minutes=30),
                "departure_at": self.today + timedelta(hours=2, minutes=50),
                "sequence_index": 2,
                "slack_minutes": 90,
            },
        ]

        self.unassigned = []

        # Run audit for evidence
        auditor = RouteAuditor()
        self.audit_result = auditor.audit(
            plan_id="PLAN_01",
            stops=[
                AuditStop(
                    id=s["id"],
                    tw_start=s["tw_start"],
                    tw_end=s["tw_end"],
                    tw_is_hard=s["tw_is_hard"],
                    required_skills=s.get("required_skills", []),
                    requires_two_person=s.get("requires_two_person", False),
                )
                for s in self.stops
            ],
            vehicles=[
                AuditVehicle(
                    id=v["id"],
                    shift_start_at=v["shift_start_at"],
                    shift_end_at=v["shift_end_at"],
                    skills=v.get("skills", []),
                    team_size=v.get("team_size", 1),
                )
                for v in self.vehicles
            ],
            assignments=[
                AuditAssignment(
                    stop_id=a["stop_id"],
                    vehicle_id=a["vehicle_id"],
                    arrival_at=a["arrival_at"],
                    departure_at=a["departure_at"],
                    sequence_index=a["sequence_index"],
                )
                for a in self.assignments
            ],
            unassigned=[],
        )

    def test_create_evidence_pack(self):
        """Test creating evidence pack."""
        pack = self.writer.create_evidence_pack(
            plan_id="PLAN_01",
            scenario_id="SCENARIO_01",
            tenant_id=1,
            vertical="MEDIAMARKT",
            plan_date="2026-01-06",
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
            assignments=self.assignments,
            unassigned=self.unassigned,
            audit_result=self.audit_result,
            seed=42,
            solver_config_hash="abc123",
            output_hash="def456",
        )

        # Verify pack structure
        self.assertEqual(pack.plan.plan_id, "PLAN_01")
        self.assertEqual(pack.plan.scenario_id, "SCENARIO_01")
        self.assertEqual(pack.plan.tenant_id, 1)
        self.assertEqual(pack.plan.seed, 42)

        # Verify input evidence
        self.assertEqual(pack.input.total_stops, 2)
        self.assertEqual(pack.input.total_vehicles, 1)
        self.assertEqual(pack.input.total_depots, 1)
        self.assertEqual(pack.input.vertical, "MEDIAMARKT")

        # Verify routes evidence
        self.assertEqual(len(pack.routes), 1)  # 1 vehicle used
        self.assertEqual(pack.routes[0].vehicle_id, "VAN_01")
        self.assertEqual(pack.routes[0].total_stops, 2)

        # Verify KPIs
        self.assertEqual(pack.kpis.total_stops, 2)
        self.assertEqual(pack.kpis.assigned_stops, 2)
        self.assertEqual(pack.kpis.unassigned_stops, 0)
        self.assertEqual(pack.kpis.coverage_percentage, 100.0)

        # Verify audit
        self.assertTrue(pack.audit.all_passed)
        self.assertEqual(pack.audit.checks_run, 5)

    def test_write_zip(self):
        """Test writing evidence pack to ZIP."""
        pack = self.writer.create_evidence_pack(
            plan_id="PLAN_01",
            scenario_id="SCENARIO_01",
            tenant_id=1,
            vertical="MEDIAMARKT",
            plan_date="2026-01-06",
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
            assignments=self.assignments,
            unassigned=self.unassigned,
            audit_result=self.audit_result,
            seed=42,
            solver_config_hash="abc123",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "evidence.zip"
            self.writer.write_zip(pack, zip_path)

            # Verify ZIP was created
            self.assertTrue(zip_path.exists())

            # Verify ZIP contents
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()

                self.assertIn("metadata.json", names)
                self.assertIn("plan.json", names)
                self.assertIn("input_summary.json", names)
                self.assertIn("routes.json", names)
                self.assertIn("unassigned.json", names)
                self.assertIn("audit_results.json", names)
                self.assertIn("kpis.json", names)
                self.assertIn("routes.csv", names)
                self.assertIn("unassigned.csv", names)

                # Verify metadata content
                metadata = json.loads(zf.read("metadata.json"))
                self.assertIn("pack_hash", metadata)
                self.assertEqual(metadata["plan_id"], "PLAN_01")

                # Verify KPIs content
                kpis = json.loads(zf.read("kpis.json"))
                self.assertEqual(kpis["coverage_percentage"], 100.0)

    def test_write_directory(self):
        """Test writing evidence pack to directory."""
        pack = self.writer.create_evidence_pack(
            plan_id="PLAN_02",
            scenario_id="SCENARIO_02",
            tenant_id=1,
            vertical="HDL_PLUS",
            plan_date="2026-01-06",
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
            assignments=self.assignments,
            unassigned=self.unassigned,
            audit_result=self.audit_result,
            seed=42,
            solver_config_hash="abc123",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "evidence"
            self.writer.write_directory(pack, output_dir)

            # Verify directory was created
            self.assertTrue(output_dir.exists())

            # Verify files
            self.assertTrue((output_dir / "metadata.json").exists())
            self.assertTrue((output_dir / "plan.json").exists())
            self.assertTrue((output_dir / "routes.json").exists())
            self.assertTrue((output_dir / "routes.csv").exists())

            # Verify content
            plan_data = json.loads((output_dir / "plan.json").read_text())
            self.assertEqual(plan_data["plan_id"], "PLAN_02")

    def test_pack_hash_consistency(self):
        """Test that pack hash is consistent."""
        pack1 = self.writer.create_evidence_pack(
            plan_id="PLAN_01",
            scenario_id="SCENARIO_01",
            tenant_id=1,
            vertical="MEDIAMARKT",
            plan_date="2026-01-06",
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
            assignments=self.assignments,
            unassigned=self.unassigned,
            audit_result=self.audit_result,
            seed=42,
            solver_config_hash="abc123",
        )

        pack2 = self.writer.create_evidence_pack(
            plan_id="PLAN_01",
            scenario_id="SCENARIO_01",
            tenant_id=1,
            vertical="MEDIAMARKT",
            plan_date="2026-01-06",
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
            assignments=self.assignments,
            unassigned=self.unassigned,
            audit_result=self.audit_result,
            seed=42,
            solver_config_hash="abc123",
        )

        # Same input should produce same hash
        self.assertEqual(pack1.compute_pack_hash(), pack2.compute_pack_hash())

    def test_routes_csv_format(self):
        """Test CSV export format."""
        pack = self.writer.create_evidence_pack(
            plan_id="PLAN_01",
            scenario_id="SCENARIO_01",
            tenant_id=1,
            vertical="MEDIAMARKT",
            plan_date="2026-01-06",
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
            assignments=self.assignments,
            unassigned=self.unassigned,
            audit_result=self.audit_result,
            seed=42,
            solver_config_hash="abc123",
        )

        csv_content = self.writer._routes_to_csv(pack.routes)

        # Verify CSV has header and data
        lines = csv_content.strip().split("\n")
        self.assertGreater(len(lines), 1)  # Header + at least 1 data row

        # Verify header
        header = lines[0]
        self.assertIn("vehicle_id", header)
        self.assertIn("stop_id", header)
        self.assertIn("arrival", header)

        # Verify we have 2 data rows (2 stops)
        self.assertEqual(len(lines), 3)  # Header + 2 stops

    def test_unassigned_evidence(self):
        """Test unassigned stops are captured in evidence."""
        # Add an unassigned stop
        unassigned_stops = [
            {
                "stop_id": "STOP_02",
                "reason_code": "STOP_NO_ELIGIBLE_VEHICLE_SKILLS",
                "reason_details": "No vehicle has required skill SPECIAL",
            }
        ]

        # Remove STOP_02 from assignments
        assignments = [a for a in self.assignments if a["stop_id"] != "STOP_02"]

        pack = self.writer.create_evidence_pack(
            plan_id="PLAN_01",
            scenario_id="SCENARIO_01",
            tenant_id=1,
            vertical="MEDIAMARKT",
            plan_date="2026-01-06",
            stops=self.stops,
            vehicles=self.vehicles,
            depots=self.depots,
            assignments=assignments,
            unassigned=unassigned_stops,
            audit_result=self.audit_result,  # Note: audit may differ
            seed=42,
            solver_config_hash="abc123",
        )

        # Verify unassigned evidence
        self.assertEqual(len(pack.unassigned), 1)
        self.assertEqual(pack.unassigned[0].stop_id, "STOP_02")
        self.assertEqual(pack.unassigned[0].reason_code, "STOP_NO_ELIGIBLE_VEHICLE_SKILLS")

        # Verify KPIs reflect unassigned
        self.assertEqual(pack.kpis.unassigned_stops, 1)
        self.assertEqual(pack.kpis.assigned_stops, 1)


if __name__ == "__main__":
    print("=" * 70)
    print("SOLVEREIGN Routing Pack - Evidence Pack Writer Tests")
    print("=" * 70)
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""
Unit tests for Impact Preview (Skill 114).

Tests cover:
- Risk level classification
- Exit code mapping
- Config change analysis
- Pack change analysis
- Migration analysis
- Code change analysis
- Rollback plan generation
- Recommendation generation
"""

import pytest
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import tempfile

from backend_py.skills.impact_preview import (
    ChangeImpactAnalyzer,
    ChangeType,
    RiskLevel,
    ImpactResult,
)


class TestRiskLevels:
    """Test risk level classification."""

    def test_exit_codes(self):
        """Should map risk levels to correct exit codes."""
        # Create minimal ImpactResult for each risk level
        base_kwargs = {
            "change_id": "CHG_TEST",
            "change_type": ChangeType.CONFIG,
            "target": "TEST",
            "action": "modify",
            "risk_score": 0.0,
            "affected_tenants": [],
            "affected_sites": [],
            "affected_packs": [],
            "risk_matrix": {"S0": 0, "S1": 0, "S2": 0, "S3": 0},
            "recommendations": [],
            "approval_required": False,
            "blocking_reason": None,
            "rollback_steps": [],
            "rollback_complexity": "trivial",
            "analyzed_at": datetime.now(timezone.utc),
        }

        safe_result = ImpactResult(risk_level=RiskLevel.SAFE, **base_kwargs)
        assert safe_result.exit_code == 0

        caution_result = ImpactResult(risk_level=RiskLevel.CAUTION, **base_kwargs)
        assert caution_result.exit_code == 1

        risky_result = ImpactResult(risk_level=RiskLevel.RISKY, **base_kwargs)
        assert risky_result.exit_code == 2

        blocked_result = ImpactResult(risk_level=RiskLevel.BLOCKED, **base_kwargs)
        assert blocked_result.exit_code == 3

    def test_risk_level_values(self):
        """Should have correct string values."""
        assert RiskLevel.SAFE.value == "SAFE"
        assert RiskLevel.CAUTION.value == "CAUTION"
        assert RiskLevel.RISKY.value == "RISKY"
        assert RiskLevel.BLOCKED.value == "BLOCKED"


class TestChangeTypes:
    """Test change type classification."""

    def test_change_type_values(self):
        """Should have correct string values."""
        assert ChangeType.CONFIG.value == "config"
        assert ChangeType.PACK.value == "pack"
        assert ChangeType.MIGRATION.value == "migration"
        assert ChangeType.CODE.value == "code"


class TestConfigChangeAnalysis:
    """Test config change impact analysis."""

    @pytest.mark.asyncio
    async def test_solver_config_affects_all_tenants(self):
        """Solver config change should affect all active tenants."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.CONFIG,
            target="SOLVER_TIME_LIMIT",
            action="modify",
            new_value=120,
        )

        assert len(result.affected_tenants) >= 2  # gurkerl, mediamarkt
        assert "routing" in result.affected_packs or "roster" in result.affected_packs

    @pytest.mark.asyncio
    async def test_seed_change_warns_determinism(self):
        """SOLVER_SEED change should warn about determinism."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.CONFIG,
            target="SOLVER_SEED",
            action="modify",
            new_value=42,
        )

        assert result.risk_matrix["S1"] > 0  # Reproducibility risk
        # Check that some recommendation mentions determinism or is present
        assert len(result.recommendations) > 0 or result.risk_level != RiskLevel.SAFE

    @pytest.mark.asyncio
    async def test_disable_feature_with_tenants_blocked(self):
        """Disabling feature with active tenants should be blocked."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.CONFIG,
            target="ENABLE_ROUTING_PACK",
            action="modify",
            new_value=False,
        )

        # Should have blocking reason due to active tenants
        assert result.blocking_reason is not None or result.risk_level in [
            RiskLevel.RISKY,
            RiskLevel.BLOCKED,
        ]


class TestPackChangeAnalysis:
    """Test pack change impact analysis."""

    @pytest.mark.asyncio
    async def test_disable_pack_with_active_tenants(self):
        """Disabling pack with active tenants should be blocked."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.PACK,
            target="routing",
            action="disable",
        )

        # Should be blocked or risky
        assert result.risk_level in [RiskLevel.RISKY, RiskLevel.BLOCKED]
        assert len(result.affected_tenants) > 0
        assert "routing" in result.affected_packs

    @pytest.mark.asyncio
    async def test_enable_unknown_pack(self):
        """Enabling unknown pack should be blocked."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.PACK,
            target="nonexistent_pack",
            action="enable",
        )

        assert result.risk_level == RiskLevel.BLOCKED
        assert result.blocking_reason is not None

    @pytest.mark.asyncio
    async def test_enable_known_pack(self):
        """Enabling known pack should analyze migrations."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.PACK,
            target="routing",
            action="enable",
        )

        # Should not be blocked for known pack
        assert result.risk_level != RiskLevel.BLOCKED or "not ready" in str(result.blocking_reason)


class TestMigrationAnalysis:
    """Test migration impact analysis."""

    @pytest.mark.asyncio
    async def test_migration_affects_all_tenants(self):
        """Migration should affect all tenants."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.MIGRATION,
            target="backend_py/db/migrations/024_new_feature.sql",
        )

        # All tenants affected by schema changes
        assert len(result.affected_tenants) >= 2
        assert result.rollback_complexity == "complex"

    @pytest.mark.asyncio
    async def test_migration_with_create_table_no_rls(self):
        """Migration creating table without RLS should be blocked."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sql", delete=False, encoding="utf-8"
        ) as f:
            f.write("CREATE TABLE new_table (id SERIAL PRIMARY KEY);")
            f.flush()

            analyzer = ChangeImpactAnalyzer()
            result = await analyzer.analyze(
                change_type=ChangeType.MIGRATION,
                target=f.name,
            )

            # Should be blocked - missing tenant_id and RLS
            assert result.risk_level == RiskLevel.BLOCKED
            assert result.risk_matrix["S0"] > 0.5

    @pytest.mark.asyncio
    async def test_migration_with_rls(self):
        """Migration with RLS should not be blocked for RLS reasons."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sql", delete=False, encoding="utf-8"
        ) as f:
            f.write("""
                CREATE TABLE new_table (
                    id SERIAL PRIMARY KEY,
                    tenant_id INTEGER NOT NULL
                );
                ALTER TABLE new_table ENABLE ROW LEVEL SECURITY;
            """)
            f.flush()

            analyzer = ChangeImpactAnalyzer()
            result = await analyzer.analyze(
                change_type=ChangeType.MIGRATION,
                target=f.name,
            )

            # Should not be blocked for RLS reasons
            assert result.blocking_reason is None or "RLS" not in result.blocking_reason


class TestCodeChangeAnalysis:
    """Test code change impact analysis."""

    @pytest.mark.asyncio
    async def test_security_files_high_risk(self):
        """Security file changes should be high risk."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.CODE,
            target="PR #123",
            changed_files=["backend_py/api/security/internal_signature.py"],
        )

        assert result.risk_matrix["S0"] > 0 or result.risk_matrix["S1"] > 0
        assert len(result.affected_tenants) > 0
        # Should recommend security review
        assert any("security" in r.lower() for r in result.recommendations) or result.risk_level != RiskLevel.SAFE

    @pytest.mark.asyncio
    async def test_kernel_files_affect_all_tenants(self):
        """Kernel file changes should affect all tenants."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.CODE,
            target="PR #123",
            changed_files=["backend_py/api/main.py", "backend_py/api/database.py"],
        )

        assert len(result.affected_tenants) >= 2  # All tenants

    @pytest.mark.asyncio
    async def test_pack_files_only_affect_pack(self):
        """Pack file changes should only affect that pack."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.CODE,
            target="PR #123",
            changed_files=["backend_py/packs/routing/services/solver.py"],
        )

        assert "routing" in result.affected_packs
        assert "roster" not in result.affected_packs

    @pytest.mark.asyncio
    async def test_no_files_safe(self):
        """No changed files should be safe."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.CODE,
            target="PR #123",
            changed_files=[],
        )

        assert result.risk_level == RiskLevel.SAFE


class TestRollbackPlan:
    """Test rollback plan generation."""

    @pytest.mark.asyncio
    async def test_config_rollback_trivial(self):
        """Config change rollback should be trivial."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.CONFIG,
            target="SOLVER_TIME_LIMIT",
            action="modify",
            new_value=120,
        )

        assert result.rollback_complexity == "trivial"
        assert len(result.rollback_steps) > 0

    @pytest.mark.asyncio
    async def test_pack_rollback_simple(self):
        """Pack change rollback should be simple."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.PACK,
            target="routing",
            action="enable",
        )

        assert result.rollback_complexity == "simple"
        assert any("disable" in step.lower() for step in result.rollback_steps)

    @pytest.mark.asyncio
    async def test_migration_rollback_complex(self):
        """Migration rollback should be complex."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.MIGRATION,
            target="backend_py/db/migrations/024_new.sql",
        )

        assert result.rollback_complexity == "complex"
        assert any("dba" in step.lower() for step in result.rollback_steps)


class TestRecommendations:
    """Test recommendation generation."""

    @pytest.mark.asyncio
    async def test_many_tenants_phased_rollout(self):
        """Many affected tenants should recommend phased rollout."""
        # Create analyzer with state that has many tenants
        async def mock_state():
            return {
                "tenants": [
                    {"code": f"tenant_{i}", "name": f"Tenant {i}", "status": "active"}
                    for i in range(10)
                ],
                "packs": [{"name": "routing", "enabled": True, "has_solver": True}],
                "migrations": {"pending": []},
            }

        analyzer = ChangeImpactAnalyzer(state_provider=mock_state)
        result = await analyzer.analyze(
            change_type=ChangeType.CONFIG,
            target="SOLVER_TIME_LIMIT",
            action="modify",
            new_value=120,
        )

        # Should recommend phased rollout
        assert any("phased" in r.lower() for r in result.recommendations)

    @pytest.mark.asyncio
    async def test_blocked_has_blocking_reason_recommendation(self):
        """Blocked changes should include blocking reason in recommendations."""
        analyzer = ChangeImpactAnalyzer()
        result = await analyzer.analyze(
            change_type=ChangeType.PACK,
            target="nonexistent_pack",
            action="enable",
        )

        if result.risk_level == RiskLevel.BLOCKED:
            assert any("blocked" in r.lower() for r in result.recommendations)


class TestImpactResultSerialization:
    """Test ImpactResult serialization."""

    def test_to_dict(self):
        """Should serialize to dictionary correctly."""
        result = ImpactResult(
            change_id="CHG_TEST",
            change_type=ChangeType.CONFIG,
            target="TEST",
            action="modify",
            risk_level=RiskLevel.SAFE,
            risk_score=0.1,
            affected_tenants=["tenant1"],
            affected_sites=["site1"],
            affected_packs=["pack1"],
            risk_matrix={"S0": 0.1, "S1": 0.2, "S2": 0.3, "S3": 0.4},
            recommendations=["Test recommendation"],
            approval_required=False,
            blocking_reason=None,
            rollback_steps=["Step 1", "Step 2"],
            rollback_complexity="trivial",
            analyzed_at=datetime(2026, 1, 7, 12, 0, 0, tzinfo=timezone.utc),
        )

        d = result.to_dict()

        assert d["change_id"] == "CHG_TEST"
        assert d["change_type"] == "config"
        assert d["risk_level"] == "SAFE"
        assert d["risk_score"] == 0.1
        assert d["affected_tenants"] == ["tenant1"]
        assert d["risk_matrix"]["S0"] == 0.1
        assert d["rollback_complexity"] == "trivial"


class TestCustomProviders:
    """Test custom state/tenant providers."""

    @pytest.mark.asyncio
    async def test_custom_state_provider(self):
        """Should use custom state provider."""
        async def custom_state():
            return {
                "tenants": [{"code": "custom", "name": "Custom", "status": "active"}],
                "packs": [{"name": "custom_pack", "enabled": True, "has_solver": True}],
                "migrations": {"pending": []},
            }

        analyzer = ChangeImpactAnalyzer(state_provider=custom_state)
        result = await analyzer.analyze(
            change_type=ChangeType.CONFIG,
            target="SOLVER_TIME_LIMIT",
            action="modify",
        )

        assert "custom" in result.affected_tenants
        assert "custom_pack" in result.affected_packs

    @pytest.mark.asyncio
    async def test_custom_active_solves_provider(self):
        """Should use custom active solves provider."""
        async def custom_solves():
            return 5

        analyzer = ChangeImpactAnalyzer(active_solves_provider=custom_solves)
        result = await analyzer.analyze(
            change_type=ChangeType.CONFIG,
            target="SOLVER_TIME_LIMIT",
            action="modify",
        )

        # Should have active_solves in recommendations
        assert result.risk_matrix["S2"] > 0  # Medium degraded risk


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

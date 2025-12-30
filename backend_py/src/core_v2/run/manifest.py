"""
Core v2 - Run Manifest & Context

State management for deterministic execution.
Single source of truth for all run parameters and state.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import hashlib
import json
import logging

from ..model.weektype import WeekCategory, classify_week


@dataclass(frozen=True)
class RunManifest:
    """
    Immutable manifest defining exactly what this run is.
    Serialized to artifacts/run_manifest.json.
    """
    run_id: str
    timestamp: str
    
    # Inputs
    dataset_hash: str     # SHA of input tours
    config_hash: str      # SHA of config dict
    
    # Week Profile
    active_days_count: int
    week_category: WeekCategory
    
    # Environment
    git_sha: str          # Version traceability
    num_workers: int = 1  # Always 1 for determinism
    
    # Solver Config
    backend: str = "highspy"
    use_duals: bool = True
    
    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "dataset_hash": self.dataset_hash,
            "config_hash": self.config_hash,
            "git_sha": self.git_sha,
            "num_workers": self.num_workers,
            "active_days_count": self.active_days_count,
            "week_category": self.week_category.value,
            "backend": self.backend,
            "use_duals": self.use_duals,
        }


class RunContext:
    """
    Mutable runtime context (logging, artifacts, snapshots).
    Passed through pipeline stages.
    """
    
    def __init__(self, manifest: RunManifest, artifact_dir: str):
        self.manifest = manifest
        self.artifact_dir = artifact_dir
        self.logger = logging.getLogger(f"CoreV2.{manifest.run_id}")
        self.snapshots: list[dict] = []
        
        # Runtime stats
        self.start_time = datetime.now()
        self.timings = {}
        
    def log(self, msg: str, level: int = logging.INFO):
        self.logger.log(level, msg)
        
    def add_timing(self, phase: str, duration_sec: float):
        self.timings[phase] = duration_sec
        self.log(f"Phase '{phase}' completed in {duration_sec:.2f}s")

    def save_snapshot(self, step: str, data: dict):
        """Save a debug snapshot (e.g., after CG iteration)."""
        snapshot_file = f"{self.artifact_dir}/snapshot_{step}.json"
        
        # Minimal metadata for index
        self.snapshots.append({
            "step": step,
            "file": snapshot_file,
            "timestamp": datetime.now().isoformat()
        })
        
        # Write actual data
        # Note: In real implementation, handle IO errors and maybe zip large files
        try:
            with open(snapshot_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Failed to save snapshot {step}: {e}")

    @staticmethod
    def create(run_id: str, tours: list[Any], config: dict, artifact_dir: str = ".") -> "RunContext":
        """Factory to create context from inputs."""
        # 1. Compute hashes
        # Simple string dump hash for now
        tours_str = json.dumps([t.to_dict() for t in tours], sort_keys=True)
        ds_hash = hashlib.sha256(tours_str.encode()).hexdigest()[:16]
        
        cfg_str = json.dumps(config, sort_keys=True)
        cfg_hash = hashlib.sha256(cfg_str.encode()).hexdigest()[:16]
        
        # 2. Week profiling
        days = {t.day for t in tours}
        active_count = len(days)
        category = classify_week(active_count)
        
        # 3. Build manifest
        manifest = RunManifest(
            run_id=run_id,
            timestamp=datetime.now().isoformat(),
            dataset_hash=ds_hash,
            config_hash=cfg_hash,
            git_sha="unknown",  # TODO: inject via build env
            active_days_count=active_count,
            week_category=category,
            backend=config.get("backend", "highspy"),
        )
        
        return RunContext(manifest, artifact_dir)

#!/usr/bin/env python3
"""
SOLVEREIGN V4.3 - Evidence Artifact Storage
============================================

Versioned storage for evidence artifacts from:
- E2E tests (e2e_portal_notify_evidence.py)
- Migration gates (prod_migration_gate.py)
- Smoke tests (smoke_test_saas.py)

Storage structure:
    evidence/
    ├── YYYY-MM-DD/
    │   ├── e2e_portal_notify_<timestamp>.json
    │   ├── migration_gate_pre_<timestamp>.json
    │   ├── migration_gate_post_<timestamp>.json
    │   └── smoke_test_<timestamp>.json
    └── latest/
        ├── e2e_portal_notify.json -> ../YYYY-MM-DD/...
        └── migration_gate.json -> ../YYYY-MM-DD/...

Usage:
    from evidence_store import EvidenceStore

    store = EvidenceStore()
    path = store.save(
        category="e2e_portal_notify",
        data={"checks": [...], "all_pass": True},
        env="staging",
    )
    print(f"Saved to: {path}")

Environment Variables:
    EVIDENCE_BASE_PATH: Base path for evidence storage (default: ./evidence)
    EVIDENCE_RETENTION_DAYS: Days to keep evidence (default: 90)
"""

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


class EvidenceStore:
    """
    Versioned evidence artifact storage.

    Features:
    - Date-partitioned storage
    - Latest symlinks for easy access
    - Automatic retention cleanup
    - JSON and text file support
    """

    def __init__(
        self,
        base_path: Optional[str] = None,
        retention_days: int = 90,
    ):
        """
        Initialize evidence store.

        Args:
            base_path: Base directory for evidence storage
            retention_days: Days to keep evidence before cleanup
        """
        self.base_path = Path(
            base_path or os.environ.get("EVIDENCE_BASE_PATH", "./evidence")
        )
        self.retention_days = int(
            os.environ.get("EVIDENCE_RETENTION_DAYS", str(retention_days))
        )

        # Ensure base directories exist
        self.base_path.mkdir(parents=True, exist_ok=True)
        (self.base_path / "latest").mkdir(exist_ok=True)

    def save(
        self,
        category: str,
        data: Dict[str, Any],
        env: str = "unknown",
        suffix: Optional[str] = None,
        update_latest: bool = True,
    ) -> Path:
        """
        Save evidence data to storage.

        Args:
            category: Evidence category (e.g., "e2e_portal_notify", "migration_gate")
            data: Evidence data to store
            env: Environment name (staging, prod)
            suffix: Optional suffix for filename
            update_latest: Whether to update latest symlink

        Returns:
            Path to saved evidence file
        """
        now = datetime.utcnow()
        date_str = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        # Create date directory
        date_dir = self.base_path / date_str
        date_dir.mkdir(exist_ok=True)

        # Build filename
        filename_parts = [category]
        if env != "unknown":
            filename_parts.append(env)
        if suffix:
            filename_parts.append(suffix)
        filename_parts.append(timestamp)
        filename = "_".join(filename_parts) + ".json"

        filepath = date_dir / filename

        # Add metadata to data
        evidence = {
            "metadata": {
                "category": category,
                "environment": env,
                "timestamp": now.isoformat() + "Z",
                "version": "v4.3",
            },
            **data,
        }

        # Write JSON
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2, ensure_ascii=False, default=str)

        # Update latest symlink
        if update_latest:
            self._update_latest(category, env, filepath)

        return filepath

    def save_text(
        self,
        category: str,
        content: str,
        env: str = "unknown",
        suffix: Optional[str] = None,
        extension: str = "txt",
    ) -> Path:
        """
        Save text evidence to storage.

        Args:
            category: Evidence category
            content: Text content to store
            env: Environment name
            suffix: Optional suffix for filename
            extension: File extension (default: txt)

        Returns:
            Path to saved evidence file
        """
        now = datetime.utcnow()
        date_str = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        # Create date directory
        date_dir = self.base_path / date_str
        date_dir.mkdir(exist_ok=True)

        # Build filename
        filename_parts = [category]
        if env != "unknown":
            filename_parts.append(env)
        if suffix:
            filename_parts.append(suffix)
        filename_parts.append(timestamp)
        filename = "_".join(filename_parts) + f".{extension}"

        filepath = date_dir / filename

        # Write content
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return filepath

    def _update_latest(self, category: str, env: str, filepath: Path) -> None:
        """Update latest symlink for category."""
        latest_dir = self.base_path / "latest"
        latest_name = f"{category}_{env}.json" if env != "unknown" else f"{category}.json"
        latest_path = latest_dir / latest_name

        # Remove existing symlink/file
        if latest_path.exists() or latest_path.is_symlink():
            latest_path.unlink()

        # On Windows, copy instead of symlink (symlinks require admin)
        if os.name == "nt":
            shutil.copy2(filepath, latest_path)
        else:
            # Create relative symlink
            relative = os.path.relpath(filepath, latest_dir)
            latest_path.symlink_to(relative)

    def get_latest(self, category: str, env: str = "unknown") -> Optional[Path]:
        """
        Get path to latest evidence for category.

        Args:
            category: Evidence category
            env: Environment name

        Returns:
            Path to latest evidence file, or None if not found
        """
        latest_name = f"{category}_{env}.json" if env != "unknown" else f"{category}.json"
        latest_path = self.base_path / "latest" / latest_name

        if latest_path.exists():
            return latest_path
        return None

    def load_latest(self, category: str, env: str = "unknown") -> Optional[Dict[str, Any]]:
        """
        Load latest evidence data for category.

        Args:
            category: Evidence category
            env: Environment name

        Returns:
            Evidence data dict, or None if not found
        """
        path = self.get_latest(category, env)
        if path and path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def cleanup_old(self) -> int:
        """
        Remove evidence older than retention_days.

        Returns:
            Number of directories removed
        """
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        removed = 0

        for item in self.base_path.iterdir():
            if item.is_dir() and item.name != "latest":
                try:
                    dir_date = datetime.strptime(item.name, "%Y-%m-%d")
                    if dir_date < cutoff:
                        shutil.rmtree(item)
                        removed += 1
                except ValueError:
                    # Not a date directory, skip
                    pass

        return removed

    def list_evidence(
        self,
        category: Optional[str] = None,
        env: Optional[str] = None,
        days: int = 7,
    ) -> list:
        """
        List recent evidence files.

        Args:
            category: Filter by category
            env: Filter by environment
            days: Number of days to look back

        Returns:
            List of evidence file paths
        """
        cutoff = datetime.utcnow() - timedelta(days=days)
        results = []

        for item in self.base_path.iterdir():
            if item.is_dir() and item.name != "latest":
                try:
                    dir_date = datetime.strptime(item.name, "%Y-%m-%d")
                    if dir_date >= cutoff:
                        for file in item.glob("*.json"):
                            # Apply filters
                            if category and category not in file.stem:
                                continue
                            if env and env not in file.stem:
                                continue
                            results.append(file)
                except ValueError:
                    pass

        return sorted(results, reverse=True)


def main():
    """CLI for evidence store operations."""
    import argparse

    parser = argparse.ArgumentParser(description="Evidence Artifact Storage")
    parser.add_argument("command", choices=["list", "cleanup", "latest"])
    parser.add_argument("--category", help="Filter by category")
    parser.add_argument("--env", help="Filter by environment")
    parser.add_argument("--days", type=int, default=7, help="Days to look back")
    parser.add_argument("--base-path", help="Base path for evidence storage")
    args = parser.parse_args()

    store = EvidenceStore(base_path=args.base_path)

    if args.command == "list":
        files = store.list_evidence(
            category=args.category,
            env=args.env,
            days=args.days,
        )
        print(f"Found {len(files)} evidence files:")
        for f in files:
            print(f"  {f}")

    elif args.command == "cleanup":
        removed = store.cleanup_old()
        print(f"Removed {removed} old evidence directories")

    elif args.command == "latest":
        if not args.category:
            print("ERROR: --category required for latest command")
            return 1

        path = store.get_latest(args.category, args.env or "unknown")
        if path:
            print(f"Latest: {path}")
            with open(path, "r") as f:
                data = json.load(f)
            print(json.dumps(data, indent=2))
        else:
            print(f"No evidence found for category={args.category}")
            return 1

    return 0


if __name__ == "__main__":
    exit(main())

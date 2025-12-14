"""
SHIFT OPTIMIZER - Snapshot Manager
===================================
Versioning, hashing, and rollback system.

Snapshots are ARTIFACTS, not logs.
They enable reproducibility and rollback.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any
import zstandard as zstd

try:
    import blake3
    BLAKE3_AVAILABLE = True
except ImportError:
    BLAKE3_AVAILABLE = False


# =============================================================================
# SNAPSHOT CONFIGURATION
# =============================================================================

SNAPSHOT_DIR = Path("snapshots")
COMPRESSION_LEVEL = 3  # zstd compression level (1-22)


# =============================================================================
# SERIALIZATION
# =============================================================================

def to_canonical_json(data: Any) -> str:
    """
    Convert data to canonical JSON format.
    
    - Sorted keys
    - No extra whitespace
    - UTF-8 encoding
    - Consistent formatting
    """
    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str  # Handle non-serializable types
    )


def from_json(json_str: str) -> Any:
    """Parse JSON string."""
    return json.loads(json_str)


# =============================================================================
# HASHING
# =============================================================================

def compute_hash(data: bytes) -> str:
    """
    Compute hash of data.
    
    Uses BLAKE3 if available (faster, more secure),
    falls back to SHA-256.
    """
    if BLAKE3_AVAILABLE:
        return blake3.blake3(data).hexdigest()[:16]
    else:
        return hashlib.sha256(data).hexdigest()[:16]


# =============================================================================
# COMPRESSION
# =============================================================================

def compress(data: bytes) -> bytes:
    """Compress data using zstd."""
    compressor = zstd.ZstdCompressor(level=COMPRESSION_LEVEL)
    return compressor.compress(data)


def decompress(data: bytes) -> bytes:
    """Decompress zstd-compressed data."""
    decompressor = zstd.ZstdDecompressor()
    return decompressor.decompress(data)


# =============================================================================
# SNAPSHOT OPERATIONS
# =============================================================================

class Snapshot:
    """Represents a single snapshot."""
    
    def __init__(
        self,
        stage: str,
        module: str,
        version: tuple[int, int, int],
        data: dict[str, Any],
        timestamp: datetime | None = None
    ):
        self.stage = stage
        self.module = module
        self.version = version
        self.data = data
        self.timestamp = timestamp or datetime.utcnow()
        
        # Compute hash
        canonical = to_canonical_json(data)
        self.hash = compute_hash(canonical.encode("utf-8"))
    
    @property
    def version_string(self) -> str:
        """Get version as string."""
        return f"v{self.version[0]}.{self.version[1]}.{self.version[2]}"
    
    @property
    def filename(self) -> str:
        """
        Generate snapshot filename.
        
        Format: <stage>-<module>-v<major>.<minor>.<patch>-<timestamp>-<hash>.snap
        """
        ts = self.timestamp.strftime("%Y%m%d%H%M%S")
        return f"{self.stage}-{self.module}-{self.version_string}-{ts}-{self.hash}.snap"
    
    def to_bytes(self) -> bytes:
        """Serialize and compress snapshot."""
        envelope = {
            "stage": self.stage,
            "module": self.module,
            "version": list(self.version),
            "timestamp": self.timestamp.isoformat(),
            "hash": self.hash,
            "data": self.data
        }
        canonical = to_canonical_json(envelope)
        return compress(canonical.encode("utf-8"))
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "Snapshot":
        """Deserialize snapshot from compressed bytes."""
        decompressed = decompress(data)
        envelope = from_json(decompressed.decode("utf-8"))
        
        snapshot = cls(
            stage=envelope["stage"],
            module=envelope["module"],
            version=tuple(envelope["version"]),
            data=envelope["data"],
            timestamp=datetime.fromisoformat(envelope["timestamp"])
        )
        
        # Verify hash
        if snapshot.hash != envelope["hash"]:
            raise ValueError(
                f"Hash mismatch: computed {snapshot.hash}, stored {envelope['hash']}. "
                "CRITICAL DRIFT DETECTED."
            )
        
        return snapshot


class SnapshotManager:
    """
    Manages snapshots for versioning and rollback.
    
    Supports:
    - Creating snapshots
    - Loading snapshots
    - Listing versions
    - Rollback to previous versions
    """
    
    def __init__(self, snapshot_dir: Path | None = None):
        self.snapshot_dir = snapshot_dir or SNAPSHOT_DIR
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    def save(self, snapshot: Snapshot) -> Path:
        """Save snapshot to disk."""
        path = self.snapshot_dir / snapshot.filename
        path.write_bytes(snapshot.to_bytes())
        return path
    
    def load(self, filename: str) -> Snapshot:
        """Load snapshot from disk."""
        path = self.snapshot_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Snapshot not found: {filename}")
        return Snapshot.from_bytes(path.read_bytes())
    
    def list_snapshots(
        self,
        stage: str | None = None,
        module: str | None = None
    ) -> list[str]:
        """List available snapshots, optionally filtered."""
        snapshots = []
        for path in self.snapshot_dir.glob("*.snap"):
            name = path.name
            if stage and not name.startswith(f"{stage}-"):
                continue
            if module:
                parts = name.split("-")
                if len(parts) >= 2 and parts[1] != module:
                    continue
            snapshots.append(name)
        return sorted(snapshots)
    
    def get_latest(
        self,
        stage: str,
        module: str
    ) -> Snapshot | None:
        """Get the latest snapshot for a stage/module."""
        snapshots = self.list_snapshots(stage=stage, module=module)
        if not snapshots:
            return None
        return self.load(snapshots[-1])
    
    def create_snapshot(
        self,
        stage: str,
        module: str,
        version: tuple[int, int, int],
        data: dict[str, Any]
    ) -> Snapshot:
        """Create and save a new snapshot."""
        snapshot = Snapshot(
            stage=stage,
            module=module,
            version=version,
            data=data
        )
        self.save(snapshot)
        return snapshot


# =============================================================================
# GLOBAL SNAPSHOT MANAGER
# =============================================================================

_manager: SnapshotManager | None = None


def get_snapshot_manager() -> SnapshotManager:
    """Get global snapshot manager instance."""
    global _manager
    if _manager is None:
        _manager = SnapshotManager()
    return _manager

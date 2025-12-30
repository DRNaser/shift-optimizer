"""
Core v2 - Column Pool Store

Manages the pool of generated columns.
Handles deduplication via canonical signatures.
"""

from ..model.column import ColumnV2


class ColumnPoolStore:
    """
    Storage for RosterColumns.
    Enforces uniqueness by signature.
    """
    
    def __init__(self):
        self._columns_by_sig: dict[str, ColumnV2] = {}
        self._stats_history: list[dict] = []
        
    def add(self, column: ColumnV2) -> bool:
        """
        Add a column to the pool.
        Returns True if new, False if duplicate.
        """
        sig = column.signature
        if sig in self._columns_by_sig:
            return False
            
        self._columns_by_sig[sig] = column
        return True
        
    def add_all(self, columns: list[ColumnV2]) -> int:
        """
        Add multiple columns.
        Returns count of NEW columns added.
        """
        count = 0
        for col in columns:
            if self.add(col):
                count += 1
        return count
        
    @property
    def columns(self) -> list[ColumnV2]:
        """Return all unique columns in the pool."""
        return list(self._columns_by_sig.values())
        
    @property
    def size(self) -> int:
        return len(self._columns_by_sig)
        
    def snapshot_stats(self, iteration: int):
        """Record pool statistics for this iteration."""
        # Simple breakdown
        by_type = {"singleton": 0, "under30": 0, "fte": 0}
        for c in self._columns_by_sig.values():
            if c.is_singleton: by_type["singleton"] += 1
            elif c.is_under_30h: by_type["under30"] += 1
            else: by_type["fte"] += 1
            
        self._stats_history.append({
            "iteration": iteration,
            "total_size": self.size,
            "breakdown": by_type
        })

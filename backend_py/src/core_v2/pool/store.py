"""
Core v2 - Column Pool Store

Manages the pool of generated columns.
Handles deduplication via canonical signatures.
Maintains tour->column adjacency for sparse LP builds.
"""

from ..model.column import ColumnV2


class ColumnPoolStore:
    """
    Storage for RosterColumns.
    Enforces uniqueness by signature.
    Maintains tour->column adjacency for O(1) lookups.
    """
    
    def __init__(self):
        self._columns_by_sig: dict[str, ColumnV2] = {}
        self._col_index: list[ColumnV2] = []           # Index -> Column
        self._tour_to_cols: dict[str, list[int]] = {}  # tour_id -> [col_indices]
        self._stats_history: list[dict] = []
        
    def add(self, column: ColumnV2) -> bool:
        """
        Add a column to the pool.
        Returns True if new, False if duplicate.
        Maintains tour->column adjacency.
        """
        sig = column.signature
        if sig in self._columns_by_sig:
            return False
            
        self._columns_by_sig[sig] = column
        
        # Add to index
        col_idx = len(self._col_index)
        self._col_index.append(column)
        
        # Update adjacency
        for tour_id in column.covered_tour_ids:
            if tour_id not in self._tour_to_cols:
                self._tour_to_cols[tour_id] = []
            self._tour_to_cols[tour_id].append(col_idx)
        
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
    
    def get_cols_for_tour(self, tour_id: str) -> list[ColumnV2]:
        """Get all columns covering a specific tour. O(k) where k = result size."""
        indices = self._tour_to_cols.get(tour_id, [])
        return [self._col_index[i] for i in indices]
    
    def get_col_indices_for_tour(self, tour_id: str) -> list[int]:
        """Get column indices for a tour. O(1)."""
        return self._tour_to_cols.get(tour_id, [])
    
    def get_column_by_index(self, idx: int) -> ColumnV2:
        """Get column by its pool index."""
        return self._col_index[idx]
        
    @property
    def columns(self) -> list[ColumnV2]:
        """Return all unique columns in the pool (by insertion order)."""
        return list(self._col_index)
        
    @property
    def size(self) -> int:
        return len(self._columns_by_sig)
    
    @property
    def all_covered_tours(self) -> set[str]:
        """Return set of all tour_ids covered by at least one column."""
        return set(self._tour_to_cols.keys())
        
    def snapshot_stats(self, iteration: int):
        """Record pool statistics for this iteration."""
        by_type = {"singleton": 0, "under30": 0, "fte": 0}
        for c in self._col_index:
            if c.is_singleton: by_type["singleton"] += 1
            elif c.is_under_30h: by_type["under30"] += 1
            else: by_type["fte"] += 1
            
        self._stats_history.append({
            "iteration": iteration,
            "total_size": self.size,
            "covered_tours": len(self._tour_to_cols),
            "breakdown": by_type
        })
    
    def get_adjacency_stats(self) -> dict:
        """Get statistics about adjacency coverage."""
        if not self._tour_to_cols:
            return {"covered_tours": 0, "avg_cols_per_tour": 0}
        
        counts = [len(v) for v in self._tour_to_cols.values()]
        return {
            "covered_tours": len(self._tour_to_cols),
            "avg_cols_per_tour": sum(counts) / len(counts) if counts else 0,
            "max_cols_per_tour": max(counts) if counts else 0,
            "min_cols_per_tour": min(counts) if counts else 0,
        }


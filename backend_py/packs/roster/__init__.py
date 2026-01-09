"""
SOLVEREIGN Roster Pack

Weekly shift/roster scheduling for logistics drivers with German labor law compliance.

Domain Concepts:
- Tour: Single work shift (e.g., Mo 08:00-16:00)
- Block: Group of tours for one driver-day (1er, 2er, 3er)
- FTE: Full-time equivalent (>=40h/week)
- PT: Part-time (<40h/week)

Tech Stack:
- Solver: Block Heuristic + Column Generation
- LP: HiGHS (via highspy)
- Refinement: Large Neighborhood Search

Key Constraints (German Labor Law):
- Weekly Hours: <=55h (hard cap)
- Daily Rest: >=11h between blocks
- Span Regular: <=14h for 1er/2er-reg
- Span Split: <=16h for 3er/split
- Split Break: 4-6h (240-360min)
- Fatigue: No 3er->3er consecutive days

See ADR-001 for pack boundary rules.
See ADR-002 for policy profile configuration.
"""

__version__ = "1.0.0"
__pack_id__ = "roster"

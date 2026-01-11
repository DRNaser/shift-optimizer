#!/usr/bin/env python3
"""
Pack Boundary Linter - Enforces import isolation between kernel and domain packs.

Architecture:
- KERNEL: backend_py/api/ (shared platform governance)
- ROUTING PACK: backend_py/packs/routing/ (VRPTW solver)
- ROSTER PACK: backend_py/v3/, backend_py/src/ (shift scheduling)

Rules:
1. Kernel MUST NOT import from packs (routing, roster)
2. Packs MAY import from kernel (api.database, api.exceptions, etc.)
3. Packs MUST NOT import from each other (routing <-> roster)
4. Tools are exempt (they orchestrate across boundaries)

Exit Codes:
- 0: All boundaries respected
- 1: Boundary violations found

Usage:
    python -m backend_py.tools.pack_boundary_linter [--strict] [--verbose]
"""

import argparse
import ast
import sys
from pathlib import Path
from typing import NamedTuple


class Violation(NamedTuple):
    """Import boundary violation."""
    file: Path
    line: int
    importer_pack: str
    imported_pack: str
    import_statement: str


# Pack definitions
PACK_PATHS = {
    "kernel": ["backend_py/api"],
    "routing": ["backend_py/packs/routing"],
    "roster": ["backend_py/v3", "backend_py/src"],
    "tools": ["backend_py/tools"],  # Exempt from rules
}

# Module prefixes for import checking
PACK_MODULES = {
    "kernel": ["api.", "backend_py.api"],
    "routing": ["packs.routing", "backend_py.packs.routing"],
    "roster": ["v3.", "src.", "backend_py.v3", "backend_py.src"],
}

# Forbidden import patterns: (source_pack, forbidden_target_pack)
FORBIDDEN_IMPORTS = [
    ("kernel", "routing"),   # Kernel must not import from routing
    ("kernel", "roster"),    # Kernel must not import from roster
    ("routing", "roster"),   # Routing must not import from roster
    ("roster", "routing"),   # Roster must not import from routing
]

# Allowed exceptions: (file_path_pattern, import_module_pattern)
# These are intentional API wiring points where kernel orchestrates packs
ALLOWED_IMPORTS = [
    # main.py wires routing pack routes
    ("api/main.py", "packs.routing"),
    # Routers call domain solvers - these are intentional API integrations
    ("api/routers/forecasts.py", "v3."),
    ("api/routers/plans.py", "v3."),
    ("api/routers/repair.py", "v3."),
    ("api/routers/runs.py", "v3."),
    ("api/routers/simulations.py", "v3."),
    # Async solver wrapper
    ("api/solver_async.py", "v3."),
    # Policy service uses routing config schema
    ("api/services/policy_service.py", "packs.routing"),
]


def is_allowed_import(file_path: Path, import_name: str) -> bool:
    """Check if an import is in the allowlist."""
    path_str = str(file_path).replace("\\", "/")
    for file_pattern, import_pattern in ALLOWED_IMPORTS:
        if file_pattern in path_str and import_name.startswith(import_pattern):
            return True
    return False


def get_pack_for_path(file_path: Path) -> str | None:
    """Determine which pack a file belongs to."""
    path_str = str(file_path).replace("\\", "/")

    for pack_name, paths in PACK_PATHS.items():
        for pack_path in paths:
            if pack_path in path_str:
                return pack_name

    return None


def get_pack_for_import(import_name: str) -> str | None:
    """Determine which pack an import belongs to."""
    for pack_name, prefixes in PACK_MODULES.items():
        for prefix in prefixes:
            if import_name.startswith(prefix):
                return pack_name

    return None


def extract_imports(file_path: Path) -> list[tuple[int, str]]:
    """Extract all import statements from a Python file."""
    imports = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.lineno, node.module))

    return imports


def check_file(file_path: Path, verbose: bool = False) -> list[Violation]:
    """Check a single file for boundary violations."""
    violations = []

    source_pack = get_pack_for_path(file_path)
    if source_pack is None or source_pack == "tools":
        # Unknown pack or tools (exempt)
        return violations

    imports = extract_imports(file_path)

    for line_no, import_name in imports:
        target_pack = get_pack_for_import(import_name)

        if target_pack is None:
            continue  # External or standard library import

        # Check if this import is forbidden (unless explicitly allowed)
        if (source_pack, target_pack) in FORBIDDEN_IMPORTS and not is_allowed_import(file_path, import_name):
            violations.append(Violation(
                file=file_path,
                line=line_no,
                importer_pack=source_pack,
                imported_pack=target_pack,
                import_statement=import_name,
            ))
            if verbose:
                print(f"  VIOLATION: {file_path}:{line_no} ({source_pack} -> {target_pack})")

    return violations


def check_all_files(root_dir: Path, verbose: bool = False) -> list[Violation]:
    """Check all Python files in the backend."""
    all_violations = []

    backend_dir = root_dir / "backend_py"
    if not backend_dir.exists():
        print(f"ERROR: {backend_dir} not found")
        return all_violations

    # Collect all Python files
    python_files = list(backend_dir.rglob("*.py"))

    # Filter out test files and __pycache__
    python_files = [
        f for f in python_files
        if "__pycache__" not in str(f)
        and not f.name.startswith("test_")
        and "tests" not in f.parts
    ]

    if verbose:
        print(f"Checking {len(python_files)} Python files...")

    for file_path in sorted(python_files):
        violations = check_file(file_path, verbose)
        all_violations.extend(violations)

    return all_violations


def main():
    parser = argparse.ArgumentParser(
        description="Pack Boundary Linter - Enforces import isolation"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 on any violation (default for CI)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print verbose output"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).parent.parent.parent,
        help="Root directory of the repository"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("PACK BOUNDARY LINTER")
    print("=" * 60)
    print()
    print("Rules:")
    print("  - Kernel MUST NOT import from packs (routing, roster)")
    print("  - Packs MUST NOT import from each other")
    print("  - Tools are exempt (orchestration layer)")
    print()

    violations = check_all_files(args.root, args.verbose)

    if violations:
        print()
        print("=" * 60)
        print(f"VIOLATIONS FOUND: {len(violations)}")
        print("=" * 60)
        print()

        # Group by file
        by_file: dict[Path, list[Violation]] = {}
        for v in violations:
            if v.file not in by_file:
                by_file[v.file] = []
            by_file[v.file].append(v)

        for file_path, file_violations in sorted(by_file.items()):
            print(f"{file_path}:")
            for v in file_violations:
                print(f"  Line {v.line}: {v.importer_pack} -> {v.imported_pack}")
                print(f"    import: {v.import_statement}")
            print()

        print("=" * 60)
        print("FIX: Move shared code to kernel or create explicit contracts")
        print("=" * 60)

        if args.strict:
            sys.exit(1)
    else:
        print("=" * 60)
        print("PASS: All pack boundaries respected")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    main()

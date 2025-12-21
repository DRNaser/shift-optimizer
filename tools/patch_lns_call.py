# tools/patch_lns_call.py
from pathlib import Path

# Ensure we have the tools directory
Path("tools").mkdir(exist_ok=True)

FILE = Path("backend_py/src/services/forecast_solver_v4.py")
MARKER = "    # ==== POST-COMPRESSION"
INSERT = """\
    # === PHASE 1B: LNS REOPTIMIZATION (Friday) ===
    try:
        fri_lb = day_min_results.get("Fri")
        lb_peak = max(day_min_results.values()) if day_min_results else 0
        fri_cur = sum(1 for b in best_solution if b.day.value == "Fri")
        if fri_lb and fri_cur > fri_lb + 5:
            print(f"\\n--- LNS Friday Reopt: {fri_cur} -> target~{fri_lb} ---", flush=True)
            improved = _lns_reopt_friday(
                current_solution=best_solution,
                all_blocks=blocks,
                tours=tours,
                block_index=block_index,
                config=config,
                block_scores=block_scores,
                block_props=block_props,
                fri_lb=fri_lb,
                lb_peak=lb_peak,
            )
            if improved:
                print(f"  LNS improved blocks: {len(best_solution)} -> {len(improved)}", flush=True)
                best_solution = improved
            else:
                print("  LNS: no improvement", flush=True)
    except Exception as e:
        print(f"[LNS] skipped due to error: {e}", flush=True)

"""

txt = FILE.read_text(encoding="utf-8")
if "LNS Friday Reopt" in txt:
    print("LNS call already patched.")
    raise SystemExit(0)

i = txt.find(MARKER)
if i == -1:
    raise SystemExit(f"Marker not found: {MARKER}")

txt2 = txt[:i] + INSERT + txt[i:]
FILE.write_text(txt2, encoding="utf-8")
print("Patched LNS call successfully.")

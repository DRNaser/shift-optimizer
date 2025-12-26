import json
import sys

def load_stats(path):
    with open(path, 'r', encoding='utf-8') as f:
        d = json.load(f)
    return d.get('stats', {})

if len(sys.argv) < 3:
    print("Usage: python compare_rc0_rc1.py <rc0.json> <rc1.json>")
    sys.exit(1)

rc0 = load_stats(sys.argv[1])
rc1 = load_stats(sys.argv[2])

# Build comparison table
metrics = [
    ('drivers_total', 'total_drivers', 'Drivers'),
    ('tours_assigned', 'total_tours_assigned', 'Tours Assigned'),
    ('coverage', 'assignment_rate', 'Coverage'),
    ('utilization', 'average_driver_utilization', 'Utilization'),
    ('avg_work_hours', 'average_work_hours', 'Avg Work Hours'),
    ('blocks_1er', lambda s: s.get('block_counts', {}).get('1er', 0), '1er Blocks'),
    ('blocks_2er', lambda s: s.get('block_counts', {}).get('2er', 0), '2er Blocks'),
    ('blocks_3er', lambda s: s.get('block_counts', {}).get('3er', 0), '3er Blocks'),
    ('1er_share_%', 'tour_share_1er', '1er Share %'),
    ('2er_share_%', 'tour_share_2er', '2er Share %'),
    ('3er_share_%', 'tour_share_3er', '3er Share %'),
    ('missed_multi_opps', 'missed_multi_opps_count', 'Missed Multi Opps'),
    ('forced_1er_count', 'forced_1er_count', 'Forced 1er Count'),
]

print("=" * 70)
print("RC0 vs RC1 KPI COMPARISON")
print("=" * 70)
print(f"{'Metric':<25} {'RC0':>15} {'RC1':>15} {'Delta':>12}")
print("-" * 70)

for _, key_or_fn, label in metrics:
    if callable(key_or_fn):
        v0 = key_or_fn(rc0)
        v1 = key_or_fn(rc1)
    else:
        v0 = rc0.get(key_or_fn, 'N/A')
        v1 = rc1.get(key_or_fn, 'N/A')
    
    # Format values
    if isinstance(v0, float):
        if 'share' in label.lower() or 'coverage' in label.lower() or 'utilization' in label.lower():
            v0_str = f"{v0*100:.1f}%"
            v1_str = f"{v1*100:.1f}%" if isinstance(v1, float) else str(v1)
            delta = f"{(v1-v0)*100:+.1f}pp" if isinstance(v1, float) else "N/A"
        else:
            v0_str = f"{v0:.1f}"
            v1_str = f"{v1:.1f}" if isinstance(v1, float) else str(v1)
            delta = f"{v1-v0:+.1f}" if isinstance(v1, (int, float)) else "N/A"
    elif isinstance(v0, int):
        v0_str = str(v0)
        v1_str = str(v1) if isinstance(v1, int) else str(v1)
        delta = f"{v1-v0:+d}" if isinstance(v1, int) else "N/A"
    else:
        v0_str = str(v0)
        v1_str = str(v1)
        delta = "N/A"
    
    print(f"{label:<25} {v0_str:>15} {v1_str:>15} {delta:>12}")

print("=" * 70)
print()
print("KEY DELTAS:")
print(f"  1) Drivers: {rc0.get('total_drivers')} -> {rc1.get('total_drivers')} (Delta: {rc1.get('total_drivers', 0) - rc0.get('total_drivers', 0):+d})")
print(f"  2) 1er_share_%: {rc0.get('tour_share_1er', 0)*100:.1f}% -> {rc1.get('tour_share_1er', 0)*100:.1f}% (Delta: {(rc1.get('tour_share_1er', 0) - rc0.get('tour_share_1er', 0))*100:+.1f}pp)")
print(f"  3) missed_multi_opps: {rc0.get('missed_multi_opps_count')} -> {rc1.get('missed_multi_opps_count')} (Delta: {rc1.get('missed_multi_opps_count', 0) - rc0.get('missed_multi_opps_count', 0):+d})")

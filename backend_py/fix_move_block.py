import sys

content = open('src/services/forecast_solver_v4.py', 'r', encoding='utf-8').read()

old = '''            # Move block PT→FTE
            _move_block(source_pt, fte, block)
            stats["absorbed_blocks"] += 1
            break'''

new = '''            # Move block PT→FTE (skip if constraint violation)
            if _move_block(source_pt, fte, block):
                stats["absorbed_blocks"] += 1
                break'''

content = content.replace(old, new)

with open('src/services/forecast_solver_v4.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done')

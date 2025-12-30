import sys
text = open('scripts/apply_step8_pool_repair_patch.py', 'r', encoding='utf-8').read()
text = text.replace(
    'if line.startswith(anchor_def):',
    'if line.rstrip().startswith(anchor_def):'
)
text = text.replace(
    'if l.startswith("def ") or l.startswith("class "):',
    'if l.rstrip().startswith("def ") or l.rstrip().startswith("class "):'
)
open('scripts/apply_step8_pool_repair_patch.py', 'w', encoding='utf-8').write(text)
print('Fixed line matching')

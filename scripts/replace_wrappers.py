import os, glob

paths = glob.glob('templates/tenant/**/*.html', recursive=True)
replacements = [
    ('tenant/_settings_wrapper.html', 'settings_content'),
    ('tenant/_customer_center_wrapper.html', 'customer_content'),
    ('tenant/_finance_wrapper.html', 'finance_content'),
    ('tenant/_integrations_wrapper.html', 'integrations_content')
]

for path in paths:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    changed = False
    for wrapper, block in replacements:
        if f'extends "{wrapper}"' in content or f"extends '{wrapper}'" in content:
            content = content.replace(f'extends "{wrapper}"', 'extends "tenant/_base_panel.html"')
            content = content.replace(f"extends '{wrapper}'", 'extends "tenant/_base_panel.html"')
            content = content.replace(f'block {block}', 'block panel_content')
            changed = True
    if changed:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
print('Done replacing wrappers.')

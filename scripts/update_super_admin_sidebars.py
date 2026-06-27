import glob

sidebar_link = '<a href="{{ url_for(\'super_admin.support_tickets\') }}" class="block px-4 py-2 rounded-lg hover:bg-gray-700 text-sm">🎫 تذاكر الدعم</a>\n'

for f in glob.glob('c:/Users/almth/Desktop/flask_saas/templates/super_admin/*.html'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    
    if '<nav class="p-4 space-y-1">' in content and 'super_admin.support_tickets' not in content:
        content = content.replace('<nav class="p-4 space-y-1">\n', '<nav class="p-4 space-y-1">\n' + sidebar_link)
        with open(f, 'w', encoding='utf-8') as file:
            file.write(content)
        print(f'Updated {f}')

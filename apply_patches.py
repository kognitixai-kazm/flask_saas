import json
import sys

transcript_path = r'C:\Users\almth\.gemini\antigravity\brain\19e651df-12ce-412e-a8f5-0d9881a1fcfe\.system_generated\logs\transcript_full.jsonl'

with open('restored_landing_v2.html', 'r', encoding='utf-8') as f:
    content = f.read()

with open(transcript_path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            if 'tool_calls' in data:
                for call in data['tool_calls']:
                    if call['name'] in ('replace_file_content', 'multi_replace_file_content'):
                        args = call['args']
                        if 'landing_v2.html' in args.get('TargetFile', ''):
                            if call['name'] == 'multi_replace_file_content':
                                chunks = args.get('ReplacementChunks', [])
                                if isinstance(chunks, str):
                                    chunks = json.loads(chunks)
                                for chunk in chunks:
                                    target = chunk.get('TargetContent', '')
                                    repl = chunk.get('ReplacementContent', '')
                                    if target in content:
                                        content = content.replace(target, repl)
                                        print(f"Replaced a chunk at step {data.get('step_index')}")
                                    else:
                                        print(f"Target not found at step {data.get('step_index')}")
                            elif call['name'] == 'replace_file_content':
                                target = args.get('TargetContent', '')
                                repl = args.get('ReplacementContent', '')
                                if target in content:
                                    content = content.replace(target, repl)
                                    print(f"Replaced content at step {data.get('step_index')}")
                                else:
                                    print(f"Target not found at step {data.get('step_index')}")
        except Exception as e:
            pass

with open('restored_landing_v2.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied all patches.")

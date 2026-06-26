import json
import sys

transcript_path = r'C:\Users\almth\.gemini\antigravity\brain\19e651df-12ce-412e-a8f5-0d9881a1fcfe\.system_generated\logs\transcript_full.jsonl'
with open(transcript_path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            if 'tool_calls' in data:
                for call in data['tool_calls']:
                    if call['name'] == 'write_to_file':
                        args = call['args']
                        if 'landing_v2.html' in args.get('TargetFile', ''):
                            print(f"Found write_to_file at step {data.get('step_index')}")
                            with open('restored_landing_v2.html', 'w', encoding='utf-8') as out:
                                out.write(args['CodeContent'])
                            print("File saved to restored_landing_v2.html")
        except Exception as e:
            pass

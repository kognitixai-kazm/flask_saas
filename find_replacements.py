import json
import sys

transcript_path = r'C:\Users\almth\.gemini\antigravity\brain\19e651df-12ce-412e-a8f5-0d9881a1fcfe\.system_generated\logs\transcript_full.jsonl'
with open(transcript_path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            if 'tool_calls' in data:
                for call in data['tool_calls']:
                    if call['name'] in ('replace_file_content', 'multi_replace_file_content'):
                        args = call['args']
                        if 'landing_v2.html' in args.get('TargetFile', ''):
                            print(f"Found {call['name']} at step {data.get('step_index')}")
        except Exception:
            pass

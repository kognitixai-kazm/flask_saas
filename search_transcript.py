import json

transcript_path = r'C:\Users\almth\.gemini\antigravity\brain\19e651df-12ce-412e-a8f5-0d9881a1fcfe\.system_generated\logs\transcript_full.jsonl'

with open(transcript_path, 'r', encoding='utf-8') as f:
    for line in f:
        if 'سرعة التنفيذ' in line:
            print("Found in transcript!")
            break
else:
    print("Not found in transcript.")

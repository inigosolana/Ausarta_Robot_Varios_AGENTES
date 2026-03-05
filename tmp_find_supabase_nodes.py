import json
import os
import glob

workflows_path = "n8n/workflows/*.json"
files = glob.glob(workflows_path)

results = []

for file_path in files:
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            nodes = data.get('nodes', [])
            for node in nodes:
                params = node.get('parameters', {})
                url = params.get('url', '')
                if isinstance(url, str) and 'supabase.co' in url:
                    results.append({
                        "file": os.path.basename(file_path),
                        "id": node.get('id'),
                        "name": node.get('name'),
                        "type": node.get('type'),
                        "url": url,
                        "auth": params.get('authentication'),
                        "nodeCredType": params.get('nodeCredentialType'),
                        "credentials": node.get('credentials')
                    })
    except Exception as e:
        print(f"Error reading {file_path}: {e}")

print(json.dumps(results, indent=2))

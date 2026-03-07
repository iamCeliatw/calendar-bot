import os
import json
import sys

token_json = os.environ.get("GOOGLE_TOKEN_JSON", "")
if not token_json:
    print("ERROR: GOOGLE_TOKEN_JSON secret is empty")
    sys.exit(1)

try:
    json.loads(token_json)
except json.JSONDecodeError as e:
    print(f"ERROR: Invalid JSON: {e}")
    sys.exit(1)

with open("token.json", "w") as f:
    f.write(token_json)

print(f"token.json written ({len(token_json)} bytes)")

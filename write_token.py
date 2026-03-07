import os
import json
import sys
import base64

token_b64 = os.environ.get("GOOGLE_TOKEN_JSON_B64", "")
if not token_b64:
    print("ERROR: GOOGLE_TOKEN_JSON_B64 secret is empty")
    sys.exit(1)

try:
    token_json = base64.b64decode(token_b64).decode("utf-8")
    json.loads(token_json)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)

with open("token.json", "w") as f:
    f.write(token_json)

print(f"token.json written ({len(token_json)} bytes)")

#!/bin/bash
# Surgical: add /v2/ SPA fallback. Does not rewrite the rest of spark-portal
# (keeps /hermes/ and all /api/*). Safe to run while inference is serving.
set -euo pipefail

SITE=/etc/nginx/sites-available/spark-portal
MARKER="# Portal v2 SPA"

if grep -q 'location /v2/' "$SITE"; then
  echo "nginx already has /v2/"
  nginx -t
  systemctl reload nginx
  echo "nginx reloaded"
  exit 0
fi

cp -a "$SITE" "${SITE}.bak-pre-portal-v2"

python3 - <<'PY'
from pathlib import Path
path = Path("/etc/nginx/sites-available/spark-portal")
text = path.read_text()
block = """
    # Portal v2 SPA
    location = /v2 {
        return 308 /v2/;
    }
    location /v2/ {
        try_files $uri $uri/ /v2/index.html;
    }

"""
needle = "    location / {\n"
if needle not in text:
    raise SystemExit("could not find location / block to insert before")
path.write_text(text.replace(needle, block + needle, 1))
print("inserted /v2/ location")
PY

nginx -t
systemctl reload nginx
echo "nginx reloaded — /v2/ live, inference untouched"

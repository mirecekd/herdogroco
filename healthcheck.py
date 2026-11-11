# healthcheck.py
"""Container healthcheck: exit 0 when GET /health answers HTTP 200, else 1."""

import http.client
import os
import sys
import urllib.request

port = os.environ.get("PORT", "8130")
url = f"http://127.0.0.1:{port}/health"

try:
    with urllib.request.urlopen(url, timeout=4) as response:
        status = response.status
except (OSError, http.client.HTTPException) as e:
    print(f"healthcheck failed for {url}: {e}")
    sys.exit(1)

if status != 200:
    print(f"healthcheck failed for {url}: HTTP {status}")
    sys.exit(1)

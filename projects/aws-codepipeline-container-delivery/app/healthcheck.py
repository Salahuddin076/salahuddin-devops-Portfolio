"""Container health probe: exit 0 when GET /healthz returns 200.

Used by the Dockerfile HEALTHCHECK and the ECS task definition healthCheck
(ECS ignores the image's HEALTHCHECK, so both point at this script).
The slim base image has no curl, so this uses urllib.
"""

import os
import sys
import urllib.request


def main() -> int:
    port = os.environ.get("PORT", "8080")
    url = f"http://127.0.0.1:{port}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310 (fixed local URL)
            return 0 if response.status == 200 else 1
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())

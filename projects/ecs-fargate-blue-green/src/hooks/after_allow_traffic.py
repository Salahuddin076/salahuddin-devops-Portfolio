"""CodeDeploy AfterAllowTraffic hook: verify production after the shift.

Runs once 100% of production traffic is on the replacement task set.
PROD_BASE_URL is the production listener, e.g. https://api.example.com.
The same checks as BeforeAllowTraffic (health, image tag, p95 budget) now
prove the production route really serves the new version. A Failed status
rolls traffic back to the original task set, which is still running during
the termination wait.

Lambda handler: after_allow_traffic.handler
"""

from __future__ import annotations

from typing import Any, Mapping

from lifecycle import handle

HOOK_NAME = "AfterAllowTraffic"
URL_VAR = "PROD_BASE_URL"


def handler(event: Mapping[str, Any], context: Any = None, **deps: Any) -> dict:
    return handle(event, context, hook_name=HOOK_NAME, url_var=URL_VAR, **deps)

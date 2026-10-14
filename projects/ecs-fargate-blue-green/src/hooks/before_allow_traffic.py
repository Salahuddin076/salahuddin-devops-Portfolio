"""CodeDeploy BeforeAllowTraffic hook: smoke-test the replacement task set.

Runs while the replacement (green) task set is registered behind the test
listener and before any production traffic moves to it. TEST_BASE_URL is
the test listener, e.g. https://api.example.com:8443. A Failed status here
stops the deployment and CodeDeploy rolls back; production never saw green.

Lambda handler: before_allow_traffic.handler
"""

from __future__ import annotations

from typing import Any, Mapping

from lifecycle import handle

HOOK_NAME = "BeforeAllowTraffic"
URL_VAR = "TEST_BASE_URL"


def handler(event: Mapping[str, Any], context: Any = None, **deps: Any) -> dict:
    return handle(event, context, hook_name=HOOK_NAME, url_var=URL_VAR, **deps)

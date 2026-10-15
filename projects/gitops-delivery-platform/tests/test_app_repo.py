"""Runs the app repo's own unit tests as part of this suite.

In the real two-repo setup app-repo/ is its own repository and its CI runs
`python -m unittest discover -s tests` there; this file pulls the same tests in.
"""

from __future__ import annotations

import sys

from helpers import APP_REPO

sys.path.insert(0, str(APP_REPO / "tests"))

from test_orders_api import OrdersApiTests  # noqa: E402,F401

if __name__ == "__main__":
    import unittest
    unittest.main()

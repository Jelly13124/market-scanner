"""Entry shim — exists so ``python -m v2.backtesting.run`` works.

The actual argparse logic lives in ``cli.py``. Keeping the shim minimal
means notebook / direct callers can ``from v2.backtesting.cli import main``
without importing this module.
"""

from __future__ import annotations

import sys

from v2.backtesting.cli import main


if __name__ == "__main__":
    sys.exit(main())

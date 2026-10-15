"""Entry point: ``python -m appSlicerSegelin.v2``."""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from appSlicerSegelin.v2.ui.app import run

    return run(argv if argv is not None else sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())

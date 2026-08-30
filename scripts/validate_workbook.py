from __future__ import annotations

import argparse
from pathlib import Path

from stock_analysis.export.workbook import Workbook_Validate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    arguments = parser.parse_args()
    Workbook_Validate(arguments.path)
    print(f"validated: {arguments.path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


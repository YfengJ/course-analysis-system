import sys
import unittest
from pathlib import Path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    suite = unittest.defaultTestLoader.discover(
        str(project_root / "tests"),
        pattern="test*.py",
        top_level_dir=str(project_root),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InstallationWorkflowTest(unittest.TestCase):
    def test_reset_demo_initializes_a_fresh_sqlite_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "runtime"
            env = os.environ.copy()
            env.update(
                {
                    "COURSE_SYSTEM_DATA_DIR": str(data_dir),
                    "DEFAULT_ADMIN_PASSWORD": "ReviewPass123!",
                    "SECRET_KEY": "installation-workflow-test-secret",
                }
            )

            result = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "init_db.py"), "--reset-demo"],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            database_path = data_dir / "instance" / "attainment_system.db"
            self.assertTrue(database_path.is_file())
            with sqlite3.connect(database_path) as connection:
                course_count = connection.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
            self.assertGreater(course_count, 0)


if __name__ == "__main__":
    unittest.main()

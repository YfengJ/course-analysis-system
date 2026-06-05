import re
import unittest
from pathlib import Path

from scripts.build_release import collect_release_files


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReleasePackageTest(unittest.TestCase):
    def test_release_file_list_keeps_source_and_excludes_private_runtime_data(self):
        files = collect_release_files(PROJECT_ROOT)

        self.assertIn("app.py", files)
        self.assertIn("README.md", files)
        self.assertIn("scripts/run_tests.py", files)
        self.assertIn("scripts/build_release.py", files)
        self.assertIn("docs/部署与使用说明.md", files)
        self.assertNotIn("scripts/build_teacher_release.py", files)
        self.assertNotIn("generate_thesis_docs.py", files)
        self.assertFalse(any(item.startswith("docs/superpowers/") for item in files))
        self.assertNotIn("scripts/revise_thesis_figures_0430.py", files)
        self.assertFalse(any(item.startswith("instance/") for item in files))
        self.assertFalse(any(item.startswith("uploads/") for item in files))
        self.assertFalse(any(item.startswith("exports/") for item in files))
        self.assertFalse(any(item.startswith("dist/") for item in files))
        self.assertFalse(any(item.startswith("datasoruce/") for item in files))
        self.assertFalse(any(item.startswith("成绩和教学大纲/") for item in files))
        self.assertFalse(any(item.endswith(".db") for item in files))
        self.assertFalse(any(item.endswith(".xlsm") for item in files if not item.startswith("sample_data/")))

    def test_release_text_files_do_not_contain_private_or_thesis_markers(self):
        files = collect_release_files(PROJECT_ROOT)
        scanned_suffixes = {".html", ".js", ".json", ".md", ".py", ".txt", ".css"}
        blocked_terms = (
            "毕业" + "设计",
            "答" + "辩",
            "graduation" + "-" + "design",
            "/" + "Users" + "/" + "yfengj",
            "Desk" + "top",
        )
        secret_key_pattern = re.compile(r"sk-[A-Za-z0-9]{16,}")
        for relative in files:
            path = Path(relative)
            if path.suffix not in scanned_suffixes or relative.startswith("static/vendor/"):
                continue
            content = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
            for term in blocked_terms:
                with self.subTest(file=relative, term=term):
                    self.assertNotIn(term, content)
            with self.subTest(file=relative, term="key-like-secret"):
                self.assertIsNone(secret_key_pattern.search(content))


if __name__ == "__main__":
    unittest.main()

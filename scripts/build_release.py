import argparse
import zipfile
from pathlib import Path


EXCLUDED_DIRS = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "datasoruce",
    "dist",
    "docx",
    "exports",
    "instance",
    "mimic",
    "node_modules",
    "output",
    "tmp",
    "uploads",
    "成绩和教学大纲",
}
EXCLUDED_FILENAMES = {
    ".DS_Store",
    ".env",
    ".flaskenv",
    "findings.md",
    "generate_thesis_docs.py",
    "progress.md",
    "task_plan.md",
}
EXCLUDED_PREFIXES = {
    "docs/superpowers/",
}
EXCLUDED_SUFFIXES = {
    ".bak",
    ".db",
    ".pyc",
    ".sqlite",
    ".sqlite3",
}
OFFICE_SUFFIXES = {".doc", ".docx", ".xls", ".xlsx", ".xlsm"}
SCRIPT_ALLOWLIST = {
    "scripts/build_release.py",
    "scripts/run_tests.py",
}


def _as_posix(path: Path) -> str:
    return path.as_posix()


def should_include(relative_path: Path) -> bool:
    relative = _as_posix(relative_path)
    parts = set(relative_path.parts)
    if parts & EXCLUDED_DIRS:
        return False
    if any(relative.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    if relative_path.name in EXCLUDED_FILENAMES:
        return False
    if relative_path.suffix in EXCLUDED_SUFFIXES:
        return False
    if relative.startswith("scripts/") and relative not in SCRIPT_ALLOWLIST:
        return False
    if relative_path.suffix in OFFICE_SUFFIXES and not relative.startswith("sample_data/"):
        return False
    return True


def collect_release_files(project_root: Path) -> list[str]:
    root = Path(project_root).resolve()
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(root)
        if should_include(relative_path):
            files.append(_as_posix(relative_path))
    return sorted(files)


def build_release_archive(project_root: Path, output_path: Path) -> Path:
    root = Path(project_root).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    files = collect_release_files(root)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for relative in files:
            package.write(root / relative, relative)
    return output_path


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="构建不含真实课程数据的系统发布包。")
    parser.add_argument(
        "--output",
        default=str(project_root / "dist" / "course-system-release.zip"),
        help="发布包输出路径，默认写入 dist/course-system-release.zip。",
    )
    args = parser.parse_args()
    output = build_release_archive(project_root, Path(args.output))
    print(f"系统发布包已生成：{output}")
    print(f"包含文件数：{len(collect_release_files(project_root))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# Contributing

Thank you for helping improve Course Attainment Report System. This project is designed for local course analysis workflows, so privacy and reproducibility matter more than flashy changes.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python init_db.py
python app.py
```

Run checks before submitting changes:

```bash
python -m compileall app.py config.py models.py routes services scripts tests
python scripts/run_tests.py
python scripts/build_release.py
```

## Contribution Scope

Good first areas to improve:

- score import adapters for more spreadsheet layouts
- syllabus parsing robustness
- report quality checks and archive package contents
- deployment documentation and screenshots
- tests for calculation rules and report export behavior

## Privacy Rules

Do not commit:

- `.env` files, API keys, passwords, or local secrets
- SQLite databases, backups, uploads, exported reports, or runtime folders
- real syllabi, student scores, names, identifiers, or course files
- local IDE settings, virtual environments, browser binaries, or cache files

Use the sanitized files in `sample_data/` for examples and tests.

## Pull Request Checklist

- The change is limited to one clear purpose.
- Tests or documentation are updated when behavior changes.
- `python scripts/run_tests.py` passes locally.
- `python scripts/build_release.py` still excludes private runtime data.
- Screenshots are sanitized before being added to `docs/images/`.

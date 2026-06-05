# Security Policy

This project is usually deployed as a local or internal tool. It may process sensitive course, score, and report files in real use, so please treat security and privacy issues carefully.

## Supported Version

The `main` branch is the maintained public branch.

## Reporting A Security Issue

Please do not open a public issue for secrets, private course files, or student data exposure. Contact the repository owner privately, or create a minimal public issue that describes the affected component without attaching sensitive files.

When reporting, include:

- affected version or commit
- reproduction steps using sanitized data
- expected and actual behavior
- whether local files, exported reports, or model service keys may be exposed

## Data Handling Expectations

- Keep databases, uploads, exports, backups, and `.env` files outside commits.
- Prefer `COURSE_SYSTEM_DATA_DIR` for deployment data.
- Use `scripts/build_release.py` before sharing a package.
- Use sanitized screenshots and sample data in documentation.

# Release Checklist

Use this checklist before publishing repository updates, sharing a release package, or handing the system to another user.

## 1. Run Local Checks

```bash
python -m compileall app.py config.py models.py routes services scripts tests
python scripts/run_tests.py
python scripts/build_release.py
```

Expected result:

- Python files compile successfully.
- Unit tests pass, with only documented private-file integration tests skipped when those files are not present.
- `dist/course-system-release.zip` is regenerated.

## 2. Check Package Contents

The release archive must not contain:

- `.env`, API keys, passwords, or local secrets
- SQLite databases, backup files, uploads, exports, or runtime folders
- real course syllabi, score sheets, student information, or generated reports
- local virtual environments, browser binaries, IDE settings, or caches

The archive should contain:

- source code
- templates and static assets
- sanitized screenshots under `docs/images/`
- sanitized sample data under `sample_data/`
- README files, deployment guide, contribution guide, security policy, and GitHub maintenance files

## 3. Scan Text Content

Before pushing, scan public text files for:

- local absolute paths
- model service keys or key-like strings
- old private course names or course identifiers
- generated report names or private file names

Only placeholder values such as `your-model-service-key` should appear in public documentation.

## 4. Check Screenshots

Screenshots must show only sanitized demo data, such as:

- course code `DEMO1001`
- course name `示例课程`
- demo class names and demo student records

Do not publish screenshots that show real course names, student names, scores, local paths, or browser tabs with private information.

## 5. Sync To GitHub

Because the working project directory may contain local runtime data, publish through a clean temporary clone:

1. Clone `YfengJ/course-analysis-system` into `/tmp`.
2. Remove tracked files in the temporary clone.
3. Unzip `dist/course-system-release.zip` into the temporary clone.
4. Restore repository-only files such as `LICENSE` when needed.
5. Review `git diff --cached`.
6. Commit and push only the sanitized public files.

## 6. Confirm Remote State

After pushing:

- confirm `main` points to the new commit
- confirm GitHub Actions finished successfully
- check open issues and labels
- update the changelog when the public behavior, documentation, or release process changes

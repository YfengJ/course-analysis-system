# Changelog

All notable public-facing changes are tracked here.

## Unreleased

- Fixed score import wrongly rejecting blank/absent score cells as "not a valid number", so sheets with missing scores now preview and import correctly.
- Validated every file in multi-file score uploads against the extension allowlist, closing a bypass where only the first file was checked.
- Added accessible labels to qualitative count inputs, removed dead gauge-chart code, and hardened chart rendering against missing data.
- Restricted version control to the public release file set, keeping private thesis-authoring scripts and working notes out of the repository.
- Updated Pillow to 12.3.0 to incorporate current image-processing security fixes.
- Made analysis saves atomic, linked snapshots to their source imports, and prevented invalidated or cross-scope reports from appearing current.
- Corrected qualitative aggregation, rejected nonnumeric split scores, removed obsolete objectives on outline reimport, and aligned insight generation with active revisions.
- Made backup restoration validate and stage every artifact before replacement, restore managed folders exactly, roll back failures, and clean temporary candidates.
- Derived report class labels from the selected semester, included removed objectives in version comparisons, and tightened class-scoped report quality checks.
- Replaced release packaging deny rules with an explicit public-file allowlist and added visible form errors, role-aware navigation, labels, and archive confirmation.
- Hardened write operations with global CSRF protection and corrected teacher-level course and report visibility boundaries.
- Made multi-file score imports atomic, detected duplicate student numbers across files, and prevented same-name uploads from overwriting each other.
- Invalidated current analysis, revisions, and insights when source inputs change while preserving historical reports and snapshots.
- Added stricter report quality checks for objective weights, assessment allocation, and objective-to-assessment mappings.
- Hardened backup restoration with archive limits and SQLite integrity validation, and constrained report downloads and archive files to configured runtime roots.
- Added persistent generated session secrets, secure remote LLM endpoint validation, upgraded vulnerable dependencies, and aligned local/CI checks through `npm test`.
- Redesigned the interface as a compact course workbench with clearer course status, next actions, workflow navigation, and report review hierarchy.
- Added accessible responsive navigation, visible keyboard focus states, reduced-motion support, and mobile-safe report tables.
- Refreshed all public screenshots with sanitized demo data from the new interface.
- Added Dependabot maintenance checks for GitHub Actions, Python dependencies, and npm dependencies.
- Added a public release checklist for privacy, packaging, and GitHub maintenance checks.
- Set the English README as the repository homepage and added a Chinese README switch.
- Added sanitized interface screenshots for the dashboard, analysis page, and report preview.
- Added GitHub issue templates, pull request template, CI workflow, contribution guide, and security policy.
- Updated the built-in demo course identifier to `DEMO1001`.

## 2026-06-06

- Published a sanitized repository version with source code, templates, tests, sample data, and deployment documentation.
- Added release packaging that excludes local runtime data, real course files, databases, reports, and secrets.
- Added authentication, backup and restore, report quality checks, course archive packages, and report version comparison support.

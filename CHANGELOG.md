# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While in `0.x`, minor releases may contain breaking changes; they are always
listed under **Changed** or **Removed** with migration notes.

## [Unreleased]

### Added

- Project scaffold: packaging with a wheel build hook that bundles the React SPA,
  CI (lint, mypy, tests on Python 3.11–3.13, security scans, wheel smoke test,
  Playwright E2E), release workflow with PyPI Trusted Publishing, CodeQL and
  Dependabot.
- Architecture docs, threat model and ADRs 0001–0007.

## [0.0.1] - 2026-11-23

### Added

- Name reservation placeholder release on PyPI.

[Unreleased]: https://github.com/bekzod818/faststudio/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/bekzod818/faststudio/releases/tag/v0.0.1

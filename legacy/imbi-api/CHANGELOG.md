# Changelog

## [Unreleased]

## [0.22.13] - 2024-11-26
### Fixed
- Handle notifications on projects connected to more than one external project

## [0.22.12] - 2024-11-15
### Changed
- Refactored the OpenSearch implementation significantly
- `/projects/build-search-index` and `/operations-log/build-search-index` endpoints now accept zero or more `id` query parameters to constrain rebuilds

### Fixed
- Update search index when projects are changed by notification processing

## [0.22.11] - 2024-11-11
### Added
- Make operations log table sortable
- Pre-populate project details when creating an Operations log entry from a project page

## [0.22.10] - 2024-10-18
### Added
- `performed_by` override for operations log entries

## [0.22.9] - 2024-09-12
### Changed
- Operations log entries now require a description
- Operations log entries now require a `recorded_at` field
- Operations log ticket slugs now support a comma-separated list of tickets

### Fixed
- Update JS for a small UI fix

## [0.22.8] - 2024-09-06
### Fixed
- Invalid SQL in `ProjectScoreDetailHandler`

## [0.22.7] - 2024-09-03
### Added
- Outdated Projects report
- Record per-version component score in database

### Fixed
- Edge case errors in project scoring

## [0.22.6] - 2024-08-19
### Added
- Associate & disassociate PagerDuty services based on project dependencies
using a new set of automations
- Optionally add a project fact that is derived from the status of the project's
components and maintain it
- Detailed project score calculation panel

## [0.22.5] - 2024-07-30
### Added
- Project information to `/projects/{}/dependencies`

## [0.22.4] - 2024-07-10
### Fixed
- SBoM ingest defects

## [0.22.3] - 2024-07-09
### Added
- SSM parameter updating
- SBoM ingest for projects
- AWS role management in admin UI

## [0.22.2] - 2024-06-21
### Added
- SSM parameter creation & deletion
- Project Component APIs

### Fixed
- Session cache fixation defect

## [0.21.1] - 2024-05-16
### Added
- SonarQube create-project automation
- PagerDuty create-project automation

## [0.21.0] - 2024-05-06
### Added
- GitLab create-project automation
- Sentry create-project automation

## [0.20.3] - 2024-04-05
### Fixed
- Index projects when surrogate IDs are modified

## [0.20.2] - 2024-03-26
### Fixed
- SQL syntax error

## [0.20.1] - 2024-03-20
### Added
- Notification processing configuration endpoints: `/integrations/{}/notifications/{}/actions`,
`/integrations/{}/notifications/{}/filters`, and `/integrations/{}/notifications/{}/rules`
- Foundation endpoints for automations (`/integrations/{}/automations/{}`)

### Changed
- Save OIDC `id_token` from Google account connection
- Switch to compose.yaml (see https://compose-spec.io)
- Change _Makefile_ to be Bourne shell compliant
- Update to pydantic v2
- Add PostgreSQL helper functions for dynamic `INSERT` and `UPDATE` queries
- Use pydantic validation for the stuff that OpenAPI doesn't handle

[Unreleased]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.13...HEAD
[0.22.13]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.12...0.22.13
[0.22.12]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.11...0.22.12
[0.22.11]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.10...0.22.11
[0.22.10]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.9...0.22.10
[0.22.9]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.8...0.22.9
[0.22.8]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.7...0.22.8
[0.22.7]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.6...0.22.7
[0.22.6]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.5...0.22.6
[0.22.5]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.4...0.22.5
[0.22.4]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.3...0.22.4
[0.22.3]: https://github.com/AWeber-Imbi/imbi-api/compare/0.22.2...0.22.3
[0.22.2]: https://github.com/AWeber-Imbi/imbi-api/compare/0.21.1...0.22.2
[0.21.1]: https://github.com/AWeber-Imbi/imbi-api/compare/0.21.0...0.21.1
[0.21.0]: https://github.com/AWeber-Imbi/imbi-api/compare/0.20.3...0.21.0
[0.20.3]: https://github.com/AWeber-Imbi/imbi-api/compare/0.20.2...0.20.3
[0.20.2]: https://github.com/AWeber-Imbi/imbi-api/compare/0.20.1...0.20.2
[0.20.1]: https://github.com/AWeber-Imbi/imbi-api/tags/0.20.1

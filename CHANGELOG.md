# Changelog

## [Unreleased]

### Added
- Normalized internal `Project` dataclass (`project.py`)
- `normalize_kwork_project()` in `adapters/kwork.py`
- AI scoring integrated into main processing loop
- Redis service in `docker-compose.yml` with healthcheck
- `data/` volume for persistent token storage
- Full `app.env.example` with all supported variables
- `source` column in PostgreSQL schema

### Changed
- `monitor.py` now works exclusively with `Project` objects
- Unified paths: token at `/app/data/kwork_token.json`, env at `/app/app.env`
- `docker-compose.yml` uses healthchecks for dependency ordering
- PostgreSQL credentials moved to env variables

## [0.1.0] - 2026-03

### Added
- Initial release
- Kwork project monitoring
- Telegram notifications
- Keyword and category filtering
- Redis deduplication
- PostgreSQL storage
- Startup sweep
- Telegram commands: /pause, /resume, /status, /score_on, /score_off

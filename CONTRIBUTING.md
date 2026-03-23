# Contributing

## Getting Started

1. Fork the repository
2. Clone your fork
3. Copy `app.env.example` to `app.env` and fill in your credentials
4. Run `docker compose up -d`

## Adding a Platform Adapter

1. Create `adapters/<platform>.py` with an API client class
2. Add a `normalize_<platform>_project(raw: dict) -> Project` function
3. Update `monitor.py` to import and use your adapter
4. Update `app.env.example` with any new required variables
5. Update `README.md`

## Code Style

- Python 3.11+
- No external linters required, but keep it readable
- No type: ignore comments without explanation

## Pull Requests

- One feature or fix per PR
- Include a brief description of what changed and why
- Test manually before submitting

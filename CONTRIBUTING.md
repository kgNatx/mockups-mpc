# Contributing to mockups-mpc

Thanks for your interest in contributing. This guide covers the basics.

## Dev Setup

```bash
git clone https://github.com/kgNatx/mockups-mpc.git
cd mockups-mpc
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running Tests

```bash
pytest tests/ -v
```

Tests use `pytest-asyncio` with auto mode. See `pytest.ini` for config.

## Running Locally

```bash
uvicorn app.main:app --reload
```

The app will be available at `http://localhost:8000`.

## Docker

```bash
docker compose -f docker-compose.local.yml up --build
```

## Pull Request Guidelines

- Make sure all tests pass before submitting.
- Follow existing code patterns and conventions.
- Keep PRs focused -- one change per PR when possible.
- Add tests for new functionality.
- Update `CHANGELOG.md` if your change is user-facing.

## Reporting Issues

Use the GitHub issue templates for bug reports and feature requests.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

# Contributing to imbi-common

Thank you for your interest in contributing to imbi-common! This document
provides guidelines and instructions for contributing.

## Development Setup

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) package manager
- Docker and Docker Compose (for integration tests)
- Git

### Getting Started

1. **Fork and clone the repository**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/imbi-common.git
   cd imbi-common
   ```

2. **Install dependencies using uv**:
   ```bash
   uv pip install -e ".[dev]"
   ```

3. **Install pre-commit hooks**:
   ```bash
   pre-commit install
   ```

4. **Start test databases** (for integration tests):
   ```bash
   docker-compose -f docker-compose.test.yml up -d
   ```

## Development Workflow

### Running Tests

**Unit tests only** (no external dependencies):
```bash
SKIP_INTEGRATION_TESTS=1 python -m unittest discover tests -v
```

**All tests** (requires Docker services):
```bash
python -m unittest discover tests -v
```

**Specific test module**:
```bash
python -m unittest tests.test_settings -v
```

### Code Quality

**Type checking with mypy**:
```bash
mypy src/imbi_common
```

**Linting with ruff**:
```bash
ruff check src/imbi_common tests
```

**Format code with ruff**:
```bash
ruff format src/imbi_common tests
```

**Run all pre-commit hooks**:
```bash
pre-commit run --all-files
```

### Building Documentation

**Serve documentation locally**:
```bash
mkdocs serve
```

Then visit `http://localhost:8000`

**Build documentation**:
```bash
mkdocs build --strict
```

## Coding Standards

### Python Style

- Follow PEP 8 style guide
- Maximum line length: 79 characters
- Use type hints for all function signatures
- Write docstrings for all public functions, classes, and modules
- Use Google-style docstrings for compatibility with mkdocstrings

### Import Style

**Import modules, not objects**:
```python
# ✅ Correct
import pathlib
import datetime

# ❌ Incorrect
from pathlib import Path
from datetime import datetime
```

**Exception**: You can import objects from imbi_common itself:
```python
# ✅ Correct
from imbi_common import settings, models, neo4j
from imbi_common.auth import core
```

### Testing

- Use Python's standard `unittest` framework (not pytest)
- Write unit tests that don't require external dependencies
- Use integration tests for database operations
- Skip integration tests with `SKIP_INTEGRATION_TESTS` environment variable
- Each test should be independent and clean up after itself
- Use descriptive test method names

### Documentation

- Update documentation when adding features or changing APIs
- Add docstrings to all public functions and classes
- Include examples in docstrings when helpful
- Update CHANGELOG.md for significant changes

## Submitting Changes

### Pull Request Process

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**:
   - Write code following the coding standards
   - Add tests for new functionality
   - Update documentation as needed
   - Ensure all tests pass
   - Ensure code quality checks pass

3. **Commit your changes**:
   ```bash
   git add .
   git commit -m "Brief description of changes"
   ```

   Commit message format:
   - Use present tense ("Add feature" not "Added feature")
   - Use imperative mood ("Move cursor to..." not "Moves cursor to...")
   - Limit first line to 72 characters
   - Reference issues and pull requests when applicable

4. **Push to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

5. **Open a Pull Request**:
   - Provide a clear description of the changes
   - Reference any related issues
   - Ensure CI checks pass

### Pull Request Guidelines

- **Keep it focused**: One feature or fix per PR
- **Write tests**: All new code should have tests
- **Update docs**: Document new features and API changes
- **Follow conventions**: Match existing code style and patterns
- **Clean history**: Squash fixup commits before submitting

## Testing Strategy

### Unit Tests

Unit tests should not require external dependencies (no Docker):

- Settings validation and loading
- Model creation and validation
- Password hashing and JWT token creation
- Encryption/decryption functions
- Logging configuration

### Integration Tests

Integration tests require Docker services:

- Neo4j CRUD operations
- ClickHouse query execution
- End-to-end workflows

Use base test classes from `tests/__init__.py`:

```python
from tests import Neo4jTestCase

class TestProjectCRUD(Neo4jTestCase):
    async def test_create_project(self):
        # Test code here
        pass
```

## Code Review Process

All submissions require review before merging:

1. **Automated checks**: CI must pass (tests, type checking, linting)
2. **Code review**: At least one maintainer approval required
3. **Documentation**: Docs must be updated for API changes
4. **Tests**: New functionality must have tests
5. **Changelog**: Significant changes should update CHANGELOG.md

## Release Process

Releases are handled by maintainers:

1. Update version in `pyproject.toml`
2. Update CHANGELOG.md with release notes
3. Create and push git tag: `git tag v0.x.0 && git push --tags`
4. GitHub Actions automatically builds and publishes to PyPI
5. GitHub Pages automatically updates documentation

## Getting Help

- **Issues**: Open an issue for bugs or feature requests
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: Check the [docs](https://aweber.github.io/imbi-common/)

## Code of Conduct

Be respectful and professional in all interactions. We follow the
[Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

## License

By contributing, you agree that your contributions will be licensed under the
BSD-3-Clause License.

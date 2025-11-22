# Imbi 2.0 Migration Guide

This document outlines the migration from Imbi 1.x (Tornado) to Imbi 2.0 (FastAPI).

## Overview

Imbi 2.0 represents a complete architectural modernization:

- **Framework:** Tornado → FastAPI
- **Python:** 3.7+ → 3.12+
- **Packaging:** setup.py/setup.cfg → pyproject.toml
- **Structure:** Multiple submodules → Consolidated src/ layout
- **ORM:** sprockets-postgres → Piccolo
- **OpenAPI:** Manual (tornado-openapi3) → Auto-generated
- **New Features:** Claude AI integration, MCP server

## Repository Changes

### Before
```
imbi/
├── api/                 # Git submodule (imbi-api)
├── ddl/                 # Git submodule (imbi-schema)
├── openapi/             # Git submodule (imbi-openapi)
└── ui/                  # Git submodule (imbi-ui)
```

### After
```
imbi/
├── src/imbi/           # Consolidated API code (no submodule)
│   ├── api/
│   ├── models/
│   ├── routers/
│   ├── chat/           # NEW: Claude integration
│   └── mcp/            # NEW: MCP server
├── ui/                 # Git submodule (unchanged)
├── pyproject.toml      # NEW: Modern Python config
└── PRD.md              # NEW: Product requirements
```

### Removed Components
- ❌ `api/` submodule - Consolidated into `src/imbi/`
- ❌ `ddl/` submodule - Replaced by Piccolo migrations
- ❌ `openapi/` submodule - FastAPI auto-generates spec
- ❌ All GitLab integration code

## Breaking Changes

### API Changes

#### 1. Base URL Structure (Unchanged)
```
# All endpoints remain the same
GET /api/projects
POST /api/projects
GET /api/namespaces
```

#### 2. Authentication (Compatible)
```python
# Session cookies - COMPATIBLE (same format)
Cookie: session=<secure-cookie>

# API tokens - COMPATIBLE
Private-Token: <token>
```

#### 3. Response Format (Compatible)
```json
// FastAPI returns the same JSON structure
{
  "id": 1,
  "name": "Service Name",
  "namespace": "platform",
  ...
}
```

#### 4. Error Format (Unchanged)
```json
// Still uses RFC 7807 problem details
{
  "type": "https://imbi.example.com/errors/not-found",
  "title": "Item Not Found",
  "status": 404,
  "detail": "Project with ID 999 not found"
}
```

### Database Changes

#### 1. Schema Structure (Unchanged)
- All tables remain in `v1` schema
- No breaking schema changes
- Existing data fully compatible

#### 2. Migration System
```bash
# OLD: DDL scripts in imbi-schema
cd ddl && make apply

# NEW: Piccolo migrations
imbi-migrate forward
```

## Installation

### Development Setup

```bash
# Clone repository
git clone https://github.com/aweber/imbi.git
cd imbi

# Checkout migration branch
git checkout feature/fastapi-migration

# Initialize UI submodule (ddl/openapi removed)
git submodule update --init ui

# Install dependencies
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,test]"

# Setup database
docker-compose up -d postgres redis opensearch
imbi-migrate forward

# Run development server
imbi-server --config example.yaml --reload
```

### Production Deployment

```bash
# Build Docker image
docker build -t aweber/imbi:2.0 .

# Run container
docker run -d \
  -p 8000:8000 \
  -v /path/to/config.yaml:/app/config.yaml \
  -e IMBI_CONFIG=/app/config.yaml \
  aweber/imbi:2.0
```

## Configuration Changes

### Old Configuration (Tornado)
```yaml
# example.yaml (Tornado format)
http:
  port: 8000
  processes: 4
  xheaders: true

postgres:
  url: postgresql://user:pass@host/db
  max_pool_size: 10
  min_pool_size: 1
  query_timeout: 30
```

### New Configuration (FastAPI)
```yaml
# example.yaml (FastAPI format - mostly compatible!)
http:
  host: 0.0.0.0
  port: 8000
  workers: 4  # Changed from 'processes'

postgres:
  url: postgresql://user:pass@host/db
  max_pool_size: 10
  min_pool_size: 1
  timeout: 30  # Changed from 'query_timeout'

# NEW: Claude integration (optional)
claude:
  api_key: ${ANTHROPIC_API_KEY}
  model: claude-sonnet-4.5
  max_tokens: 4096

# NEW: MCP server (optional)
mcp:
  enabled: true
  host: 0.0.0.0
  port: 3000
```

## Testing Changes

### Old Tests (unittest)
```python
from tests.base import TestCase

class ProjectTests(TestCase):
    def test_create_project(self):
        response = self.fetch('/api/projects', method='POST', body=...)
        self.assertEqual(response.code, 201)
```

### New Tests (pytest)
```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_project(client: AsyncClient):
    response = await client.post('/api/projects', json={...})
    assert response.status_code == 201
```

## New Features

### 1. Claude Chat Interface

```python
# Use the new chat API
POST /api/chat/message
{
  "message": "Show me all projects in the platform namespace"
}

# Response includes AI-generated answer and tool calls
{
  "message": "Here are the projects in the platform namespace...",
  "tool_calls": [
    {
      "tool": "search_projects",
      "parameters": {"namespace": "platform"}
    }
  ]
}
```

### 2. MCP Server

```bash
# Run standalone MCP server
imbi-mcp --host localhost --port 3000

# Configure Claude Desktop
# ~/.config/claude/config.json
{
  "mcpServers": {
    "imbi": {
      "command": "imbi-mcp",
      "env": {
        "IMBI_API_URL": "https://imbi.company.com",
        "IMBI_API_TOKEN": "${IMBI_API_TOKEN}"
      }
    }
  }
}
```

### 3. Auto-Generated OpenAPI

```bash
# OpenAPI spec available at:
https://imbi.company.com/api/openapi.json

# Interactive documentation:
https://imbi.company.com/api/docs  # Swagger UI
https://imbi.company.com/api/redoc # ReDoc
```

## Migration Checklist

### For Administrators

- [ ] Review new configuration format
- [ ] Update deployment scripts for FastAPI/uvicorn
- [ ] Run database migrations (`imbi-migrate forward`)
- [ ] Update monitoring/alerting (new metrics format)
- [ ] Test authentication (sessions should work unchanged)
- [ ] Verify all integrations (GitHub, Sentry, etc.)
- [ ] Configure Claude API key (if using AI features)
- [ ] Set up MCP server (if needed)

### For Developers

- [ ] Update local development environment (Python 3.12+)
- [ ] Review new project structure (`src/imbi/`)
- [ ] Update API client code (if needed - should be compatible)
- [ ] Test existing integrations
- [ ] Review new async patterns (if contributing)
- [ ] Update CI/CD pipelines
- [ ] Run new test suite (`pytest`)

### For API Consumers

- [ ] Verify API endpoint compatibility (should be 100% compatible)
- [ ] Test authentication tokens (should work unchanged)
- [ ] Review new OpenAPI spec (auto-generated)
- [ ] Update client libraries if needed
- [ ] Test error handling (same RFC 7807 format)

## Rollback Procedure

If issues are encountered:

```bash
# 1. Revert to previous Docker image
docker run aweber/imbi:1.x

# 2. Restore database from backup
pg_restore -d imbi backup.sql

# 3. Restart services
systemctl restart imbi

# 4. Verify health
curl https://imbi.company.com/api/status
```

## Support

- **Documentation:** https://imbi.readthedocs.io
- **Issues:** https://github.com/aweber/imbi/issues
- **PRD:** See `PRD.md` for detailed product requirements

## FAQ

**Q: Will my existing API integrations break?**
A: No, all endpoints remain the same. Response formats are identical.

**Q: Do I need to migrate my database?**
A: Yes, but Piccolo migrations are automatic: `imbi-migrate forward`

**Q: Can I use the old Tornado version?**
A: Version 1.x will receive security updates for 6 months post-migration.

**Q: Do I have to use the AI features?**
A: No, Claude integration is optional. Core API works without it.

**Q: What happened to GitLab integration?**
A: Removed. Use GitHub instead or contribute a new integration.

**Q: Can I still use Python 3.7?**
A: No, Python 3.12+ is required for FastAPI and modern features.

**Q: Where did the openapi/ submodule go?**
A: FastAPI auto-generates OpenAPI spec. No manual spec needed.

**Q: How do I run migrations?**
A: Use `imbi-migrate forward` instead of `make apply` in ddl/

---

**Last Updated:** 2025-11-22
**Version:** 2.0.0

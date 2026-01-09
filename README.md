# LangChain + Ollama + MCP Client Server

A Python-based LLM server integrating **LangChain**, **Ollama**, and **Model Context Protocol (MCP)** for enhanced AI responses with extensible context sources.

## Features

✅ **LangChain Integration** - Advanced LLM orchestration and chaining
✅ **Multi-LLM Support** - Ollama (local) and OpenAI (cloud) providers
✅ **MCP Client** - Extensible context from multiple sources (SQLite, Web Search, Custom servers)
✅ **FastAPI** - RESTful API with sync and streaming endpoints
✅ **Dual Storage Architecture** - Redis (active cache) + SQL DB (persistent storage)
✅ **API Key Authentication** - HMAC-signed keys with database persistence
✅ **Session Management** - Conversation history with automatic caching
✅ **Flexible Configuration** - JSON-based MCP server config with environment variable support
✅ **HTTP & Process MCP Servers** - Support for both process-based and HTTP-based MCP servers

## Quick Start

### 1. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/download) installed (if using Ollama provider)
- MySQL/MariaDB or PostgreSQL (for persistent storage)
- Redis (for session caching)
- Node.js (optional, for npx-based MCP servers)

### 2. Installation

```bash
# Clone and navigate to project
cd c:\ai\claude

# Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Database Setup

**MySQL/MariaDB**:
```bash
mysql -u root -p
CREATE DATABASE claude_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'claude_user'@'localhost' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON claude_db.* TO 'claude_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

**PostgreSQL**:
```bash
psql -U postgres
CREATE DATABASE claude_db;
CREATE USER claude_user WITH PASSWORD 'your-password';
GRANT ALL PRIVILEGES ON DATABASE claude_db TO claude_user;
\q
```

### 4. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings
# - Database credentials (DB_TYPE, DB_HOST, DB_USER, DB_PASSWORD, DB_NAME)
# - Redis connection (REDIS_HOST, REDIS_PORT)
# - LLM provider (LLM_PROVIDER=ollama or openai)
# - Authentication secret (AUTH_SECRET_KEY)
```

### 5. Start Dependencies

**Ollama** (if using LLM_PROVIDER=ollama):
```bash
ollama pull llama3.2
ollama pull llama3.1
```

**Redis**:
```bash
# Windows: sc start Redis
# Linux/Mac: systemctl start redis
redis-cli ping  # Should return PONG
```

### 6. Run the Server

```bash
# Development mode (with auto-reload)
uvicorn app.main:app --reload

# Production mode
uvicorn app.main:app --workers 4
```

Server runs at: `http://localhost:8000`

## API Usage

### Generate API Key

First, create an API key for authentication:

```bash
python scripts/create_api_key.py admin "Admin Key" 10000

# Output:
# ======================================================================
# ✓ API 키가 성공적으로 생성되었습니다
# ======================================================================
# API Key: ak_1234567890abcdef...
# User ID: admin
# Name: Admin Key
# ⚠️  Save this key now - it won't be shown again!
```

### Health Check

```bash
curl http://localhost:8000/health
```

### Query (Synchronous)

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
    "query": "What are the top 10 products?",
    "model": "llama3.2",
    "mcp_servers": ["sqlite"]
  }'
```

### Query (Streaming)

```bash
curl -X POST http://localhost:8000/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
    "query": "Explain quantum computing",
    "model": "llama3.2",
    "stream": true
  }'
```

### Session-based Conversation

```bash
# First query - creates new session
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-api-key" \
  -d '{"query": "Tell me about Python"}'

# Response includes session_id:
# {"session_id": "sess_abc123...", "response": "...", ...}

# Follow-up query - uses same session for context
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-api-key" \
  -d '{
    "query": "Can you show me some examples?",
    "session_id": "sess_abc123...",
    "use_conversation_history": true
  }'
```

## MCP Server Configuration

Edit [mcp_servers.json](mcp_servers.json) to configure context sources:

### Process-Based Servers

```json
{
  "sqlite": {
    "command": "python",
    "args": ["-m", "mcp.server.sqlite", "--db-path", "./data/app.db"],
    "env": { "PYTHONUNBUFFERED": "1" },
    "description": "SQLite database access",
    "enabled": true
  }
}
```

### HTTP-Based Servers

```json
{
  "custom-http-server": {
    "type": "http",
    "url": "http://localhost:3001/mcp",
    "headers": {
      "Authorization": "Bearer ${CUSTOM_SERVER_TOKEN}"
    },
    "description": "Custom MCP server via HTTP",
    "enabled": true
  }
}
```

## Project Structure

```
c:\ai\claude\
├── app/
│   ├── main.py                  # FastAPI application
│   ├── api/                     # API routes and middleware
│   ├── core/                    # Core business logic
│   │   ├── api_key_manager.py   # API key management
│   │   ├── database_manager.py  # DB connection (MySQL/PostgreSQL)
│   │   ├── session_manager.py   # Session management (Redis + DB)
│   │   ├── mcp/                 # MCP client
│   │   └── llm/                 # LLM services
│   ├── models/                  # Data models (dataclasses & SQLAlchemy)
│   └── utils/                   # Utilities
├── config/                      # Configuration management
├── scripts/                     # Utility scripts (API key generation)
├── tests/                       # Test suite
├── mcp_servers.json            # MCP server configurations
├── .env.example                # Environment template
└── requirements.txt            # Dependencies
```

## Development

### Run Tests

```bash
pytest
pytest --cov=app --cov-report=html
```

### Code Quality

```bash
# Lint and format
ruff check . --fix
ruff format .

# Type checking
mypy app/
```

## Documentation

For detailed documentation, see [CLAUDE.md](CLAUDE.md)

Topics covered:

- Architecture overview
- Installation & setup
- API usage examples
- MCP server configuration
- Development workflow
- Troubleshooting
- Deployment guide

## Tech Stack

- **Framework**: FastAPI 0.115+
- **LLM**: LangChain 0.3+ with Ollama/OpenAI
- **MCP**: LangChain MCP Adapters 0.2+
- **Database**: SQLAlchemy 2.0+ (MySQL/PostgreSQL support)
- **Cache**: Redis (aioredis)
- **Python**: 3.11+
- **Validation**: Pydantic 2.10+
- **Logging**: Structlog 25.1+

## License

MIT

## Contributing

Contributions welcome! Please read [CLAUDE.md](CLAUDE.md) for development guidelines.

## Support

For issues and questions:

- Check [CLAUDE.md](CLAUDE.md) troubleshooting section
- Review [mcp_servers.json](mcp_servers.json) configuration
- Check Ollama is running: `ollama list`

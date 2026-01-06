# LangChain + Ollama + MCP Client Server

A Python-based LLM server integrating **LangChain**, **Ollama**, and **Model Context Protocol (MCP)** for enhanced AI responses with extensible context sources.

## Features

✅ **LangChain Integration** - Advanced LLM orchestration and chaining
✅ **Ollama Support** - Local LLM execution (llama3.2, llama3.1)
✅ **MCP Client** - Extensible context from multiple sources (SQLite, Web Search, Custom servers)
✅ **FastAPI** - RESTful API with sync and streaming endpoints
✅ **Flexible Configuration** - JSON-based MCP server config with environment variable support
✅ **HTTP & Process MCP Servers** - Support for both process-based and HTTP-based MCP servers

## Quick Start

### 1. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/download) installed
- Node.js (for npx-based MCP servers)

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

### 3. Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your settings (API keys, etc.)
```

### 4. Start Ollama & Pull Models

```bash
ollama pull llama3.2
ollama pull llama3.1
```

### 5. Run the Server

```bash
# Development mode (with auto-reload)
uvicorn app.main:app --reload

# Production mode
uvicorn app.main:app --workers 4
```

Server runs at: `http://localhost:8000`

## API Usage

### Health Check

```bash
curl http://localhost:8000/health
```

### Query (Synchronous)

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
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
  -d '{
    "query": "Explain quantum computing",
    "model": "llama3.2",
    "stream": true
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
│   ├── api/                     # API routes and schemas
│   ├── core/                    # Core business logic
│   └── utils/                   # Utilities
├── config/                      # Configuration management
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
- **LLM**: LangChain 0.3+ with Ollama
- **MCP**: Official MCP Python SDK 1.2+
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

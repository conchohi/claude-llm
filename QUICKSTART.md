# Quick Start Guide

Get your LangChain + Ollama + MCP server running in 5 minutes!

## Prerequisites Check

Before starting, ensure you have:

- ✅ Python 3.11 or higher (`python --version`)
- ✅ Ollama installed ([https://ollama.ai/download](https://ollama.ai/download))
- ✅ Node.js (optional, for npx-based MCP servers)

## Step-by-Step Setup

### 1. Install Ollama and Pull Models

```bash
# Install Ollama first from https://ollama.ai/download
# Then pull the models

ollama pull llama3.2
ollama pull llama3.1

# Verify Ollama is running
ollama list
```

### 2. Create Virtual Environment

```bash
# Navigate to project directory
cd c:\ai\claude

# Create virtual environment
python -m venv venv

# Activate (Windows)
.\venv\Scripts\activate

# Activate (Mac/Linux)
# source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt

# Optional: Install development dependencies
pip install -r requirements-dev.txt
```

### 4. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env file with your settings
# At minimum, verify these settings:
# - OLLAMA_BASE_URL=http://localhost:11434
# - OLLAMA_MODEL=llama3.2
# - MCP_CONFIG_PATH=./mcp_servers.json
```

### 5. Configure MCP Servers

Edit [mcp_servers.json](mcp_servers.json):

- **SQLite** server is enabled by default
- **Brave Search** requires `BRAVE_API_KEY` in `.env`
- **Custom HTTP servers** can be added with `type: "http"`

### 6. Test Ollama Connection

```bash
python scripts/test_ollama.py
```

Expected output:
```
✓ SUCCESS!
Response: <ollama response>
Ollama is working correctly!
```

### 7. Run the Server

```bash
# Development mode (with auto-reload)
uvicorn app.main:app --reload

# Or production mode
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Expected output:
```
Starting application...
✓ Successfully connected to Ollama (model: llama3.2)
Found 2 enabled MCP servers
  ✓ sqlite (process) - running
  ✓ brave-search (process) - running
✓ Application startup complete
API running at http://0.0.0.0:8000
Documentation at http://0.0.0.0:8000/docs
```

### 8. Test the API

Open your browser:
- **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

Or use curl:

```bash
# Health check
curl http://localhost:8000/health

# Simple query
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the capital of France?",
    "model": "llama3.2"
  }'

# Query with MCP context
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the top products?",
    "model": "llama3.2",
    "mcp_servers": ["sqlite"]
  }'
```

## Troubleshooting

### Ollama Connection Failed

```bash
# Check if Ollama is running
ollama list

# Restart Ollama
# Windows: Restart from system tray
# Mac/Linux: brew services restart ollama

# Verify URL
curl http://localhost:11434/api/tags
```

### MCP Server Failed to Start

1. Check [mcp_servers.json](mcp_servers.json) configuration
2. Verify command is in PATH (e.g., `python`, `npx`)
3. Check environment variables are set
4. Review error logs in application output

### Import Errors

```bash
# Reinstall dependencies
pip install --upgrade -r requirements.txt

# Verify Python version
python --version  # Should be 3.11+
```

### Port Already in Use

```bash
# Change port in .env
API_PORT=8001

# Or specify when running
uvicorn app.main:app --port 8001
```

## Next Steps

1. ✅ Read [CLAUDE.md](CLAUDE.md) for detailed documentation
2. ✅ Customize MCP servers in [mcp_servers.json](mcp_servers.json)
3. ✅ Add your API keys to `.env`
4. ✅ Explore API at [http://localhost:8000/docs](http://localhost:8000/docs)
5. ✅ Add custom MCP servers (process or HTTP-based)

## Common Commands

```bash
# Run server
uvicorn app.main:app --reload

# Run tests
pytest

# Format code
ruff format .

# Type check
mypy app/

# Check code quality
ruff check .
```

## Getting Help

- 📖 **Full Documentation**: [CLAUDE.md](CLAUDE.md)
- 🐛 **Issues**: Check application logs
- 💡 **Examples**: See `/docs` endpoint for API examples

## Project Structure

```
c:\ai\claude\
├── app/                    # Application code
│   ├── api/               # API routes and schemas
│   ├── core/              # Business logic
│   ├── models/            # Data models
│   └── utils/             # Utilities
├── config/                # Configuration
├── tests/                 # Test suite
├── scripts/               # Utility scripts
├── .env                   # Environment variables (you create this)
├── mcp_servers.json       # MCP configuration
└── requirements.txt       # Dependencies
```

Happy coding! 🚀

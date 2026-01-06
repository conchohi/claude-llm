# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LangChain + Ollama + MCP Client Server: A Python FastAPI application that combines LangChain for LLM orchestration, Ollama for local LLM execution, and Model Context Protocol (MCP) for extensible context sources. The server processes user queries by gathering context from MCP servers (SQLite, web search, custom HTTP endpoints) and generating AI responses via Ollama.

**Python Version**: 3.11+ (required)

## Development Commands

### Setup
```bash
# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Unix/Mac

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Optional: dev tools

# Configure environment
cp .env.example .env
# Edit .env with your Ollama URL, API keys, etc.
```

### Running the Application
```bash
# Development mode (with auto-reload)
uvicorn app.main:app --reload

# Production mode
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# Custom port
uvicorn app.main:app --port 8001

# Test Ollama connection
python scripts/test_ollama.py
```

### Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_core/test_mcp_client.py -v

# Run single test
pytest tests/test_core/test_mcp_client.py::test_specific_function -v
```

### Code Quality
```bash
# Format code (auto-fix)
ruff format .

# Lint and auto-fix issues
ruff check . --fix

# Type checking
mypy app/

# Run all quality checks
ruff format . && ruff check . && mypy app/
```

## Architecture

### Core Request Flow

1. **Request Entry** → `app/api/routes.py` receives API request
2. **Query Processing** → `app/core/query_processor.py` orchestrates the pipeline
3. **MCP Context Gathering** → `app/core/mcp_client.py` queries MCP servers in parallel
4. **LLM Generation** → `app/core/langchain_service.py` formats prompt with context and calls Ollama
5. **Response** → Structured response with LLM output, MCP context, and metadata

### Key Architectural Patterns

**Dependency Injection via Lifespan**
- Global services (`mcp_client`, `langchain_service`, `query_processor`, `session_manager`) are initialized once during app startup in `app/main.py:lifespan()`
- These are then injected into routes via:
  - `routes.set_query_processor(query_processor)` → Sets global `_query_processor`
  - `routes.set_session_manager(session_manager)` → Sets global `_session_manager`
- Access pattern: Route handlers use FastAPI dependency injection
  - `Depends(get_query_processor)` → Returns singleton or raises HTTP 500 if not initialized
  - `Depends(get_session_manager)` → Returns singleton or raises HTTP 500 if not initialized
  - `Depends(get_current_user)` → Extracts `user_id` from `request.state` or raises HTTP 401
- **Why use getter functions instead of direct access?**
  1. **Consistent error handling**: Returns clear HTTP exceptions if service not initialized
  2. **Testability**: Easy to override with `app.dependency_overrides[get_session_manager] = mock`
  3. **Type safety**: FastAPI validates dependency injection at runtime

**LangChain MCP Integration**
- Uses **LangChain MCP Adapters** (`langchain-mcp-adapters`) for high-level MCP server management
- `MultiServerMCPClient`: Manages multiple MCP servers with unified interface
- **Process-based servers (stdio)**: Launched as subprocesses
  - Config: `{"command": "python", "args": ["-m", "mcp.server.sqlite"], "transport": "stdio"}`
  - Environment variables: `{"env": {...}}`
- **HTTP-based servers**: Connect to already-running HTTP servers
  - Config: `{"url": "http://localhost:3001/mcp", "transport": "http", "headers": {...}}`
- **Tool-based querying**: MCP servers expose tools via LangChain's tool interface
  - Tools loaded using `load_mcp_tools(session)`
  - Invoked via `tool.ainvoke(input)` for async execution
- Unified interface: `MCPClientManager.query_server()` handles both server types transparently

**Configuration Hierarchy**
- `config/settings.py`: Pydantic-based settings with environment variable loading
  - Nested settings classes: `OllamaSettings`, `APISettings`, `MCPSettings`, etc.
  - Each has `env_prefix` for namespaced env vars (e.g., `OLLAMA_BASE_URL`)
  - Singleton pattern via `get_settings()` ensures single instance
- `mcp_servers.json`: MCP server configurations with environment variable substitution
  - Loaded by `app/core/mcp_loader.py`
  - Supports `${VAR_NAME}` syntax for env var substitution
  - Validates server configs and filters enabled servers

**Async/Await Throughout**
- All I/O operations are async (MCP queries, LLM calls, HTTP requests)
- MCP servers queried in parallel via `asyncio.gather()` in `MCPClientManager.get_context()`
- Streaming responses use async generators (`AsyncIterator[str]`)

**Authentication & Session Management**
- **API Key Authentication**: HMAC-signed API keys with SHA-256 hashing
  - Middleware: `app/api/middleware.py:AuthenticationMiddleware`
  - API key format: `{random_token}.{hmac_signature}`
    - `random_token`: 32-byte random token via `secrets.token_urlsafe(32)`
    - `hmac_signature`: HMAC-SHA256 signature using `AUTH_SECRET_KEY`
  - Validation process:
    1. Split key into token + signature
    2. Recompute HMAC signature using `AUTH_SECRET_KEY`
    3. Timing-safe comparison via `hmac.compare_digest()` (prevents timing attacks)
    4. Lookup key hash in Redis
  - Keys stored in Redis with SHA-256 hash: `apikey:{key_hash}`
  - Required fields: `user_id`, `name`, `created_at`, `is_active`, `rate_limit`, `last_used`
  - Exempt paths: `/`, `/health`, `/docs`, `/redoc`, `/openapi.json`
  - Authentication can be disabled via `AUTH_ENABLED=false` in `.env`
  - **CRITICAL**: `AUTH_SECRET_KEY` must be set in production (used for HMAC signing)

- **Session Management**: Redis-based conversation history and caching
  - Manager: `app/core/session_manager.py:SessionManager`
  - Constructor parameters:
    - `redis_url`: Redis connection URL
    - `max_connections`: Connection pool size (default: 10)
    - `session_ttl`: Session expiry in seconds (default: 3600)
    - `cache_ttl`: MCP cache expiry in seconds (default: 300)
    - `secret_key`: HMAC secret for API key signing
  - Sessions auto-created on first query if `user_id` available
  - Conversation history (last 10 messages) included in LLM context
  - Sessions stored as JSON: `session:{session_id}`
  - User session index: `user_sessions:{user_id}` (Redis set)
  - Sessions expire after `REDIS_SESSION_TTL` seconds (default 3600)

- **User Profiles**: Store user preferences (default model, temperature, MCP servers)
  - Stored in Redis: `profile:{user_id}` (hash)
  - Fields: `default_model`, `default_temperature`, `default_max_tokens`, `preferred_mcp_servers`, `metadata`, `created_at`, `updated_at`
  - Loaded automatically by `QueryProcessor` and applied when parameters not explicitly provided
  - Can be updated via `PUT /api/v1/profile`
  - Creates default profile on first access if not exists

- **MCP Caching**: Response caching to reduce redundant queries
  - Cache key: SHA-256 hash of `server_name:query`
  - Stored in Redis: `mcp_cache:{cache_key}`
  - TTL: `REDIS_CACHE_TTL` seconds (default 300)
  - Integrated into `QueryProcessor._gather_mcp_context()`
  - Only successful responses are cached
  - Cache miss → query MCP server → store in cache

- **Request Flow with Auth**:
  1. Request hits `AuthenticationMiddleware` → validates API key (HMAC signature + Redis lookup)
  2. `user_id` stored in `request.state.user_id`
  3. Route handler extracts `user_id` via `Depends(get_current_user)`
  4. `QueryProcessor` loads session and user profile from Redis
  5. Conversation history (last 10 messages) injected into LLM prompt
  6. Response saved to session with MCP context summary (truncated to 200 chars)
  7. Session and profile TTLs refreshed on each access

### Critical Files

**app/main.py**
- FastAPI app creation and lifespan management
- Initializes all services on startup, shuts down MCP servers on exit
- Sets up CORS, exception handlers, includes routes

**app/core/mcp_client.py**
- `MCPClientManager`: Wraps LangChain's `MultiServerMCPClient` for MCP server lifecycle
- `mcp_client`: Instance of `MultiServerMCPClient` from `langchain-mcp-adapters`
- Supports both stdio (process-based) and HTTP transports
- Key methods:
  - `initialize_servers(configs)`: Initializes all MCP servers via `MultiServerMCPClient`
  - `query_server(name, query)`: Queries specific server using LangChain tools
  - `get_context(server_names, query)`: Parallel queries across multiple servers
  - `get_all_tools()`: Returns all available LangChain tools from MCP servers
  - `session(name)`: Context manager for server-specific tool access

**app/core/query_processor.py**
- `QueryProcessor`: Main orchestrator for query processing
- Constructor: `__init__(mcp_client, langchain_service, session_manager)`
- Constants:
  - `MAX_CONVERSATION_HISTORY_MESSAGES = 10`: Max messages included in context
  - `MCP_CONTEXT_PREVIEW_LENGTH = 200`: Max chars for MCP context summary in session
- Key methods:
  - `process_query(query, user_id, session_id, use_conversation_history, mcp_servers, model, temperature, max_tokens)`:
    - Step 0: Session and profile management
      - Gets or creates session if `user_id` provided
      - Loads user profile for defaults (model, temperature, max_tokens, preferred_mcp_servers)
      - Builds conversation history string from last 10 messages
    - Step 1: Gather MCP context with caching via `_gather_mcp_context()`
    - Step 2: Generate LLM response with context and conversation history
      - Enhances query with conversation history prefix
    - Step 3: Save to session (user message + assistant message with MCP context summary)
    - Step 4: Return result with metadata (processing_time, mcp_servers_queried, mcp_servers_successful)
  - `process_streaming_query(...)`: Same as above but streams response chunks
    - Collects full response for session storage after streaming completes
  - `_gather_mcp_context(server_names, query, use_cache)`: Gathers MCP context with caching
    - If `use_cache=False` or no session manager: queries MCP servers directly
    - If `use_cache=True`: checks Redis cache first, queries on cache miss
    - Stores successful responses in cache
  - `_format_mcp_context_for_response(mcp_context)`: Formats MCP responses for JSON API response
  - `health_check()`: Returns health status of Ollama and MCP servers

**app/core/langchain_service.py**
- `LangChainService`: Wraps LangChain + Ollama
- `_format_mcp_context()`: Converts MCP responses to prompt-friendly text
- Uses `ChatPromptTemplate` with context injection
- Supports both sync and streaming generation

**config/settings.py**
- All configuration loaded from environment or `.env` file
- `get_settings()`: Returns singleton Settings instance
- `reset_settings()`: Clears singleton (for testing)

**app/core/session_manager.py**
- `SessionManager`: Redis-based session and auth management
- Constructor: `__init__(redis_url, max_connections, session_ttl, cache_ttl, secret_key)`
- Connection management:
  - `connect()`: Establishes Redis connection pool with `aioredis.from_url()`
  - `disconnect()`: Closes Redis connection via `aioredis.aclose()`
  - `_get_redis()`: Returns Redis client or raises `RuntimeError` if not connected
- API key methods:
  - `generate_api_key()`: Generates secure random token via `secrets.token_urlsafe(32)`
  - `create_api_key(user_id, name, rate_limit)`: Creates HMAC-signed API key
    - Generates `random_token` + HMAC signature using `secret_key`
    - Stores SHA-256 hash in Redis: `apikey:{key_hash}`
    - Returns tuple: `(plain_key, APIKey object)`
  - `validate_api_key(api_key)`: Validates API key
    - Splits key into token + signature
    - Recomputes HMAC and compares via `hmac.compare_digest()`
    - Returns `user_id` if valid, `None` otherwise
    - Updates `last_used` timestamp on successful validation
  - `_hash_api_key(api_key)`: SHA-256 hash for Redis storage
- Session methods:
  - `create_session(user_id)`: Creates new session with random session_id
  - `get_session(session_id)`: Retrieves session from Redis
  - `save_session(session)`: Saves session JSON with TTL, adds to user's session set
  - `get_user_sessions(user_id, limit)`: Returns user's sessions sorted by `updated_at`
  - `delete_session(session_id)`: Deletes session and removes from user's session set
- Profile methods:
  - `get_user_profile(user_id)`: Returns profile or creates default if not exists
  - `update_user_profile(profile)`: Updates profile hash in Redis
- Cache methods:
  - `generate_mcp_cache_key(server_name, query)`: SHA-256 hash of `server_name:query`
  - `get_mcp_cache(cache_key)`: Returns cached MCP response or None
  - `set_mcp_cache(cache_key, data)`: Stores MCP response with TTL

**app/api/middleware.py**
- `AuthenticationMiddleware`: Validates API keys on every request
  - Constructor: `__init__(app, session_manager, auth_enabled, api_key_header)`
  - `EXEMPT_PATHS`: List of paths that don't require auth (/, /health, /docs, /redoc, /openapi.json)
  - `dispatch(request, call_next)`: Main middleware logic
    - Skips authentication if `auth_enabled=False`
    - Skips authentication for exempt paths
    - Extracts API key from header (default: `X-API-Key`)
    - Validates key via `session_manager.validate_api_key()`
    - Sets `request.state.user_id` for authenticated requests
    - Returns HTTP 401 JSON response if key missing/invalid
  - `_is_exempt_path(path)`: Checks if path is exempt (exact match or prefix match)
- `get_current_user(request)`: FastAPI dependency helper
  - Extracts `user_id` from `request.state`
  - Raises `HTTPException(401)` if not authenticated
  - Used in route handlers via `Depends(get_current_user)`

**app/models/auth.py**
- Data models: `APIKey`, `UserProfile`, `ConversationSession`, `ConversationMessage`
- All use `@dataclass` with JSON serialization helpers

## MCP Server Configuration

### Adding a New Process-Based MCP Server (stdio transport)

Edit `mcp_servers.json`:
```json
{
  "my-server": {
    "command": "python",
    "args": ["-m", "my.mcp.server", "--option", "value"],
    "env": {
      "MY_ENV_VAR": "${MY_ENV_VAR}"
    },
    "description": "My custom MCP server",
    "enabled": true
  }
}
```

**How it works:**
- The server is launched as a subprocess via stdio transport
- `MultiServerMCPClient` handles process lifecycle automatically
- Tools exposed by the server become available as LangChain tools
- Environment variable substitution: `${VAR_NAME}` → `os.getenv("VAR_NAME")`

### Adding a New HTTP-Based MCP Server

```json
{
  "my-http-server": {
    "type": "http",
    "url": "http://localhost:3001/mcp",
    "headers": {
      "Authorization": "Bearer ${MY_API_TOKEN}",
      "X-Custom-Header": "value"
    },
    "description": "Already-running HTTP MCP server",
    "enabled": true
  }
}
```

**How it works:**
- Server must already be running on the specified URL
- `MultiServerMCPClient` connects via HTTP transport
- Headers are included in all requests for authentication
- Server must expose tools via MCP HTTP protocol

**Important notes:**
- Both server types expose tools via the same LangChain tool interface
- Tools are automatically loaded and invoked via `tool.ainvoke(input)`
- No manual MCP protocol handling required - LangChain adapters handle everything

## Common Modifications

### Adding a New API Endpoint

1. Define request/response schemas in `app/api/schemas.py`
2. Add route handler in `app/api/routes.py` with `@router.get/post/etc.`
3. Use FastAPI dependency injection to access services:
   - `Depends(get_query_processor)` → Access `QueryProcessor` singleton
   - `Depends(get_session_manager)` → Access `SessionManager` singleton
   - `Depends(get_current_user)` → Extract `user_id` from authenticated request
4. No restart needed in dev mode (auto-reload active)

Example:
```python
@router.get("/api/v1/my-endpoint")
async def my_endpoint(
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    profile = await session_manager.get_user_profile(user_id)
    return {"user_id": user_id, "profile": profile}
```

### Changing LLM Prompt Template

Edit `app/core/langchain_service.py:_create_default_template()`:
```python
template = """Your custom prompt here.

Context: {context_section}
Query: {query}

Response:"""
```

The `{context_section}` placeholder is filled with formatted MCP context.
The `{query}` placeholder is filled with the user's query.

### Adding Custom MCP Context Formatting

Override `app/core/langchain_service.py:_format_mcp_context()` to customize how MCP responses are presented to the LLM.

## Environment Variables

All settings use Pydantic with environment variable support. Key variables:

```bash
# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
OLLAMA_TEMPERATURE=0.7
OLLAMA_MAX_TOKENS=2048

# FastAPI
API_HOST=0.0.0.0
API_PORT=8000
API_RELOAD=true

# MCP
MCP_CONFIG_PATH=./mcp_servers.json
MCP_TIMEOUT=30
MCP_MAX_RETRIES=3

# Redis (Session Management & Caching)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=                    # Optional
REDIS_MAX_CONNECTIONS=10           # Connection pool size
REDIS_SESSION_TTL=3600             # Session expiry in seconds (1 hour)
REDIS_CACHE_TTL=300                # MCP cache expiry in seconds (5 minutes)

# Authentication
AUTH_ENABLED=true                  # Enable/disable API key authentication
AUTH_API_KEY_HEADER=X-API-Key      # Header name for API key
AUTH_SECRET_KEY=your-secret-key-change-in-production  # CRITICAL: HMAC secret for API key signing (MUST change in production!)

# MCP Server Credentials
BRAVE_API_KEY=your_key_here
CUSTOM_SERVER_TOKEN=your_token_here
```

See `.env.example` for full list.

## Authentication & Session Setup

### Setting Up Redis

**Windows**:
```bash
choco install redis-64
```

**Mac**:
```bash
brew install redis
brew services start redis
```

**Linux**:
```bash
sudo apt-get install redis-server
sudo systemctl start redis-server
```

### Creating API Keys

Use the provided script to generate API keys for users:

```bash
# Basic usage
python scripts/create_api_key.py <user_id> <key_name>

# With rate limit
python scripts/create_api_key.py admin "Admin Key" 10000

# Example output:
# ======================================================================
# ✓ API KEY CREATED SUCCESSFULLY
# ======================================================================
# API Key: ak_1234567890abcdef...
# User ID: admin
# Name: Admin Key
# Created: 2025-12-29 10:30:45
# Rate Limit: 10000 requests/hour
# ⚠️  IMPORTANT: Save this API key now - it won't be shown again!
```

### Using API Keys

Include the API key in the `X-API-Key` header for all requests:

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_1234567890abcdef..." \
  -d '{"query": "What is quantum computing?"}'
```

### Session-Based Conversations

The system automatically manages conversation sessions:

```bash
# First query - creates new session
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-key" \
  -d '{"query": "Tell me about Python"}'

# Response includes session_id:
# {"session_id": "sess_abc123...", "response": "...", ...}

# Follow-up query - uses same session for context
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-key" \
  -d '{
    "query": "Can you give me some examples?",
    "session_id": "sess_abc123...",
    "use_conversation_history": true
  }'
```

### Managing User Profiles

User profiles store default settings (model, temperature, preferred MCP servers):

```bash
# Get current profile
curl -X GET http://localhost:8000/api/v1/profile \
  -H "X-API-Key: your-key"

# Update profile
curl -X PUT http://localhost:8000/api/v1/profile \
  -H "X-API-Key: your-key" \
  -d '{
    "default_model": "llama3.1",
    "default_temperature": 0.8,
    "preferred_mcp_servers": ["sqlite", "brave-search"]
  }'
```

### Disabling Authentication (Development)

For local development, you can disable authentication:

```bash
# In .env
AUTH_ENABLED=false
```

Note: Authentication middleware will still be initialized but will pass all requests through.

## Debugging

### Application Startup Failures

Check startup logs for:
- Ollama connection status (should see "✓ Successfully connected to Ollama")
- MCP server initialization (each server shows "✓ running" or "✗ failed")

Common issues:
- Ollama not running: `ollama list` to verify
- MCP config errors: Check `mcp_servers.json` syntax and paths
- Missing environment variables: Verify `.env` file exists and contains required keys

### MCP Server Issues

**LangChain MCP Adapter Errors:**
- Check that `langchain-mcp-adapters` is installed: `pip list | grep langchain-mcp`
- Verify server configuration format matches LangChain requirements
- Common error: "No tools available" → Server may not be exposing tools correctly

**Process-based servers (stdio transport):**
- Ensure command is in PATH or use absolute path
- Check `env` variables are set correctly in `mcp_servers.json`
- Verify subprocess can be launched: test command manually in terminal
- Check logs for `MultiServerMCPClient` initialization errors
- Troubleshoot: Run server command directly to see if it outputs valid MCP protocol

**HTTP-based servers:**
- Ensure server is running BEFORE starting the application
- Verify server exposes MCP-compatible HTTP endpoints
- Test connection: `curl -X POST http://localhost:3001/mcp/tools`
- Check authentication headers are correct and included in config
- Verify server responds with valid MCP tool schemas

**Tool Invocation Failures:**
- Check tool input format matches tool's expected schema
- Review error messages from `tool.ainvoke()` calls
- Ensure query parameters are correctly formatted
- Some tools may require specific context fields

### Query Processing Failures

The query pipeline gracefully degrades: if some MCP servers fail, the LLM still generates a response with partial context. Check `metadata.mcp_servers_successful` in responses to see which servers provided context.

### Authentication & Session Issues

**Redis Connection Failures**:
```bash
# Check if Redis is running
redis-cli ping
# Should respond with: PONG

# Windows
sc query Redis

# Linux/Mac
systemctl status redis
```

**API Key Authentication Failures**:
- Verify `X-API-Key` header is present in request
- Check API key format: should be `{token}.{signature}`
- Verify `AUTH_SECRET_KEY` matches the key used during creation
- Check Redis for stored key: `redis-cli HGETALL apikey:{key_hash}`
  - Key hash: SHA-256 of full API key (token + signature)
- Ensure `is_active` field is `True`
- Check authentication middleware logs for validation errors
- Common issues:
  - **HMAC signature mismatch**: `AUTH_SECRET_KEY` changed after key creation
  - **Key not found in Redis**: Key expired or was deleted
  - **Invalid format**: Key doesn't contain `.` separator

**Session Not Persisting**:
- Verify Redis connection is active (check startup logs)
- Check session TTL hasn't expired (`REDIS_SESSION_TTL`)
- Verify session_id is being passed in follow-up requests
- Check Redis for session: `redis-cli GET session:{session_id}`

**MCP Cache Not Working**:
- Verify cache is enabled in query processor (`use_cache=True`)
- Check cache TTL settings (`REDIS_CACHE_TTL`)
- Monitor cache hits in logs
- Check Redis for cache keys: `redis-cli KEYS mcp_cache:*`

## Testing Patterns

### Testing with Mock MCP Servers

Use `tests/conftest.py:mock_mcp_config` fixture to create temporary MCP configurations:

```python
def test_my_feature(mock_mcp_config):
    loader = load_mcp_config(mock_mcp_config)
    # ... test with mock config
```

### Async Test Functions

All tests involving async code should use `pytest-asyncio`:

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await my_async_function()
    assert result == expected
```

Configuration in `pyproject.toml` sets `asyncio_mode = "auto"` for automatic async test detection.

## Important Notes

- **No database migrations**: SQLite databases in `data/` are managed by MCP servers, not the application
- **Authentication enabled by default**: API key authentication is ON by default. Disable with `AUTH_ENABLED=false` for development
- **Redis required for sessions**: Session management and caching require Redis. App will start without Redis but authentication will fail
- **API keys are HMAC-signed**: Keys use `{token}.{signature}` format with HMAC-SHA256 signing
  - **CRITICAL**: `AUTH_SECRET_KEY` must be set and kept secret in production
  - Changing `AUTH_SECRET_KEY` invalidates all existing API keys
  - Keys are SHA-256 hashed for storage in Redis
  - Keys only shown once during creation - cannot be recovered
- **Conversation history limit**: Last 10 messages included in context to prevent token overflow
- **MCP responses are cached**: Repeated queries to same server with same input use cached responses (TTL: 5 minutes by default)
  - Cache key: SHA-256 hash of `server_name:query`
  - Only successful responses cached
- **Ollama must be running**: Application starts even if Ollama is unavailable, but queries will fail
- **MCP server failures are graceful**: Failed servers don't crash the app, just reduce available context
- **Settings are singletons**: Use `reset_settings()` in tests to ensure clean state
- **Sessions auto-expire**: Sessions deleted from Redis after `REDIS_SESSION_TTL` seconds of inactivity (default 1 hour)
- **Dependency injection pattern**: Use `Depends(get_service)` instead of direct global access for:
  - Consistent error handling (HTTP exceptions)
  - Easy testing (mocking via `app.dependency_overrides`)
  - Type safety

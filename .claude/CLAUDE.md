# CLAUDE.md

이 파일은 Claude Code (claude.ai/code)가 이 저장소의 코드 작업 시 참고할 가이드를 제공합니다.

## 프로젝트 개요

LangChain + Ollama + MCP 클라이언트 서버: LLM 오케스트레이션을 위한 LangChain, 로컬 LLM 실행을 위한 Ollama, 확장 가능한 컨텍스트 소스를 위한 MCP(Model Context Protocol)를 결합한 Python FastAPI 애플리케이션입니다. 서버는 MCP 서버(SQLite, 웹 검색, 커스텀 HTTP 엔드포인트)에서 컨텍스트를 수집하고 Ollama를 통해 AI 응답을 생성하여 사용자 쿼리를 처리합니다.

**Python 버전**: 3.11+ (필수)

## 개발 명령어

### 설정
```bash
# 가상 환경 생성 및 활성화
python -m venv venv
.\venv\Scripts\activate  # Windows
# source venv/bin/activate  # Unix/Mac

# 의존성 설치
pip install -r requirements.txt
pip install -r requirements-dev.txt  # 선택사항: 개발 도구

# 환경 설정
cp .env.example .env
# Ollama URL, API 키 등으로 .env 편집
```

### 애플리케이션 실행
```bash
# 개발 모드 (자동 리로드)
uvicorn app.main:app --reload

# 프로덕션 모드
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

# 커스텀 포트
uvicorn app.main:app --port 8001

# Ollama 연결 테스트
python scripts/test_ollama.py
```

### 테스트
```bash
# 모든 테스트 실행
pytest

# 커버리지와 함께 실행
pytest --cov=app --cov-report=html

# 특정 테스트 파일 실행
pytest tests/test_core/test_mcp_client.py -v

# 단일 테스트 실행
pytest tests/test_core/test_mcp_client.py::test_specific_function -v
```

### 코드 품질
```bash
# 코드 포맷팅 (자동 수정)
ruff format .

# 린트 및 자동 수정
ruff check . --fix

# 타입 검사
mypy app/

# 모든 품질 검사 실행
ruff format . && ruff check . && mypy app/
```

## 아키텍처

### 핵심 요청 흐름

1. **요청 진입** → `app/api/routes.py`가 API 요청 수신
2. **쿼리 처리** → `app/core/query_processor.py`가 파이프라인 조율
3. **MCP 컨텍스트 수집** → `app/core/mcp_client.py`가 MCP 서버를 병렬로 쿼리
4. **LLM 생성** → `app/core/langchain_service.py`가 컨텍스트와 함께 프롬프트를 포맷하고 Ollama 호출
5. **응답** → LLM 출력, MCP 컨텍스트 및 메타데이터가 포함된 구조화된 응답

### 주요 아키텍처 패턴

**Lifespan을 통한 의존성 주입**
- 전역 서비스(`mcp_client`, `langchain_service`, `query_processor`, `session_manager`)는 `app/main.py:lifespan()`에서 앱 시작 시 한 번 초기화됨
- 이후 다음을 통해 라우트에 주입됨:
  - `routes.set_query_processor(query_processor)` → 전역 `_query_processor` 설정
  - `routes.set_session_manager(session_manager)` → 전역 `_session_manager` 설정
- 접근 패턴: 라우트 핸들러는 FastAPI 의존성 주입 사용
  - `Depends(get_query_processor)` → 싱글톤 반환 또는 초기화되지 않은 경우 HTTP 500 발생
  - `Depends(get_session_manager)` → 싱글톤 반환 또는 초기화되지 않은 경우 HTTP 500 발생
  - `Depends(get_current_user)` → `request.state`에서 `user_id` 추출 또는 HTTP 401 발생
- **직접 접근 대신 getter 함수를 사용하는 이유는?**
  1. **일관된 오류 처리**: 서비스가 초기화되지 않은 경우 명확한 HTTP 예외 반환
  2. **테스트 가능성**: `app.dependency_overrides[get_session_manager] = mock`으로 쉽게 재정의
  3. **타입 안전성**: FastAPI가 런타임에 의존성 주입 검증

**LangChain MCP 통합**
- 고수준 MCP 서버 관리를 위해 **LangChain MCP 어댑터**(`langchain-mcp-adapters`) 사용
- `MultiServerMCPClient`: 통합 인터페이스로 여러 MCP 서버 관리
- **프로세스 기반 서버 (stdio)**: 서브프로세스로 시작
  - 설정: `{"command": "python", "args": ["-m", "mcp.server.sqlite"], "transport": "stdio"}`
  - 환경 변수: `{"env": {...}}`
- **HTTP 기반 서버**: 이미 실행 중인 HTTP 서버에 연결
  - 설정: `{"url": "http://localhost:3001/mcp", "transport": "http", "headers": {...}}`
- **도구 기반 쿼리**: MCP 서버는 LangChain의 도구 인터페이스를 통해 도구 노출
  - `load_mcp_tools(session)`을 사용하여 도구 로드
  - 비동기 실행을 위해 `tool.ainvoke(input)` 호출
- 통합 인터페이스: `MCPClientManager.query_server()`가 두 서버 유형을 투명하게 처리

**설정 계층 구조**
- `config/settings.py`: 환경 변수 로딩을 통한 Pydantic 기반 설정
  - 중첩 설정 클래스: `OllamaSettings`, `APISettings`, `MCPSettings` 등
  - 각각 네임스페이스 환경 변수를 위한 `env_prefix` 보유 (예: `OLLAMA_BASE_URL`)
  - `get_settings()`를 통한 싱글톤 패턴으로 단일 인스턴스 보장
- `mcp_servers.json`: 환경 변수 치환을 지원하는 MCP 서버 설정
  - `app/core/mcp_loader.py`에서 로드
  - 환경 변수 치환을 위한 `${VAR_NAME}` 문법 지원
  - 서버 설정 검증 및 활성화된 서버 필터링

**전체적인 Async/Await**
- 모든 I/O 작업은 비동기 (MCP 쿼리, LLM 호출, HTTP 요청)
- `MCPClientManager.get_context()`에서 `asyncio.gather()`를 통해 MCP 서버 병렬 쿼리
- 스트리밍 응답은 비동기 제너레이터(`AsyncIterator[str]`) 사용

**인증 및 세션 관리**
- **API 키 인증**: SHA-256 해싱을 사용한 HMAC 서명 API 키
  - 미들웨어: `app/api/middleware.py:AuthenticationMiddleware`
  - API 키 형식: `{random_token}.{hmac_signature}`
    - `random_token`: `secrets.token_urlsafe(32)`를 통한 32바이트 랜덤 토큰
    - `hmac_signature`: `AUTH_SECRET_KEY`를 사용한 HMAC-SHA256 서명
  - 검증 프로세스:
    1. 키를 토큰 + 서명으로 분할
    2. `AUTH_SECRET_KEY`를 사용하여 HMAC 서명 재계산
    3. `hmac.compare_digest()`를 통한 타이밍 안전 비교 (타이밍 공격 방지)
    4. Redis에서 키 해시 조회
  - 키는 SHA-256 해시와 함께 Redis에 저장: `apikey:{key_hash}`
  - 필수 필드: `user_id`, `name`, `created_at`, `is_active`, `rate_limit`, `last_used`
  - 제외 경로: `/`, `/health`, `/docs`, `/redoc`, `/openapi.json`
  - `.env`에서 `AUTH_ENABLED=false`를 통해 인증 비활성화 가능
  - **중요**: 프로덕션에서는 `AUTH_SECRET_KEY`를 반드시 설정해야 함 (HMAC 서명에 사용)

- **세션 관리**: Redis 기반 대화 기록 및 캐싱
  - 관리자: `app/core/session_manager.py:SessionManager`
  - 생성자 매개변수:
    - `redis_url`: Redis 연결 URL
    - `max_connections`: 연결 풀 크기 (기본값: 10)
    - `session_ttl`: 세션 만료 시간(초) (기본값: 3600)
    - `cache_ttl`: MCP 캐시 만료 시간(초) (기본값: 300)
    - `secret_key`: API 키 서명을 위한 HMAC 비밀키
  - `user_id`가 있는 경우 첫 쿼리 시 세션 자동 생성
  - 대화 기록(최근 10개 메시지)이 LLM 컨텍스트에 포함
  - 세션은 JSON으로 저장: `session:{session_id}`
  - 사용자 세션 인덱스: `user_sessions:{user_id}` (Redis 세트)
  - 세션은 `REDIS_SESSION_TTL` 초 후 만료 (기본값 3600)

- **사용자 프로필**: 사용자 선호 설정 저장 (기본 모델, 온도, MCP 서버)
  - Redis에 저장: `profile:{user_id}` (해시)
  - 필드: `default_model`, `default_temperature`, `default_max_tokens`, `preferred_mcp_servers`, `metadata`, `created_at`, `updated_at`
  - `QueryProcessor`에서 자동으로 로드되고 매개변수가 명시적으로 제공되지 않은 경우 적용
  - `PUT /api/v1/profile`을 통해 업데이트 가능
  - 첫 접근 시 존재하지 않으면 기본 프로필 생성

- **MCP 캐싱**: 중복 쿼리를 줄이기 위한 응답 캐싱
  - 캐시 키: `server_name:query`의 SHA-256 해시
  - Redis에 저장: `mcp_cache:{cache_key}`
  - TTL: `REDIS_CACHE_TTL` 초 (기본값 300)
  - `QueryProcessor._gather_mcp_context()`에 통합
  - 성공적인 응답만 캐시됨
  - 캐시 미스 → MCP 서버 쿼리 → 캐시에 저장

- **인증을 통한 요청 흐름**:
  1. 요청이 `AuthenticationMiddleware`에 도달 → API 키 검증 (HMAC 서명 + Redis 조회)
  2. `user_id`가 `request.state.user_id`에 저장
  3. 라우트 핸들러가 `Depends(get_current_user)`를 통해 `user_id` 추출
  4. `QueryProcessor`가 Redis에서 세션 및 사용자 프로필 로드
  5. 대화 기록(최근 10개 메시지)이 LLM 프롬프트에 주입
  6. MCP 컨텍스트 요약(200자로 잘림)과 함께 응답이 세션에 저장
  7. 각 접근 시 세션 및 프로필 TTL 갱신

### 주요 파일

**app/main.py**
- FastAPI 앱 생성 및 라이프스팬 관리
- 시작 시 모든 서비스 초기화, 종료 시 MCP 서버 종료
- CORS, 예외 핸들러 설정, 라우트 포함

**app/core/mcp_client.py**
- `MCPClientManager`: MCP 서버 라이프사이클을 위한 LangChain의 `MultiServerMCPClient` 래핑
- `mcp_client`: `langchain-mcp-adapters`의 `MultiServerMCPClient` 인스턴스
- stdio (프로세스 기반) 및 HTTP 전송 모두 지원
- 주요 메서드:
  - `initialize_servers(configs)`: `MultiServerMCPClient`를 통해 모든 MCP 서버 초기화
  - `query_server(name, query)`: LangChain 도구를 사용하여 특정 서버 쿼리
  - `get_context(server_names, query)`: 여러 서버에 대한 병렬 쿼리
  - `get_all_tools()`: MCP 서버에서 사용 가능한 모든 LangChain 도구 반환
  - `session(name)`: 서버별 도구 접근을 위한 컨텍스트 관리자

**app/core/query_processor.py**
- `QueryProcessor`: 쿼리 처리를 위한 주요 오케스트레이터
- 생성자: `__init__(mcp_client, langchain_service, session_manager)`
- 상수:
  - `MAX_CONVERSATION_HISTORY_MESSAGES = 10`: 컨텍스트에 포함된 최대 메시지 수
  - `MCP_CONTEXT_PREVIEW_LENGTH = 200`: 세션의 MCP 컨텍스트 요약 최대 문자 수
- 주요 메서드:
  - `process_query(query, user_id, session_id, use_conversation_history, mcp_servers, model, temperature, max_tokens)`:
    - 단계 0: 세션 및 프로필 관리
      - `user_id`가 제공된 경우 세션 가져오기 또는 생성
      - 기본값(모델, 온도, max_tokens, preferred_mcp_servers)을 위해 사용자 프로필 로드
      - 최근 10개 메시지에서 대화 기록 문자열 구축
    - 단계 1: `_gather_mcp_context()`를 통한 캐싱과 함께 MCP 컨텍스트 수집
    - 단계 2: 컨텍스트 및 대화 기록과 함께 LLM 응답 생성
      - 대화 기록 접두사로 쿼리 향상
    - 단계 3: 세션에 저장 (사용자 메시지 + MCP 컨텍스트 요약이 포함된 어시스턴트 메시지)
    - 단계 4: 메타데이터(processing_time, mcp_servers_queried, mcp_servers_successful)와 함께 결과 반환
  - `process_streaming_query(...)`: 위와 동일하지만 응답 청크를 스트리밍
    - 스트리밍 완료 후 세션 저장을 위해 전체 응답 수집
  - `_gather_mcp_context(server_names, query, use_cache)`: 캐싱과 함께 MCP 컨텍스트 수집
    - `use_cache=False` 또는 세션 관리자가 없는 경우: MCP 서버를 직접 쿼리
    - `use_cache=True`인 경우: 먼저 Redis 캐시 확인, 캐시 미스 시 쿼리
    - 성공적인 응답을 캐시에 저장
  - `_format_mcp_context_for_response(mcp_context)`: JSON API 응답을 위해 MCP 응답 포맷팅
  - `health_check()`: Ollama 및 MCP 서버의 상태 반환

**app/core/langchain_service.py**
- `LangChainService`: LangChain + Ollama 래핑
- `_format_mcp_context()`: MCP 응답을 프롬프트 친화적 텍스트로 변환
- 컨텍스트 주입이 있는 `ChatPromptTemplate` 사용
- 동기 및 스트리밍 생성 모두 지원

**config/settings.py**
- 환경 또는 `.env` 파일에서 로드된 모든 설정
- `get_settings()`: 싱글톤 Settings 인스턴스 반환
- `reset_settings()`: 싱글톤 지우기 (테스트용)

**app/core/session_manager.py**
- `SessionManager`: Redis 기반 세션 및 인증 관리
- 생성자: `__init__(redis_url, max_connections, session_ttl, cache_ttl, secret_key)`
- 연결 관리:
  - `connect()`: `aioredis.from_url()`로 Redis 연결 풀 설정
  - `disconnect()`: `aioredis.aclose()`를 통해 Redis 연결 종료
  - `_get_redis()`: Redis 클라이언트 반환 또는 연결되지 않은 경우 `RuntimeError` 발생
- API 키 메서드:
  - `generate_api_key()`: `secrets.token_urlsafe(32)`를 통해 보안 랜덤 토큰 생성
  - `create_api_key(user_id, name, rate_limit)`: HMAC 서명된 API 키 생성
    - `random_token` + `secret_key`를 사용한 HMAC 서명 생성
    - SHA-256 해시를 Redis에 저장: `apikey:{key_hash}`
    - 튜플 반환: `(plain_key, APIKey 객체)`
  - `validate_api_key(api_key)`: API 키 검증
    - 키를 토큰 + 서명으로 분할
    - HMAC을 재계산하고 `hmac.compare_digest()`를 통해 비교
    - 유효한 경우 `user_id` 반환, 그렇지 않으면 `None`
    - 성공적인 검증 시 `last_used` 타임스탬프 업데이트
  - `_hash_api_key(api_key)`: Redis 저장을 위한 SHA-256 해시
- 세션 메서드:
  - `create_session(user_id)`: 랜덤 session_id로 새 세션 생성
  - `get_session(session_id)`: Redis에서 세션 검색
  - `save_session(session)`: TTL과 함께 세션 JSON 저장, 사용자의 세션 세트에 추가
  - `get_user_sessions(user_id, limit)`: `updated_at`으로 정렬된 사용자의 세션 반환
  - `delete_session(session_id)`: 세션 삭제 및 사용자의 세션 세트에서 제거
- 프로필 메서드:
  - `get_user_profile(user_id)`: 프로필 반환 또는 존재하지 않으면 기본값 생성
  - `update_user_profile(profile)`: Redis의 프로필 해시 업데이트
- 캐시 메서드:
  - `generate_mcp_cache_key(server_name, query)`: `server_name:query`의 SHA-256 해시
  - `get_mcp_cache(cache_key)`: 캐시된 MCP 응답 또는 None 반환
  - `set_mcp_cache(cache_key, data)`: TTL과 함께 MCP 응답 저장

**app/api/middleware.py**
- `AuthenticationMiddleware`: 모든 요청에 대해 API 키 검증
  - 생성자: `__init__(app, session_manager, auth_enabled, api_key_header)`
  - `EXEMPT_PATHS`: 인증이 필요하지 않은 경로 목록 (/, /health, /docs, /redoc, /openapi.json)
  - `dispatch(request, call_next)`: 주요 미들웨어 로직
    - `auth_enabled=False`인 경우 인증 건너뛰기
    - 제외 경로에 대한 인증 건너뛰기
    - 헤더에서 API 키 추출 (기본값: `X-API-Key`)
    - `session_manager.validate_api_key()`를 통해 키 검증
    - 인증된 요청에 대해 `request.state.user_id` 설정
    - 키가 누락/유효하지 않은 경우 HTTP 401 JSON 응답 반환
  - `_is_exempt_path(path)`: 경로가 제외되는지 확인 (정확한 일치 또는 접두사 일치)
- `get_current_user(request)`: FastAPI 의존성 헬퍼
  - `request.state`에서 `user_id` 추출
  - 인증되지 않은 경우 `HTTPException(401)` 발생
  - `Depends(get_current_user)`를 통해 라우트 핸들러에서 사용

**app/models/auth.py**
- 데이터 모델: `APIKey`, `UserProfile`, `ConversationSession`, `ConversationMessage`
- 모두 JSON 직렬화 헬퍼와 함께 `@dataclass` 사용

## MCP 서버 설정

### 새로운 프로세스 기반 MCP 서버 추가 (stdio 전송)

`mcp_servers.json` 편집:
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

**작동 방식:**
- 서버는 stdio 전송을 통해 서브프로세스로 시작됨
- `MultiServerMCPClient`가 프로세스 라이프사이클을 자동으로 처리
- 서버에서 노출된 도구는 LangChain 도구로 사용 가능해짐
- 환경 변수 치환: `${VAR_NAME}` → `os.getenv("VAR_NAME")`

### 새로운 HTTP 기반 MCP 서버 추가

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

**작동 방식:**
- 서버는 이미 지정된 URL에서 실행 중이어야 함
- `MultiServerMCPClient`가 HTTP 전송을 통해 연결
- 인증을 위해 모든 요청에 헤더 포함
- 서버는 MCP HTTP 프로토콜을 통해 도구를 노출해야 함

**중요 참고사항:**
- 두 서버 유형 모두 동일한 LangChain 도구 인터페이스를 통해 도구 노출
- 도구는 자동으로 로드되고 `tool.ainvoke(input)`를 통해 호출됨
- 수동 MCP 프로토콜 처리 불필요 - LangChain 어댑터가 모든 것을 처리

## 일반적인 수정 사항

### 새 API 엔드포인트 추가

1. `app/api/schemas.py`에서 요청/응답 스키마 정의
2. `@router.get/post/etc.`를 사용하여 `app/api/routes.py`에 라우트 핸들러 추가
3. FastAPI 의존성 주입을 사용하여 서비스 액세스:
   - `Depends(get_query_processor)` → `QueryProcessor` 싱글톤 액세스
   - `Depends(get_session_manager)` → `SessionManager` 싱글톤 액세스
   - `Depends(get_current_user)` → 인증된 요청에서 `user_id` 추출
4. 개발 모드에서는 재시작 불필요 (자동 리로드 활성화)

예제:
```python
@router.get("/api/v1/my-endpoint")
async def my_endpoint(
    user_id: str = Depends(get_current_user),
    session_manager: SessionManager = Depends(get_session_manager),
):
    profile = await session_manager.get_user_profile(user_id)
    return {"user_id": user_id, "profile": profile}
```

### LLM 프롬프트 템플릿 변경

`app/core/langchain_service.py:_create_default_template()` 편집:
```python
template = """여기에 커스텀 프롬프트 작성.

컨텍스트: {context_section}
쿼리: {query}

응답:"""
```

`{context_section}` 플레이스홀더는 포맷된 MCP 컨텍스트로 채워집니다.
`{query}` 플레이스홀더는 사용자의 쿼리로 채워집니다.

### 커스텀 MCP 컨텍스트 포맷팅 추가

`app/core/langchain_service.py:_format_mcp_context()`를 재정의하여 MCP 응답이 LLM에 표시되는 방식을 커스터마이즈합니다.

## 환경 변수

모든 설정은 환경 변수 지원과 함께 Pydantic을 사용합니다. 주요 변수:

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

# Redis (세션 관리 및 캐싱)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=                    # 선택사항
REDIS_MAX_CONNECTIONS=10           # 연결 풀 크기
REDIS_SESSION_TTL=3600             # 세션 만료 시간(초) (1시간)
REDIS_CACHE_TTL=300                # MCP 캐시 만료 시간(초) (5분)

# 인증
AUTH_ENABLED=true                  # API 키 인증 활성화/비활성화
AUTH_API_KEY_HEADER=X-API-Key      # API 키 헤더 이름
AUTH_SECRET_KEY=your-secret-key-change-in-production  # 중요: API 키 서명을 위한 HMAC 비밀키 (프로덕션에서 반드시 변경!)

# MCP 서버 자격 증명
BRAVE_API_KEY=your_key_here
CUSTOM_SERVER_TOKEN=your_token_here
```

전체 목록은 `.env.example`을 참조하세요.

## 인증 및 세션 설정

### Redis 설정

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

### API 키 생성

제공된 스크립트를 사용하여 사용자를 위한 API 키 생성:

```bash
# 기본 사용법
python scripts/create_api_key.py <user_id> <key_name>

# 속도 제한 포함
python scripts/create_api_key.py admin "Admin Key" 10000

# 예제 출력:
# ======================================================================
# ✓ API 키가 성공적으로 생성되었습니다
# ======================================================================
# API Key: ak_1234567890abcdef...
# User ID: admin
# Name: Admin Key
# Created: 2025-12-29 10:30:45
# Rate Limit: 10000 requests/hour
# ⚠️  중요: 이 API 키를 지금 저장하세요 - 다시 표시되지 않습니다!
```

### API 키 사용

모든 요청에 대해 `X-API-Key` 헤더에 API 키를 포함:

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_1234567890abcdef..." \
  -d '{"query": "양자 컴퓨팅이란 무엇인가요?"}'
```

### 세션 기반 대화

시스템은 대화 세션을 자동으로 관리합니다:

```bash
# 첫 번째 쿼리 - 새 세션 생성
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-key" \
  -d '{"query": "Python에 대해 알려주세요"}'

# 응답에 session_id 포함:
# {"session_id": "sess_abc123...", "response": "...", ...}

# 후속 쿼리 - 컨텍스트를 위해 동일한 세션 사용
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-key" \
  -d '{
    "query": "몇 가지 예제를 알려주실 수 있나요?",
    "session_id": "sess_abc123...",
    "use_conversation_history": true
  }'
```

### 사용자 프로필 관리

사용자 프로필은 기본 설정(모델, 온도, 선호 MCP 서버)을 저장합니다:

```bash
# 현재 프로필 가져오기
curl -X GET http://localhost:8000/api/v1/profile \
  -H "X-API-Key: your-key"

# 프로필 업데이트
curl -X PUT http://localhost:8000/api/v1/profile \
  -H "X-API-Key: your-key" \
  -d '{
    "default_model": "llama3.1",
    "default_temperature": 0.8,
    "preferred_mcp_servers": ["sqlite", "brave-search"]
  }'
```

### 인증 비활성화 (개발)

로컬 개발의 경우 인증을 비활성화할 수 있습니다:

```bash
# .env에서
AUTH_ENABLED=false
```

참고: 인증 미들웨어는 여전히 초기화되지만 모든 요청을 통과시킵니다.

## 디버깅

### 애플리케이션 시작 실패

다음에 대한 시작 로그 확인:
- Ollama 연결 상태 ("✓ Ollama에 성공적으로 연결됨"이 표시되어야 함)
- MCP 서버 초기화 (각 서버는 "✓ 실행 중" 또는 "✗ 실패" 표시)

일반적인 문제:
- Ollama가 실행 중이지 않음: `ollama list`로 확인
- MCP 설정 오류: `mcp_servers.json` 구문 및 경로 확인
- 누락된 환경 변수: `.env` 파일이 존재하고 필수 키가 포함되어 있는지 확인

### MCP 서버 문제

**LangChain MCP 어댑터 오류:**
- `langchain-mcp-adapters`가 설치되었는지 확인: `pip list | grep langchain-mcp`
- 서버 설정 형식이 LangChain 요구 사항과 일치하는지 확인
- 일반적인 오류: "사용 가능한 도구 없음" → 서버가 도구를 올바르게 노출하지 않을 수 있음

**프로세스 기반 서버 (stdio 전송):**
- 명령이 PATH에 있거나 절대 경로를 사용하는지 확인
- `mcp_servers.json`에서 `env` 변수가 올바르게 설정되었는지 확인
- 서브프로세스를 시작할 수 있는지 확인: 터미널에서 명령 수동 테스트
- `MultiServerMCPClient` 초기화 오류에 대한 로그 확인
- 문제 해결: 유효한 MCP 프로토콜을 출력하는지 확인하기 위해 서버 명령을 직접 실행

**HTTP 기반 서버:**
- 애플리케이션을 시작하기 전에 서버가 실행 중인지 확인
- 서버가 MCP 호환 HTTP 엔드포인트를 노출하는지 확인
- 연결 테스트: `curl -X POST http://localhost:3001/mcp/tools`
- 인증 헤더가 올바르고 설정에 포함되어 있는지 확인
- 서버가 유효한 MCP 도구 스키마로 응답하는지 확인

**도구 호출 실패:**
- 도구 입력 형식이 도구의 예상 스키마와 일치하는지 확인
- `tool.ainvoke()` 호출의 오류 메시지 검토
- 쿼리 매개변수가 올바르게 포맷되었는지 확인
- 일부 도구는 특정 컨텍스트 필드가 필요할 수 있음

### 쿼리 처리 실패

쿼리 파이프라인은 우아하게 저하됩니다: 일부 MCP 서버가 실패하더라도 LLM은 부분 컨텍스트로 응답을 생성합니다. 응답에서 `metadata.mcp_servers_successful`을 확인하여 어떤 서버가 컨텍스트를 제공했는지 확인합니다.

### 인증 및 세션 문제

**Redis 연결 실패**:
```bash
# Redis가 실행 중인지 확인
redis-cli ping
# 응답: PONG

# Windows
sc query Redis

# Linux/Mac
systemctl status redis
```

**API 키 인증 실패**:
- 요청에 `X-API-Key` 헤더가 있는지 확인
- API 키 형식 확인: `{token}.{signature}` 형식이어야 함
- `AUTH_SECRET_KEY`가 생성 시 사용된 키와 일치하는지 확인
- Redis에 저장된 키 확인: `redis-cli HGETALL apikey:{key_hash}`
  - 키 해시: 전체 API 키의 SHA-256 (토큰 + 서명)
- `is_active` 필드가 `True`인지 확인
- 검증 오류에 대한 인증 미들웨어 로그 확인
- 일반적인 문제:
  - **HMAC 서명 불일치**: 키 생성 후 `AUTH_SECRET_KEY` 변경됨
  - **Redis에서 키를 찾을 수 없음**: 키가 만료되었거나 삭제됨
  - **유효하지 않은 형식**: 키에 `.` 구분자가 없음

**세션이 유지되지 않음**:
- Redis 연결이 활성 상태인지 확인 (시작 로그 확인)
- 세션 TTL이 만료되지 않았는지 확인 (`REDIS_SESSION_TTL`)
- session_id가 후속 요청에서 전달되는지 확인
- Redis에서 세션 확인: `redis-cli GET session:{session_id}`

**MCP 캐시가 작동하지 않음**:
- 쿼리 프로세서에서 캐시가 활성화되었는지 확인 (`use_cache=True`)
- 캐시 TTL 설정 확인 (`REDIS_CACHE_TTL`)
- 로그에서 캐시 히트 모니터링
- Redis에서 캐시 키 확인: `redis-cli KEYS mcp_cache:*`

## 테스트 패턴

### 모의 MCP 서버로 테스트

`tests/conftest.py:mock_mcp_config` 픽스처를 사용하여 임시 MCP 설정 생성:

```python
def test_my_feature(mock_mcp_config):
    loader = load_mcp_config(mock_mcp_config)
    # ... 모의 설정으로 테스트
```

### 비동기 테스트 함수

비동기 코드와 관련된 모든 테스트는 `pytest-asyncio`를 사용해야 합니다:

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await my_async_function()
    assert result == expected
```

`pyproject.toml`의 설정은 자동 비동기 테스트 감지를 위해 `asyncio_mode = "auto"`를 설정합니다.

## 중요 참고사항

- **데이터베이스 마이그레이션 없음**: `data/`의 SQLite 데이터베이스는 애플리케이션이 아닌 MCP 서버에서 관리됨
- **기본적으로 인증 활성화**: API 키 인증은 기본적으로 활성화됨. 개발 시 `AUTH_ENABLED=false`로 비활성화
- **세션에는 Redis 필요**: 세션 관리 및 캐싱에는 Redis가 필요함. Redis 없이 앱이 시작되지만 인증이 실패함
- **API 키는 HMAC 서명됨**: 키는 HMAC-SHA256 서명을 사용한 `{token}.{signature}` 형식 사용
  - **중요**: 프로덕션에서는 `AUTH_SECRET_KEY`를 반드시 설정하고 비밀로 유지해야 함
  - `AUTH_SECRET_KEY` 변경은 기존의 모든 API 키를 무효화함
  - 키는 Redis 저장을 위해 SHA-256으로 해시됨
  - 키는 생성 시 한 번만 표시됨 - 복구 불가능
- **대화 기록 제한**: 토큰 오버플로를 방지하기 위해 최근 10개 메시지가 컨텍스트에 포함됨
- **MCP 응답이 캐시됨**: 동일한 입력으로 동일한 서버에 대한 반복 쿼리는 캐시된 응답 사용 (기본 TTL: 5분)
  - 캐시 키: `server_name:query`의 SHA-256 해시
  - 성공적인 응답만 캐시됨
- **Ollama가 실행 중이어야 함**: Ollama를 사용할 수 없어도 애플리케이션이 시작되지만 쿼리가 실패함
- **MCP 서버 실패는 우아함**: 실패한 서버는 앱을 충돌시키지 않고 사용 가능한 컨텍스트만 줄임
- **설정은 싱글톤**: 테스트에서 `reset_settings()`를 사용하여 깨끗한 상태 보장
- **세션 자동 만료**: 비활성 상태 `REDIS_SESSION_TTL` 초 후 Redis에서 세션 삭제 (기본값 1시간)
- **의존성 주입 패턴**: 다음을 위해 직접 전역 액세스 대신 `Depends(get_service)` 사용:
  - 일관된 오류 처리 (HTTP 예외)
  - 쉬운 테스트 (`app.dependency_overrides`를 통한 모킹)
  - 타입 안전성

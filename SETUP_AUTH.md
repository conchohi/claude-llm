# Authentication & Session Management Setup Guide

## 개요

API Key 인증과 Redis 기반 세션 관리가 추가되었습니다. 주요 기능:

✅ **API Key 인증** - 모든 API 요청에 대한 인증 미들웨어
✅ **대화 이력 저장** - Redis에 사용자별 대화 세션 저장
✅ **MCP 컨텍스트 캐싱** - 반복 쿼리 시 MCP 응답 캐싱으로 성능 향상

## 설치 및 설정

### 1. Redis 설치

#### Windows

```bash
# Chocolatey 사용
choco install redis-64

# 또는 Redis for Windows 다운로드
# https://github.com/microsoftarchive/redis/releases
```

#### Mac/Linux

```bash
# Mac (Homebrew)
brew install redis
brew services start redis

# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis-server

# CentOS/RHEL
sudo yum install redis
sudo systemctl start redis
```

### 2. Python 의존성 설치

```bash
pip install -r requirements.txt
```

새로 추가된 패키지:

- `redis==5.2.1` - Redis 비동기 클라이언트
- `python-jose[cryptography]==3.3.0` - JWT 토큰 지원
- `passlib[bcrypt]==1.7.4` - 비밀번호 해싱

### 3. 환경 변수 설정

`.env` 파일에 다음 설정 추가:

```env
# Redis Configuration
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=
REDIS_SESSION_TTL=3600        # 세션 TTL (초) - 1시간

# Authentication Configuration
AUTH_ENABLED=true
AUTH_API_KEY_HEADER=X-API-Key
AUTH_SECRET_KEY=your-secret-key-change-in-production-use-strong-random-key
```

**중요**: 프로덕션 환경에서는 `AUTH_SECRET_KEY`를 강력한 랜덤 키로 변경하세요!

```python
# 강력한 시크릿 키 생성
import secrets
print(secrets.token_urlsafe(32))
```

## 구현된 기능

### 1. API Key 인증 시스템

#### 미들웨어 (`app/api/middleware.py`)

- 모든 API 요청에서 `X-API-Key` 헤더 검증
- 면제 경로: `/`, `/health`, `/docs`, `/redoc`
- 유효한 API 키 → `request.state.user_id`에 사용자 ID 저장

#### API Key 관리

```python
# SessionManager를 통한 API Key 생성
plain_key, api_key_obj = await session_manager.create_api_key(
    user_id="user123",
    name="My Application",
    rate_limit=1000  # 선택적: 시간당 요청 제한
)

# API Key 검증
user_id = await session_manager.validate_api_key(api_key)
```

### 2. 세션 관리 (`app/core/session_manager.py`)

#### 대화 세션 생성 및 관리

```python
# 새 세션 생성
session = await session_manager.create_session(user_id="user123")

# 메시지 추가
session.add_message(
    role="user",
    content="Hello, how are you?"
)

session.add_message(
    role="assistant",
    content="I'm doing great!",
    mcp_context={"sqlite": {...}}
)

# 세션 저장
await session_manager.save_session(session)

# 세션 조회
session = await session_manager.get_session(session_id)

# 사용자의 모든 세션 조회
sessions = await session_manager.get_user_sessions(user_id, limit=20)
```

## API 사용법

### 인증 헤더 추가

모든 API 요청에 `X-API-Key` 헤더 포함:

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key-here" \
  -d '{
    "query": "What are the top products?",
    "session_id": "optional-session-id",
    "use_conversation_history": true
  }'
```

### 세션 기반 대화

```bash
# 1. 첫 번째 쿼리 (새 세션 자동 생성)
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Tell me about quantum computing"
  }'

# 응답에서 session_id 획득
# Response: { "session_id": "abc123", ... }

# 2. 후속 쿼리 (같은 세션 ID 사용)
curl -X POST http://localhost:8000/api/v1/query \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Can you explain it in simpler terms?",
    "session_id": "abc123",
    "use_conversation_history": true
  }'
```

### QueryRequest 스키마 변경사항

```python
class QueryRequest(BaseModel):
    query: str  # 필수
    session_id: Optional[str] = None  # 세션 ID (선택)
    stream: bool = False
    use_conversation_history: bool = True  # 대화 이력 포함 여부
```

## Redis 데이터 구조

### Keys

```
apikey:{key_hash}           → Hash: API 키 정보
session:{session_id}        → String (JSON): 대화 세션
user_sessions:{user_id}     → Set: 사용자의 세션 ID 목록
```

### TTL (Time To Live)

- **세션**: `REDIS_SESSION_TTL` (기본 3600초 = 1시간)
- **API 키**: 영구 저장 (TTL 없음)

## 다음 단계

현재 구현된 기능:

- ✅ Redis 연결 및 세션 관리자
- ✅ API Key 인증 미들웨어
- ✅ 대화 이력 관리
- ✅ MCP 컨텍스트 캐싱
- ✅ 새로운 API 스키마

아직 구현 필요:

- ⏳ `app/main.py`에 SessionManager 통합
- ⏳ `app/api/routes.py`에 인증 미들웨어 적용
- ⏳ 세션 기반 쿼리 처리 로직
- ⏳ MCP 캐싱 통합

## 개발 가이드

### API Key 생성 스크립트

```python
# scripts/create_api_key.py
import asyncio
from app.core.session_manager import SessionManager
from config.settings import get_settings

async def main():
    settings = get_settings()
    redis_url = f"redis://{settings.redis.host}:{settings.redis.port}/{settings.redis.db}"

    session_manager = SessionManager(redis_url)
    await session_manager.connect()

    # API Key 생성
    plain_key, api_key = await session_manager.create_api_key(
        user_id="admin",
        name="Admin Key",
        rate_limit=10000
    )

    print(f"API Key: {plain_key}")
    print(f"User ID: {api_key.user_id}")
    print("⚠️  Save this key - it won't be shown again!")

    await session_manager.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

### 인증 비활성화 (개발/테스트용)

`.env`에서:

```env
AUTH_ENABLED=false
```

### Redis 데이터 확인

```bash
# Redis CLI 접속
redis-cli

# 모든 키 조회
KEYS *

# API 키 확인
HGETALL apikey:abc123...

# 세션 확인
GET session:xyz789...

```

## 트러블슈팅

### Redis 연결 실패

```bash
# Redis 실행 확인
redis-cli ping
# 응답: PONG

# Redis 서비스 상태 확인
# Windows
sc query Redis

# Linux/Mac
systemctl status redis
```

### API Key 인증 실패

- `X-API-Key` 헤더가 올바르게 설정되었는지 확인
- API 키가 Redis에 저장되어 있는지 확인: `HGETALL apikey:{hash}`
- 키의 `is_active` 필드가 `True`인지 확인

### 세션 만료

- 세션이 `REDIS_SESSION_TTL` 이후 자동 삭제됨
- 더 긴 세션 유지가 필요하면 `.env`에서 TTL 증가

## 보안 권장사항

1. **프로덕션 환경**:

   - `AUTH_SECRET_KEY`를 강력한 랜덤 값으로 변경
   - Redis에 비밀번호 설정 (`REDIS_PASSWORD`)
   - HTTPS 사용
   - Rate limiting 구현

2. **API Key 관리**:

   - API 키는 평문으로 저장되지 않음 (SHA-256 해시)
   - 키 생성 시 한 번만 평문 반환
   - 정기적인 키 rotation 권장

3. **Redis 보안**:
   - 외부 접근 차단 (방화벽 설정)
   - `redis.conf`에서 `bind 127.0.0.1` 설정
   - `requirepass` 옵션으로 인증 활성화

"""
Script to create an API key for a user.
Usage: python scripts/create_api_key.py <user_id> <key_name> [rate_limit]
"""

import asyncio
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.session_manager import SessionManager
from config.settings import get_settings


async def create_api_key(user_id: str, key_name: str, rate_limit: int | None = None):
    """
    Create an API key for a user.

    Args:
        user_id: User ID to create key for
        key_name: Friendly name for the key
        rate_limit: Optional rate limit (requests per hour)
    """
    settings = get_settings()

    # Build Redis URL
    redis_url = f"redis://"
    if settings.redis.password:
        redis_url += f":{settings.redis.password}@"
    redis_url += f"{settings.redis.host}:{settings.redis.port}/{settings.redis.db}"

    print(f"Connecting to Redis at {settings.redis.host}:{settings.redis.port}...")

    session_manager = SessionManager(
        redis_url=redis_url,
        session_ttl=settings.redis.session_ttl,
        secert_key=settings.auth.secret_key
    )

    try:
        await session_manager.connect()
        print("✓ Connected to Redis\n")

        # Create API key
        print(f"Creating API key for user: {user_id}")
        print(f"Key name: {key_name}")
        if rate_limit:
            print(f"Rate limit: {rate_limit} requests/hour")

        plain_key, api_key = await session_manager.create_api_key(
            user_id=user_id,
            name=key_name,
            rate_limit=rate_limit,
        )

        print("\n" + "=" * 70)
        print("✓ API KEY CREATED SUCCESSFULLY")
        print("=" * 70)
        print(f"\nAPI Key: {plain_key}")
        print(f"User ID: {api_key.user_id}")
        print(f"Name: {api_key.name}")
        print(f"Created: {api_key.created_at}")
        if api_key.rate_limit:
            print(f"Rate Limit: {api_key.rate_limit} requests/hour")
        print("\n⚠️  IMPORTANT: Save this API key now - it won't be shown again!")
        print("=" * 70)

    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
    finally:
        await session_manager.disconnect()
        print("\n✓ Disconnected from Redis")


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python scripts/create_api_key.py <user_id> <key_name> [rate_limit]")
        print("\nExample:")
        print("  python scripts/create_api_key.py admin 'Admin Key' 10000")
        print("  python scripts/create_api_key.py user123 'My App Key'")
        sys.exit(1)

    user_id = sys.argv[1]
    key_name = sys.argv[2]
    rate_limit = int(sys.argv[3]) if len(sys.argv) > 3 else None

    asyncio.run(create_api_key(user_id, key_name, rate_limit))


if __name__ == "__main__":
    main()

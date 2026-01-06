"""
Simple script to test OpenAI connection.
Run this to verify OpenAI API is accessible and working.
"""

import asyncio
import sys
from langchain_openai import ChatOpenAI


async def test_openai_connection(
    api_key: str,
    model: str = "gpt-3.5-turbo",
    base_url: str = "https://api.openai.com/v1",
    organization: str = "",
):
    """
    Test connection to OpenAI server.

    Args:
        api_key: OpenAI API key (required).
        model: Model name to test.
        base_url: OpenAI API base URL.
        organization: Organization ID (optional).
    """
    print(f"Testing OpenAI connection...")
    print(f"  Base URL: {base_url}")
    print(f"  Model: {model}")
    if organization:
        print(f"  Organization: {organization}")
    print()

    try:
        # Create OpenAI client
        openai_kwargs = {
            "model": model,
            "temperature": 0.7,
            "api_key": api_key,
            "base_url": base_url,
        }

        if organization:
            openai_kwargs["organization"] = organization

        llm = ChatOpenAI(**openai_kwargs)

        # Test with a simple query
        print("Sending test query: 'Hello, are you working?'")
        response = await llm.ainvoke("Hello, are you working?")

        print()
        print("✓ SUCCESS!")
        print()
        print(f"Response: {response.content}")
        print()
        print("OpenAI is working correctly!")

        return True

    except Exception as e:
        print()
        print("✗ FAILED!")
        print()
        print(f"Error: {str(e)}")
        print()
        print("Troubleshooting:")
        print("1. Make sure your OpenAI API key is valid")
        print("2. Check that you have sufficient credits in your OpenAI account")
        print("3. Verify the model name is correct (e.g., gpt-3.5-turbo, gpt-4)")
        print("4. Check your internet connection")
        print("5. If using a custom base URL, verify it's accessible")

        return False


async def main():
    """Main entry point."""
    # Parse command line arguments
    if len(sys.argv) < 2:
        print("Usage: python test_openai.py <api_key> [model] [base_url] [organization]")
        print()
        print("Examples:")
        print("  python test_openai.py sk-xxx...")
        print("  python test_openai.py sk-xxx... gpt-4")
        print("  python test_openai.py sk-xxx... gpt-3.5-turbo https://api.openai.com/v1")
        print("  python test_openai.py sk-xxx... gpt-3.5-turbo https://api.openai.com/v1 org-xxx...")
        print()
        print("Or set OPENAI_API_KEY environment variable:")
        print("  export OPENAI_API_KEY=sk-xxx...")
        print("  python test_openai.py")
        sys.exit(1)

    api_key = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else "gpt-3.5-turbo"
    base_url = sys.argv[3] if len(sys.argv) > 3 else "https://api.openai.com/v1"
    organization = sys.argv[4] if len(sys.argv) > 4 else ""

    # Check if API key looks valid
    if not api_key or len(api_key) < 10:
        print("Error: Invalid API key provided")
        print("OpenAI API keys typically start with 'sk-' and are much longer")
        sys.exit(1)

    success = await test_openai_connection(api_key, model, base_url, organization)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())

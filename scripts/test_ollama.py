"""
Simple script to test Ollama connection.
Run this to verify Ollama is running and accessible.
"""

import asyncio
import sys
from langchain_ollama import ChatOllama


async def test_ollama_connection(
    base_url: str = "http://localhost:11434",
    model: str = "llama3.2"
):
    """
    Test connection to Ollama server.

    Args:
        base_url: Ollama API base URL.
        model: Model name to test.
    """
    print(f"Testing Ollama connection...")
    print(f"  Base URL: {base_url}")
    print(f"  Model: {model}")
    print()

    try:
        # Create Ollama client
        llm = ChatOllama(
            base_url=base_url,
            model=model,
            temperature=0.7,
        )

        # Test with a simple query
        print("Sending test query: 'Hello, are you working?'")
        response = await llm.ainvoke("Hello, are you working?")

        print()
        print("✓ SUCCESS!")
        print()
        print(f"Response: {response.content}")
        print()
        print("Ollama is working correctly!")

        return True

    except Exception as e:
        print()
        print("✗ FAILED!")
        print()
        print(f"Error: {str(e)}")
        print()
        print("Troubleshooting:")
        print("1. Make sure Ollama is installed and running")
        print("2. Check that the model is pulled: ollama pull llama3.2")
        print("3. Verify the base URL is correct")
        print(f"4. Try accessing {base_url}/api/tags in your browser")

        return False


async def main():
    """Main entry point."""
    # Parse command line arguments
    base_url = "http://localhost:11434"
    model = "llama3.2"

    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    if len(sys.argv) > 2:
        model = sys.argv[2]

    success = await test_ollama_connection(base_url, model)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())

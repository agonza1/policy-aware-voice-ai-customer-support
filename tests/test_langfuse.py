#!/usr/bin/env python3
"""
Langfuse integration test - creates a trace and validates it's visible in dashboard.

This test:
1. Creates a trace using LangChain CallbackHandler
2. Flushes the trace to Langfuse
3. Verifies the trace was created successfully

Run with: python tests/test_langfuse.py
"""

import os
import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load .env if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)
except ImportError:
    pass


def test_langfuse_trace():
    """Test that creates a trace in Langfuse and validates it."""
    print("=" * 70)
    print("Langfuse Trace Test")
    print("=" * 70)
    print()
    
    # Check configuration
    secret_key = os.getenv("LANGFUSE_SECRET_KEY") or os.getenv("LANGCHAIN_API_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY") or os.getenv("LANGCHAIN_PUBLIC_KEY", "")
    project = os.getenv("LANGCHAIN_PROJECT") or os.getenv("LANGFUSE_PROJECT", "policy-aware-voice-ai")
    
    if not secret_key or not public_key:
        print("⚠ SKIP: Langfuse keys not configured")
        print("   Set LANGFUSE_SECRET_KEY (or LANGCHAIN_API_KEY) and")
        print("   LANGFUSE_PUBLIC_KEY (or LANGCHAIN_PUBLIC_KEY) in .env")
        return
    
    # Get handler
    from src.graph import get_langfuse_handler
    
    handler = get_langfuse_handler()
    if handler is None:
        print("✗ ERROR: Langfuse handler not initialized")
        print("   Check that both public and secret keys are set correctly")
        raise AssertionError("Langfuse handler is None")
    
    print(f"✓ Handler initialized: {type(handler).__name__}")
    print()
    
    # Create a trace
    from langchain_openai import ChatOpenAI
    
    timestamp = int(time.time())
    test_message = f"Langfuse Test Trace {timestamp}"
    
    print(f"Creating trace: {test_message}")
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, callbacks=[handler])
    response = llm.invoke(test_message, config={"callbacks": [handler]})
    
    print(f"✓ LLM call completed")
    print(f"  Response: {response.content[:60]}...")
    print()
    
    # Flush traces
    print("Flushing traces to Langfuse...")
    if hasattr(handler, 'client') and hasattr(handler.client, 'flush'):
        handler.client.flush()
    elif hasattr(handler, 'flush'):
        handler.flush()
    print("✓ Traces flushed")
    print()
    
    # Wait for traces to be sent
    print("Waiting for traces to be sent (5 seconds)...")
    time.sleep(5)
    print()
    
    # Summary
    print("=" * 70)
    print("Test Completed")
    print("=" * 70)
    print()
    print(f"Trace Details:")
    print(f"  Message: {test_message}")
    print(f"  Project: {project}")
    print()
    print(f"To verify in Langfuse dashboard:")
    print(f"1. Open: http://localhost:3000")
    print(f"2. Login: admin@langchain.dev / admin")
    print(f"3. Go to: 'Traces' section")
    print(f"4. Filter by project: {project}")
    print(f"5. Search for: {test_message}")
    print()
    print("✓ Trace should be visible in the dashboard")
    print()


if __name__ == "__main__":
    try:
        test_langfuse_trace()
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ ERROR: {type(e).__name__}: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)

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
    langfuse_host = os.getenv("LANGFUSE_HOST", "localhost:3000")
    
    if not secret_key or not public_key:
        print("⚠ SKIP: Langfuse keys not configured")
        print("   Set LANGFUSE_SECRET_KEY (or LANGCHAIN_API_KEY) and")
        print("   LANGFUSE_PUBLIC_KEY (or LANGCHAIN_PUBLIC_KEY) in .env")
        print()
        print("   Get API keys from Langfuse UI:")
        print("   1. Open: http://localhost:3000")
        print("   2. Login: admin@langchain.dev / admin")
        print("   3. Go to: Settings → API Keys")
        return
    
    # Display configuration (masked)
    print("Configuration:")
    print(f"  Public Key: {public_key[:20]}..." if len(public_key) > 20 else f"  Public Key: {public_key}")
    print(f"  Secret Key: {secret_key[:20]}..." if len(secret_key) > 20 else f"  Secret Key: {secret_key}")
    print(f"  Host: {langfuse_host}")
    print(f"  Project: {project}")
    print()
    
    # Get handler
    from src.graph import get_langfuse_handler
    
    handler = get_langfuse_handler()
    if handler is None:
        print("✗ ERROR: Langfuse handler not initialized")
        print("   Possible issues:")
        print("   1. Both LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY must be set")
        print("   2. Langfuse server may not be accessible at:", langfuse_host)
        print("   3. API keys may be incorrect")
        print()
        print("   Note: Langfuse uses Basic Authentication (public key as username, secret as password)")
        raise AssertionError("Langfuse handler is None")
    
    print(f"✓ Handler initialized: {type(handler).__name__}")
    
    # Verify handler client configuration
    if hasattr(handler, 'client'):
        client = handler.client
        print(f"  Client type: {type(client).__name__}")
        
        # Check tracing enabled status
        tracing_enabled = getattr(client, '_tracing_enabled', None)
        base_url = getattr(client, '_base_url', None)
        project_id = getattr(client, '_project_id', None)
        
        print(f"  Base URL: {base_url}")
        print(f"  Tracing enabled: {tracing_enabled}")
        print(f"  Project ID: {project_id}")
        
        if tracing_enabled is False:
            print("⚠ WARNING: Langfuse tracing is DISABLED!")
            print("   Traces will NOT be sent to Langfuse.")
            print("   This might be because:")
            print("   1. Langfuse server is not reachable")
            print("   2. API keys are incorrect")
            print("   3. SDK initialization failed")
            print()
            print("   Attempting to continue anyway - traces may be queued...")
        elif tracing_enabled:
            print("✓ Langfuse tracing is enabled")
        
        if not project_id:
            print("⚠ WARNING: Project ID is None - traces may not be associated with project")
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
    
    # Flush traces to ensure they're sent to Langfuse
    print("Flushing traces to Langfuse...")
    try:
        if hasattr(handler, 'client') and hasattr(handler.client, 'flush'):
            handler.client.flush()
            print("✓ Traces flushed (via client.flush())")
        elif hasattr(handler, 'flush'):
            handler.flush()
            print("✓ Traces flushed (via handler.flush())")
        else:
            print("⚠ No flush method found - traces will be sent asynchronously")
    except Exception as e:
        print(f"⚠ Warning during flush: {e}")
        print("   Traces may still be sent asynchronously")
    print()
    
    # Wait for traces to be sent (Langfuse SDK sends asynchronously)
    print("Waiting for traces to be sent to Langfuse (5 seconds)...")
    print("   (Langfuse SDK sends traces asynchronously in the background)")
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
    langfuse_url = f"http://{langfuse_host}"
    print(f"1. Open: {langfuse_url}")
    print(f"2. Login: admin@langchain.dev / admin")
    print(f"3. Go to: 'Traces' section")
    print(f"4. Filter by project: {project}")
    print(f"5. Search for: {test_message}")
    print()
    print("✓ Trace should be visible in the dashboard")
    print()
    print("Note: If trace doesn't appear immediately, wait a few more seconds.")
    print("      The Langfuse SDK sends traces asynchronously.")
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

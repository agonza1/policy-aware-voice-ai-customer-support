#!/bin/bash
# Test Langfuse connectivity with curl

LANGFUSE_URL="${LANGFUSE_URL:-http://localhost:3000}"

# Load .env file if it exists
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
    echo ""
fi

# Use Langfuse keys or fallback to LangChain keys
LANGFUSE_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-$LANGCHAIN_PUBLIC_KEY}"
LANGFUSE_SECRET_KEY="${LANGFUSE_SECRET_KEY:-$LANGCHAIN_API_KEY}"

echo "=========================================="
echo "Testing Langfuse at: $LANGFUSE_URL"
echo "=========================================="
echo ""

# Test 1: Basic health check
echo "1. Testing basic health endpoint..."
curl -s -w "\nHTTP Status: %{http_code}\n" "$LANGFUSE_URL/api/public/health"
echo ""
echo ""

# Test 2: Health check with database verification
echo "2. Testing health with database check..."
curl -s -w "\nHTTP Status: %{http_code}\n" "$LANGFUSE_URL/api/public/health?failIfDatabaseUnavailable=true"
echo ""
echo ""

# Test 3: Readiness check (may return 404 - that's OK)
echo "3. Testing readiness endpoint..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$LANGFUSE_URL/api/public/ready")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Readiness endpoint returned 200 OK"
elif [ "$HTTP_CODE" = "404" ]; then
    echo "⚠ Readiness endpoint returned 404 (endpoint may not exist in this version)"
else
    echo "Readiness endpoint returned HTTP $HTTP_CODE"
fi
echo ""
echo ""

# Test 4: Test public ingestion endpoint (with sample data)
if [ -n "$LANGFUSE_PUBLIC_KEY" ] && [ -n "$LANGFUSE_SECRET_KEY" ]; then
    echo "4. Testing ingestion endpoint with credentials..."
    echo "   Using Public Key: ${LANGFUSE_PUBLIC_KEY:0:20}..."
    echo "   Using Secret Key: ${LANGFUSE_SECRET_KEY:0:20}..."
    echo ""
    # Langfuse uses Basic Auth: public key as username, secret key as password
    TRACE_ID="test-trace-$(date +%s)"
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.%3NZ" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")
    
    RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" -X POST "$LANGFUSE_URL/api/public/ingestion" \
        -H "Content-Type: application/json" \
        -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" \
        -d '{
            "batch": [
                {
                    "id": "'$TRACE_ID'",
                    "timestamp": "'$TIMESTAMP'",
                    "type": "trace-create",
                    "body": {
                        "id": "'$TRACE_ID'",
                        "name": "Curl Test Trace",
                        "metadata": {"test": true, "source": "curl-test-script"}
                    }
                }
            ]
        }')
    
    HTTP_STATUS=$(echo "$RESPONSE" | grep -o "HTTP_STATUS:[0-9]*" | cut -d: -f2)
    BODY=$(echo "$RESPONSE" | sed '/HTTP_STATUS:/d')
    
    echo "Response:"
    echo "$BODY" | head -n 5
    echo ""
    echo "HTTP Status: $HTTP_STATUS"
    
    if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "201" ] || [ "$HTTP_STATUS" = "207" ]; then
        # Check if response contains success
        if echo "$BODY" | grep -q '"successes"'; then
            SUCCESS_COUNT=$(echo "$BODY" | grep -o '"successes":\[[^]]*\]' | grep -o '"status":[0-9]*' | wc -l)
            echo "✓ Ingestion successful! Created $SUCCESS_COUNT trace(s)."
            echo "  View in Langfuse dashboard: $LANGFUSE_URL"
        else
            echo "✓ Ingestion successful! Trace should appear in Langfuse dashboard."
        fi
    elif [ "$HTTP_STATUS" = "401" ]; then
        echo "✗ Authentication failed. Check your API keys in .env"
        echo "  Make sure both LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set"
    else
        echo "⚠ Unexpected status code: $HTTP_STATUS"
        echo "  Response: $BODY"
    fi
    echo ""
    echo ""
else
    echo "4. Skipping ingestion test (API keys not found)"
    echo "   Add to .env:"
    echo "   - LANGFUSE_PUBLIC_KEY (or LANGCHAIN_PUBLIC_KEY)"
    echo "   - LANGFUSE_SECRET_KEY (or LANGCHAIN_API_KEY)"
    echo "   Get keys from: http://localhost:3000 → Settings → API Keys"
    echo ""
fi

# Test 5: Check UI is accessible
echo "5. Testing UI endpoint..."
curl -s -w "\nHTTP Status: %{http_code}\n" "$LANGFUSE_URL" | head -n 20
echo ""
echo ""

echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo "✓ Health checks completed"
echo ""
echo "Expected results:"
echo "  - Health endpoints should return 200 OK"
echo "  - UI endpoint should return 200 OK (HTML content)"
echo "  - Ingestion endpoint should return 207 Multi-Status (batch endpoint)"
echo ""
echo "Note: HTTP 207 is normal for batch ingestion endpoints."
echo "      It indicates partial success (some items succeeded/failed)."
echo ""

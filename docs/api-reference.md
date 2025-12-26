# API Reference

Complete API endpoint documentation for the Voice AI Loan Pre-Approval Demo.

## Base URL

The base URL varies by deployment:
- **Local**: `http://localhost:8000`
- **Cerebrium**: `https://your-deployment.cerebrium.ai`
- **ECS**: `https://your-alb-dns-name.elb.amazonaws.com`

## Authentication

Currently, the API does not require authentication. In production, consider implementing:
- API key authentication
- OAuth 2.0
- JWT tokens

## Endpoints

### 1. Twilio Webhook Endpoint

**Endpoint**: `POST /`

**Description**: Handles incoming Twilio webhook requests for voice calls. Returns TwiML that connects the call to the WebSocket endpoint.

**Request Headers**:
```
Content-Type: application/x-www-form-urlencoded
```

**Request Body** (from Twilio):
```
CallSid: CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
From: +1234567890
To: +1987654321
CallStatus: ringing
...
```

**Response**:
- **Content-Type**: `application/xml`
- **Status**: `200 OK`

**Response Body** (TwiML):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://your-domain.com/ws"></Stream>
  </Connect>
  <Pause length="40"/>
</Response>
```

**WebSocket URL Generation**:
- Uses `WEBSOCKET_URL` environment variable if set
- Otherwise constructs from request headers:
  - Scheme: `wss` if HTTPS, `ws` if HTTP
  - Host: From `Host` header or `x-forwarded-host`
  - Path: `/ws`

**Example**:
```bash
curl -X POST https://your-domain.com/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=CA123&From=%2B1234567890&To=%2B1987654321"
```

**Implementation**: `main.py::start_call()`

---

### 2. WebSocket Endpoint

**Endpoint**: `WebSocket /ws`

**Description**: Establishes WebSocket connection for real-time bidirectional audio streaming between Twilio and the application.

**Connection Process**:
1. Client connects to `/ws`
2. Server accepts connection
3. Client sends initial text message with stream metadata
4. Server parses stream SID
5. Audio pipeline starts processing

**WebSocket Protocol**:
- **Protocol**: Twilio Media Stream Protocol
- **Format**: JSON for metadata, binary for audio
- **Direction**: Bidirectional

**Initial Message** (from Twilio):
```json
{
  "event": "start",
  "start": {
    "streamSid": "MZxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "accountSid": "ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "callSid": "CAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "tracks": {
      "inbound": {},
      "outbound": {}
    },
    "mediaFormat": {
      "encoding": "audio/x-mulaw",
      "sampleRate": 8000
    }
  }
}
```

**Audio Format**:
- **Encoding**: μ-law (PCMU) or linear PCM
- **Sample Rate**: 8000 Hz (telephony standard)
- **Channels**: Mono

**Pipeline Flow**:
```
WebSocket Input → STT (Deepgram) → LLM (OpenAI) → TTS (OpenAI) → WebSocket Output
```

**Event Handlers**:
- `on_client_connected`: Initiates conversation
- `on_client_disconnected`: Cleans up resources

**Implementation**: `main.py::websocket_endpoint()`, `bot.py::main()`

---

## WebSocket Message Format

### Incoming Audio Messages

**Format**: Binary audio data (μ-law PCM)

**Frequency**: Continuous stream during call

**Processing**: 
- Received by WebSocket transport
- Converted by Deepgram STT service
- Transcribed to text
- Fed to LLM for processing

### Outgoing Audio Messages

**Format**: Binary audio data (PCM)

**Generation**:
- LLM generates text response
- Cartesia TTS converts to speech
- Audio sent via WebSocket to Twilio

---

## Error Responses

All endpoints follow standard HTTP status codes:

| Status Code | Description |
|-------------|-------------|
| `200` | Success |
| `400` | Bad Request (validation errors) |
| `404` | Not Found |
| `500` | Internal Server Error |
| `503` | Service Unavailable |

**Error Response Format**:
```json
{
  "success": false,
  "detail": "Error message description"
}
```

---

## Rate Limiting

Currently, no rate limiting is implemented. In production, consider:
- Per-IP rate limiting
- Per-API-key rate limiting
- WebSocket connection limits

---

## CORS Configuration

Current CORS configuration (development):
- **Allow Origins**: `*` (all origins)
- **Allow Credentials**: `true`
- **Allow Methods**: `*` (all methods)
- **Allow Headers**: `*` (all headers)

**Production Recommendation**: Restrict to specific origins.

**Implementation**: `main.py` CORS middleware

---

## Environment Variables

Required environment variables for API functionality:

| Variable | Description | Required |
|----------|-------------|----------|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o | Yes |
| `DEEPGRAM_API_KEY` | Deepgram API key for STT | Yes |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID | Yes |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token | Yes |
| `WEBSOCKET_URL` | WebSocket URL override | No |

---

## Static Files

### CSS
- **Path**: `/static/css/loan_application.css`
- **Description**: Styling for loan application form

### JavaScript
- **Path**: `/static/js/loan_application.js`
- **Description**: Form handling and URL parameter parsing

### Mount Point
- **Path**: `/static/*`
- **Implementation**: FastAPI StaticFiles mount

---

## Future API Endpoints (Planned)

### Application Status
- `GET /api/application/{application_id}`
- Check application status

### Escalation
- `POST /api/escalate`
- Request human review
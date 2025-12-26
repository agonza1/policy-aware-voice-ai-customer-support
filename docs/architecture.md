# Architecture Overview

## System Architecture

**Policy-aware Voice AI customer support PoC.**  
A minimal real-time voice agent that answers a simple customer support inquiry (“Why is my case still open?”), applies explicit decision rules using LangGraph, and conditionally escalates a live call to a human agent. The system is intentionally simple and designed to demonstrate **default-deny execution** for Voice AI.

---

## Architecture Flow

Twilio Call
↓
FastAPI (POST /) → TwiML (WebSocket URL)
↓
WebSocket (/ws)
↓
Pipecat Voice Pipeline
├── STT (Deepgram)
├── Intent Extraction (OpenAI LLM)
├── Decision & Routing (LangGraph)
└── TTS (OpenAI / Cartesia)
↓
Spoken Response OR
Real Escalation (Twilio Call Forward)

---

## High-Level Interaction Flow

1. Incoming phone call hits `POST /`
2. Server responds with TwiML pointing to `/ws`
3. Pipecat handles real-time audio over WebSocket
4. Agent asks for **case number** (required)
5. User provides case number (stored in session state)
6. User asks: “Why is my case still open?”
7. LLM extracts intent only (no execution authority)
8. LangGraph evaluates policy and routes execution
9. Outcome:
   - Read-only case status (spoken)
   - Escalation denied (spoken)
   - Escalation allowed → call forwarded to human agent

Once escalated, the AI agent stops speaking.

---

## Components

### `main.py` — FastAPI Server
- `POST /`
  - Twilio webhook
  - Returns TwiML with WebSocket URL
- `WebSocket /ws`
  - Audio streaming endpoint
  - Entry point into Pipecat pipeline

---

### `bot.py` — Voice Pipeline
- Pipecat pipeline:
  - STT → LangGraph → TTS
- Manages conversation order:
  1. Ask for case number
  2. Wait for response
  3. Forward inquiry to LangGraph
- Must NOT call backend tools directly

---

### `graph.py` — Decision & Execution Plane
- LangGraph state machine
- Enforces default-deny execution
- Routes between:
  - Read-only status response
  - Escalation denial
  - Escalation execution
- Only place where side effects are allowed

---

### `policies.py`
- In-memory decision table (PoC only)
- Deterministic rules
- Missing rule → deny

---

### `tools.py`
- Backend actions
- Includes real side effect:
  - `forward_call_to_agent(call_sid, support_phone_number)`
- Tools are unreachable unless LangGraph explicitly routes to them

---

### `prompts.py`
- LLM system prompts
- Intent extraction only
- No business logic
- No execution instructions

---

## Decision Model (PoC)

| intent       | auth_level | decision        |
|-------------|------------|-----------------|
| case_status | any        | allow_status    |
| escalate    | weak       | deny            |
| escalate    | strong     | allow_escalate  |

- Auth level is simulated
- Default behavior is deny

---

## Technology Stack

- FastAPI — Web framework, WebSocket support
- Pipecat — Real-time voice pipeline
- Twilio — Call webhooks and live call forwarding
- Deepgram — Speech-to-Text
- OpenAI — Intent extraction (LLM)
- Cartesia / OpenAI TTS — Text-to-Speech
- LangGraph — Explicit decision & execution plane
- LangSmith (optional) — Tracing and debugging

---

## Observability

- LangSmith tracing is optional
- Used only to inspect:
  - Intent extraction
  - Graph routing
  - Execution paths
- System must run correctly without LangSmith enabled

---

## Deployment

- Local:
  - `uvicorn main:app --host 0.0.0.0 --port 8000`
  - ngrok for Twilio webhooks
- Container-friendly
- Stateless by design

---

## Data Storage

- In-memory only
- Session state:
  - case number
  - auth level
  - call SID
- No database
- Data lost on restart (acceptable for PoC)

---

## Security & Constraints

- HTTPS / WSS required in production
- Environment variables for secrets
- No persistence
- No background jobs
- No retries
- One case per session
- One inquiry per session

---

## Architectural Principle

LLMs interpret.  
Graphs decide.  
Voice delivers.
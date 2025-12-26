# High-Level Flow Documentation

This document describes the complete end-to-end flow of the **Policy-Aware Voice AI Customer Support PoC**.

---

## Overview

The system demonstrates a minimal, real-time Voice AI agent that handles a simple customer support inquiry (“Why is my case still open?”), applies explicit decision rules using LangGraph, and conditionally escalates a live call to a human agent.  

The goal is to show **safe, default-deny execution** in voice AI systems — not full customer support automation.

---

## Complete Flow Diagram

┌───────────────────────────────────────────────────────────────────┐
│ HIGH-LEVEL APPLICATION FLOW │
└───────────────────────────────────────────────────────────────────┘

INBOUND CALL
│
│ Customer calls support number (Twilio)
│
▼

VOICE AGENT GREETING
│
│ Pipecat voice pipeline
│ - Greets caller
│ - Explains purpose
│ - Requests case number
│
▼

CASE IDENTIFICATION
│
│ - User provides case number (spoken)
│ - Case number stored in in-memory session state
│
▼

CASE INQUIRY
│
│ User asks:
│ “Why is my case still open?”
│
▼

INTENT EXTRACTION
│
│ LLM extracts intent only:
│ - case_status
│ - escalate
│
│ (No execution authority)
│
▼

DECISION & ROUTING (LangGraph)
│
│ Policy evaluation (default-deny):
│ - Read-only status allowed
│ - Escalation allowed only for strong auth
│
▼

OUTCOME
│
│ ├─▶ Speak case status (read-only)
│ │
│ ├─▶ Deny escalation (spoken explanation)
│ │
│ └─▶ Escalate to human agent
│ (Twilio call forwarded)
│
▼

COMPLETION
│
│ - AI stops speaking after escalation
│ - Session ends

---

## Detailed Flow Steps

### Step 1: Inbound Call (Twilio)

**Trigger**: Customer dials the configured support phone number.

**Process**:
- Twilio receives the call
- Twilio sends a `POST /` request to the FastAPI webhook
- FastAPI responds with TwiML containing a WebSocket URL
- Twilio opens a WebSocket connection to `/ws`

**Key Components**:
- `main.py` — Twilio webhook handler
- Twilio Voice API
- WebSocket URL generation

---

### Step 2: Voice Agent Greeting (Pipecat)

**Process**:
- Pipecat pipeline initializes
- AI greets the caller
- Explains the purpose of the call
- Requests the **case number**

**Key Components**:
- `bot.py` — Pipecat pipeline initialization
- Deepgram STT
- TTS engine (OpenAI / Cartesia)

---

### Step 3: Case Identification

**Process**:
- User speaks a case number
- Case number is treated as an opaque identifier
- Stored in in-memory session state
- No validation or lookup occurs yet

**Rules**:
- No case number → no backend actions allowed
- One case per session

---

### Step 4: Case Inquiry

**Process**:
- User asks:
  - “Why is my case still open?”
  - or “Can you escalate this?”

**Constraints**:
- Only one inquiry per session
- No free-form support conversation

---

### Step 5: Intent Extraction (LLM)

**Process**:
- Audio is converted to text
- LLM extracts intent only:
  - `case_status`
  - `escalate`

**Important**:
- LLM does NOT decide execution
- LLM does NOT call tools
- Output is structured intent only

---

### Step 6: Decision & Routing (LangGraph)

**Process**:
- LangGraph receives:
  - intent
  - auth level (simulated)
  - case number
  - call SID
- Policy rules evaluated (default-deny)
- Execution path selected

**Policy Model (PoC)**:

| intent       | auth_level | decision        |
|-------------|------------|-----------------|
| case_status | any        | allow_status    |
| escalate    | weak       | deny            |
| escalate    | strong     | allow_escalate  |

Missing rule → deny.

---

### Step 7: Outcomes

#### Case Status (Read-Only)
- Dummy case status returned
- Spoken back to the user
- No side effects

#### Escalation Denied
- AI explains escalation is not allowed
- Call continues briefly or ends

#### Escalation Allowed (REAL SIDE EFFECT)
- LangGraph routes to escalation node
- `forward_call_to_agent()` is invoked
- Active Twilio call is forwarded to a human agent
- AI stops speaking immediately

---

### Step 8: Completion

**Process**:
- Session ends after response or escalation
- No data is persisted
- No follow-up actions

---

## Key Architectural Guarantees

- No backend action runs without LangGraph approval
- Escalation is impossible unless explicitly routed
- Default-deny execution
- Voice logic and decision logic are separated
- In-memory state only

---

## Technology Stack

- **FastAPI** — Web framework, WebSocket support
- **Pipecat** — Real-time voice pipeline
- **Twilio** — Voice calls and live call forwarding
- **Deepgram** — Speech-to-Text
- **OpenAI** — Intent extraction (LLM)
- **Cartesia / OpenAI TTS** — Text-to-Speech
- **LangGraph** — Decision & execution plane
- **LangSmith (optional)** — Tracing and debugging

---

## Non-Goals (Intentional)

- No forms
- No databases
- No CRM integrations
- No RAG or vector search
- No async workflows
- No production auth
- No persistence

This document describes a **learning-focused PoC**, not a production system.

---

## Guiding Principle

LLMs interpret.  
Graphs decide.  
Voice delivers.


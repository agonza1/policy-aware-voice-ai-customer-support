# Policy-aware Voice AI Customer Support PoC - Documentation

This documentation provides comprehensive architecture and API reference for the Policy-aware Voice AI Customer Support PoC application. This documentation is designed to serve as context for AI-assisted development tools like Cursor.

## Documentation Structure

- **[Architecture Overview](./architecture.md)** - High-level system architecture, components, and data flow
- **[API Reference](./api-reference.md)** - Complete API endpoint documentation
- **[High-Level Flow](./high-level-flow.md)** - Detailed workflow and process flows

## Quick Start

For developers new to the project, start with:
1. [Architecture Overview](./architecture.md) - Understand the system design
2. [High-Level Flow](./high-level-flow.md) - Learn the application workflow
3. [API Reference](./api-reference.md) - Explore available endpoints

## Project Context

This is a minimal, real-time voice agent that:
- Answers a simple customer support inquiry ("Why is my case still open?")
- Applies explicit decision rules using LangGraph
- Conditionally escalates a live call to a human agent
- Demonstrates **default-deny execution** for Voice AI

The system is intentionally simple and designed to show how voice interaction, AI reasoning, and policy-based decisioning can be cleanly separated.

## Key Technologies

- **FastAPI**: Web framework and WebSocket server
- **Pipecat**: Real-time audio processing pipeline ([API Reference](https://reference-server.pipecat.ai/en/latest/))
- **Twilio**: Call webhooks, audio streaming, and live call forwarding
- **Deepgram**: Speech-to-Text (STT)
- **OpenAI**: Intent extraction (LLM) and Text-to-Speech (TTS)
- **Cartesia**: Alternative Text-to-Speech provider
- **LangGraph**: Explicit decision & execution plane for policy enforcement

## Architectural Principle

**LLMs interpret.  
Graphs decide.  
Voice delivers.**


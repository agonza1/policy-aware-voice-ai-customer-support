"""FastAPI server for Policy-aware Voice AI Customer Support PoC.

This module provides:
- POST / - Twilio webhook endpoint that returns TwiML
- WebSocket /ws - Audio streaming endpoint for Pipecat pipeline
"""

import json
import os
from xml.sax.saxutils import quoteattr

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from bot import main

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Policy-aware Voice AI Customer Support PoC")

def _parse_csv_env(name: str) -> list[str]:
    value = os.getenv(name, "")
    return [part.strip() for part in value.split(",") if part.strip()]


cors_allow_origins = _parse_csv_env("CORS_ALLOW_ORIGINS") or ["*"]
cors_allow_credentials = os.getenv("CORS_ALLOW_CREDENTIALS", "true").lower() in {
    "1",
    "true",
    "yes",
}

# Starlette/FastAPI CORS behavior + browser spec:
# wildcard origins cannot be combined with credentials safely.
if "*" in cors_allow_origins:
    cors_allow_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins,
    allow_credentials=cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/")
async def start_call(request: Request):
    """Twilio webhook endpoint that returns TwiML with WebSocket URL."""
    logger.info("Received POST request for TwiML")
    
    # Use environment variable if set, otherwise construct from request
    ws_url = os.getenv("WEBSOCKET_URL")
    if not ws_url:
        forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
        is_https = forwarded_proto == "https" or request.url.scheme == "https"
        scheme = "wss" if is_https else "ws"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if not host:
            logger.error("Cannot determine host for WebSocket URL")
            host = "localhost:8000"

        allowed_hosts = _parse_csv_env("ALLOWED_HOSTS")
        if allowed_hosts and host not in allowed_hosts:
            logger.warning(
                f"Rejected Host header {host!r}; allowed hosts: {allowed_hosts}. "
                "Set WEBSOCKET_URL to override."
            )
            host = allowed_hosts[0]
        ws_url = f"{scheme}://{host}/ws"
    
    logger.info(f"Generated WebSocket URL: {ws_url}")
    
    xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url={quoteattr(ws_url)}></Stream>
  </Connect>
  <Pause length="40"/>
</Response>'''
    
    return HTMLResponse(content=xml_content, media_type="application/xml")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time audio streaming."""
    await websocket.accept()
    logger.info("WebSocket connection accepted")
    
    # Read initial messages to get stream metadata
    try:
        # First message is usually empty or connection metadata
        first_message = await websocket.receive_text()
        logger.debug(f"First WebSocket message: {first_message}")
        
        # Second message contains stream start data
        start_message = await websocket.receive_text()
        call_data = json.loads(start_message)
        
        stream_sid = call_data.get("start", {}).get("streamSid")
        call_sid = call_data.get("start", {}).get("callSid")
        
        logger.info(f"Starting voice AI session with stream_sid: {stream_sid}, call_sid: {call_sid}")
        
        # Verify Twilio credentials are available
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        if not account_sid or not auth_token:
            logger.warning(f"TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN not set. Account SID: {'SET' if account_sid else 'NOT SET'}, Auth Token: {'SET' if auth_token else 'NOT SET'}")
        
        company_name = os.getenv("COMPANY_NAME", "our company")
        
        # Start the Pipecat pipeline
        await main(websocket, stream_sid, call_sid, company_name=company_name)
        
    except Exception as e:
        logger.error(f"Error in WebSocket endpoint: {str(e)}", exc_info=True)
        await websocket.close()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

"""FastAPI server for Policy-aware Voice AI Customer Support PoC.

This module provides:
- POST / - Twilio webhook endpoint that returns TwiML
- WebSocket /ws - Audio streaming endpoint for Pipecat pipeline
"""

import json
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from loguru import logger

from src.bot import main

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="Policy-aware Voice AI Customer Support PoC")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for testing
    allow_credentials=True,
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
        forwarded_proto = request.headers.get("x-forwarded-proto")
        is_https = forwarded_proto == "https" or request.url.scheme == "https"
        scheme = "wss" if is_https else "ws"
        host = request.headers.get('host') or request.headers.get('x-forwarded-host')
        if not host:
            logger.error("Cannot determine host for WebSocket URL")
            host = "localhost:8000"
        ws_url = f"{scheme}://{host}/ws"
    
    logger.info(f"Generated WebSocket URL: {ws_url}")
    
    xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{ws_url}"></Stream>
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


@app.post("/transfer")
async def transfer_call(request: Request):
    """TwiML endpoint for call transfer to human agent."""
    try:
        # Get phone number from query parameter or environment variable
        support_phone_number = request.query_params.get("number") or os.getenv("SUPPORT_PHONE_NUMBER")
        
        # Log the request for debugging
        logger.info(f"Transfer endpoint called - number param: {request.query_params.get('number')}, env number: {os.getenv('SUPPORT_PHONE_NUMBER')}")
        
        if not support_phone_number:
            logger.error("SUPPORT_PHONE_NUMBER not configured for transfer")
            xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>I'm sorry, transfer is not available at this time.</Say>
  <Hangup/>
</Response>'''
        else:
            # Normalize and escape the phone number for TwiML
            from src.tools import normalize_phone_number
            normalized_number = normalize_phone_number(support_phone_number)
            logger.info(f"Transferring call to {normalized_number} (normalized from {support_phone_number})")
            
            # Use Dial with proper attributes for call transfer
            # If Dial fails (no answer, busy, etc.), Twilio will continue to next verb
            xml_content = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say voice="alice">Connecting you to one of our agents now. Please hold.</Say>
  <Dial timeout="30" answerOnMedia="false" hangupOnStar="false" record="false">
    <Number>{normalized_number}</Number>
  </Dial>
  <Say voice="alice">I'm sorry, we couldn't connect you to an agent at this time. Please try again later.</Say>
  <Hangup/>
</Response>'''
        
        logger.debug(f"Returning TwiML for transfer to {support_phone_number}")
        return HTMLResponse(content=xml_content, media_type="application/xml")
    
    except Exception as e:
        logger.error(f"Error in transfer endpoint: {e}", exc_info=True)
        # Return error TwiML
        error_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Say>I'm sorry, an error occurred during transfer. Please try again later.</Say>
  <Hangup/>
</Response>'''
        return HTMLResponse(content=error_xml, media_type="application/xml")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

"""Pipecat voice pipeline for customer support.

This module implements the voice interaction layer using Pipecat.
It handles STT, conversation management, and TTS, but delegates
all decisions and execution to LangGraph.
"""

import asyncio
import os
import sys
from typing import Optional

from dotenv import load_dotenv
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMMessagesFrame, EndFrame, TextFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService, LiveOptions
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.openai.tts import OpenAITTSService
from pipecat.transports.network.fastapi_websocket import (
    FastAPIWebsocketTransport,
    FastAPIWebsocketParams,
)

from case_extraction import extract_case_number
from graph import run_graph
from prompts import INTENT_EXTRACTION_PROMPT

load_dotenv()

# Configure logger
logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

DEFAULT_COMPANY_NAME = os.getenv("COMPANY_NAME", "our company")
CARTESIA_MODEL = os.getenv("CARTESIA_MODEL", "sonic-3")
CARTESIA_VOICE_ID = os.getenv("CARTESIA_WELCOME_VOICE_ID", "sonic-3")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "alloy")  # Options: alloy, echo, fable, onyx, nova, shimmer


def build_system_prompt(company_name: str) -> str:
    """Build the system prompt for the customer support agent."""
    return f"""
You are a helpful customer support agent for {company_name}. Your role is to assist customers with:

1. **Case Status Inquiries**: Help customers check the status of their support cases. You will need their case number to look up the status.

2. **Case Escalation**: CRITICAL - If a customer requests escalation, transfer, or to speak with a human agent (using words like "escalate", "agent", "human", "representative", "transfer", "connect me", "speak with"), DO NOT generate ANY response. Be completely silent. Do not say "One moment please" or "I understand" or anything at all. The system handles escalation automatically - you must say nothing.

Keep your responses:
- Concise and professional (2-3 sentences max)
- Friendly and helpful
- Focused on solving the customer's issue

When a customer provides their case number, acknowledge it and let them know you're checking the status.

IMPORTANT: For escalation requests, be silent or very brief - the system handles it automatically.

Respond in the same language the caller uses.
""".strip()


async def main(websocket_client, stream_sid: str, call_sid: Optional[str] = None, company_name: Optional[str] = None):
    """Main entry point for the voice pipeline."""
    company_name = company_name or os.getenv("COMPANY_NAME") or DEFAULT_COMPANY_NAME
    system_prompt = build_system_prompt(company_name)

    # Transport setup - using FastAPIWebsocketTransport like the working example
    transport = FastAPIWebsocketTransport(
        websocket=websocket_client,
        params=FastAPIWebsocketParams(
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
            serializer=TwilioFrameSerializer(stream_sid),
        ),
    )
    
    # Initialize services
    deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
    if not deepgram_api_key:
        raise ValueError("DEEPGRAM_API_KEY must be set")
    
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY must be set")
    
    # STT Service
    stt = DeepgramSTTService(
        api_key=deepgram_api_key,
        live_options=LiveOptions(
            model="nova-3",
            language="en-US",
        ),
    )

    # LLM Service
    llm = OpenAILLMService(
        name="LLM",
        api_key=openai_api_key,
        model="gpt-4o-mini",
    )
    
    # TTS Service - OpenAI as primary, Cartesia as backup
    openai_tts: OpenAITTSService | None = None
    cartesia_tts: CartesiaTTSService | None = None
    
    # Try OpenAI TTS first (primary)
    try:
        openai_tts = OpenAITTSService(
            api_key=openai_api_key,
            voice=OPENAI_TTS_VOICE,
        )
        logger.info(f"OpenAI TTS enabled as primary (voice: {OPENAI_TTS_VOICE}).")
    except Exception as exc:
        logger.warning(f"Failed to initialize OpenAI TTS: {exc}, will try Cartesia as backup")
        openai_tts = None
    
    # Try Cartesia TTS as backup if OpenAI failed
    if not openai_tts:
        cartesia_api_key = os.getenv("CARTESIA_API_KEY")
        cartesia_voice_id = CARTESIA_VOICE_ID
        
        if cartesia_api_key and cartesia_voice_id:
            try:
                cartesia_tts = CartesiaTTSService(
                    api_key=cartesia_api_key,
                    voice_id=cartesia_voice_id,
                    model=CARTESIA_MODEL,
                )
                logger.info("Cartesia TTS enabled as backup.")
            except Exception as exc:
                logger.error(f"Failed to initialize Cartesia TTS: {exc}")
                cartesia_tts = None
        else:
            logger.warning("Cartesia TTS not configured; CARTESIA_API_KEY and CARTESIA_WELCOME_VOICE_ID required.")
    
    # Use whichever TTS service is available
    tts_service = openai_tts or cartesia_tts
    if not tts_service:
        raise RuntimeError(
            "No TTS service available. Configure OPENAI_API_KEY (for OpenAI TTS) or "
            "CARTESIA_API_KEY and CARTESIA_WELCOME_VOICE_ID (for Cartesia TTS)."
        )

    # Initialize conversation context
    messages = [
        {
            "role": "system",
            "content": system_prompt,
        }
    ]
    
    context = OpenAILLMContext(messages=messages)
    context_aggregator = llm.create_context_aggregator(context)
    
    # Track conversation state for LangGraph
    conversation_state = {
        "case_number": None,
        "case_number_collected": False,
        "inquiry_processed": False,
        "call_sid": call_sid,
        "escalated": False,
        "case_number_extracted_after_inquiry": False,  # Track if we already re-ran LangGraph after extracting case number
        "escalation_processed": False,  # Track if we've already processed an escalation request
        "last_processed_message": None,  # Track the last message we processed to avoid duplicates
    }
    
    # Create pipeline
    pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from Twilio
            stt,  # Speech-To-Text
            context_aggregator.user(),
            llm,  # LLM
            tts_service,  # Text-To-Speech (OpenAI primary, Cartesia backup)
            transport.output(),  # Websocket output to Twilio
            context_aggregator.assistant(),
        ]
    )
    
    task = PipelineTask(pipeline, params=PipelineParams(allow_interruptions=True))
    
    def sync_context():
        """Sync messages with context."""
        try:
            context.set_messages(messages)
        except AttributeError:
            # Some versions of OpenAILLMContext may not expose set_messages;
            # in that case we rely on in-place list mutation of `messages`.
            pass
    
    # Background task to monitor messages and route to LangGraph
    async def monitor_messages():
        """Monitor conversation and route to LangGraph for policy decisions."""
        logger.info("LangGraph monitoring task started")
        while True:
            try:
                # Check periodically for new messages
                await asyncio.sleep(2)
                
                # If escalation has occurred, skip processing but keep loop running to maintain connection
                if conversation_state.get("escalated"):
                    logger.debug("Escalation completed - skipping message processing but keeping connection open")
                    continue
                
                aggregated_messages = context.get_messages()
                if not aggregated_messages:
                    continue
                
                # Get latest user message
                user_messages = [m["content"] for m in aggregated_messages if m.get("role") == "user"]
                if not user_messages:
                    continue
                
                latest_user_text = user_messages[-1]
                logger.debug(f"Monitoring latest user message: {latest_user_text}")
                
                # Skip if we've already processed this exact message
                if latest_user_text == conversation_state.get("last_processed_message"):
                    logger.debug(f"Skipping already processed message: {latest_user_text}")
                    continue
                
                conversation_state["last_processed_message"] = latest_user_text
                
                # Extract case number if not already collected
                if not conversation_state["case_number_collected"]:
                    case_number = extract_case_number(latest_user_text)
                    if case_number:
                        conversation_state["case_number"] = case_number
                        conversation_state["case_number_collected"] = True
                        logger.info(f"Extracted case number: {case_number}")
                
                # If we just extracted a case number and inquiry was already processed (without case number),
                # reset inquiry_processed to re-run LangGraph with the case number (only once)
                if (conversation_state.get("case_number") and 
                    conversation_state.get("inquiry_processed") and 
                    not conversation_state.get("case_number_extracted_after_inquiry")):
                    # Check if the previous LangGraph run was without a case number
                    # If so, re-run it now that we have the case number (only once)
                    logger.info("Case number extracted after initial inquiry - re-running LangGraph with case number")
                    conversation_state["inquiry_processed"] = False
                    conversation_state["case_number_extracted_after_inquiry"] = True
                
                # Route to LangGraph for policy decisions
                # LangGraph handles all decision-making including escalation detection
                # Always process if inquiry not yet processed, OR if escalation is requested (even after previous inquiry)
                should_process = not conversation_state["inquiry_processed"]
                logger.debug(f"Should process inquiry: {should_process}, inquiry_processed: {conversation_state.get('inquiry_processed')}, escalated: {conversation_state.get('escalated')}")
                
                # Also check if this might be an escalation request (even if inquiry was already processed)
                if not should_process and not conversation_state.get("escalated"):
                    # Quick check for escalation keywords to allow re-processing for escalation
                    escalation_keywords = [
                        "escalate", "agent", "human", "representative", "speak to someone",
                        "talk to a person", "transfer", "manager", "supervisor", "connect me", "connect"
                    ]
                    has_escalation_keyword = any(keyword in latest_user_text.lower() for keyword in escalation_keywords)
                    logger.debug(f"Checking for escalation keywords in '{latest_user_text}': {has_escalation_keyword}")
                    if has_escalation_keyword:
                        logger.info(f"Escalation request detected in message: '{latest_user_text}' - routing to LangGraph even though inquiry was already processed")
                        should_process = True
                
                if should_process:
                    logger.info(f"Processing message through LangGraph: '{latest_user_text}'")
                    try:
                        # Run LangGraph with the user's inquiry - it will extract intent and make decisions
                        result = run_graph(
                            user_input=latest_user_text,
                            case_number=conversation_state.get("case_number"),
                            call_sid=call_sid,
                        )
                        logger.info(f"LangGraph result: escalated={result.get('escalated')}, intent={result.get('intent')}, response_text={result.get('response_text')}")
                        
                        # Only mark as processed if this wasn't an escalation request after a previous inquiry
                        intent = result.get("intent")
                        if intent != "escalate" or not conversation_state["inquiry_processed"]:
                            conversation_state["inquiry_processed"] = True
                        
                        escalated = result.get("escalated", False)
                        conversation_state["escalated"] = escalated
                        
                        # Handle escalation if LangGraph decided to escalate
                        if escalated:
                            logger.info("LangGraph decided to escalate - handling transfer")
                            
                            # CRITICAL: Stop the LLM from generating responses
                            # The transfer TwiML will handle the announcement, so we don't need to speak anything
                            stop_message = {
                                "role": "system",
                                "content": "CRITICAL: The call has been escalated to a human agent. You MUST NOT generate any responses. The conversation is ending immediately. Do not speak. Do not respond. Stop all processing. Be completely silent."
                            }
                            messages.append(stop_message)
                            
                            # Update the main system prompt to prevent future responses
                            for msg in messages:
                                if msg.get("role") == "system" and "customer support agent" in msg.get("content", ""):
                                    msg["content"] = f"{msg['content']}\n\nCRITICAL: The call has been escalated. Do not generate any responses. Be completely silent."
                                    break
                            sync_context()
                            
                            # DO NOT try to speak the LangGraph response - the transfer TwiML already has a <Say> verb
                            # that will announce the transfer. Speaking here causes issues because the WebSocket
                            # closes when Twilio processes the transfer TwiML.
                            logger.info("Transfer initiated via TwiML - TwiML will handle the announcement")
                            
                            # Don't break out of the loop - keep it running so WebSocket stays open briefly
                            # The transfer will happen via TwiML, which will close the connection
                            # We'll just skip processing new messages since escalated is now True
                            # Continue the loop but it will skip processing due to escalated=True check at top
                            continue
                        
                        # If LangGraph generated a response (non-escalation), inject it into the conversation
                        response_text = result.get("response_text")
                        if response_text:
                            logger.info(f"LangGraph response: {response_text}")
                            # Queue the response directly as a TextFrame to trigger TTS
                            await task.queue_frames([TextFrame(text=response_text)])
                            
                    except Exception as e:
                        logger.error(f"Error in LangGraph processing: {e}", exc_info=True)
                
            except asyncio.CancelledError:
                # Task was cancelled (e.g., when WebSocket closes during transfer)
                logger.info("Monitoring task cancelled - connection closing")
                break
            except Exception as e:
                logger.error(f"Error in monitor_messages: {e}", exc_info=True)
                await asyncio.sleep(2)
    
    monitor_task = None

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        """Handle client connection."""
        nonlocal monitor_task
        # Start monitoring task when client connects
        monitor_task = asyncio.create_task(monitor_messages())
        logger.info("LangGraph monitoring task created")
        
        # Kick off the conversation with greeting
        opening_message = {
            "role": "system", 
            "content": (
                f"Say: 'Hello! This is {company_name} customer support. "
                "I can help you check your case status or escalate your case. "
                "First, I'll need your case number. Please provide your case number.'"
            ),
        }
        messages.append(opening_message)
        sync_context()
        await task.queue_frames([LLMMessagesFrame(list(messages))])
        messages.pop()
        sync_context()

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        """Handle client disconnection."""
        nonlocal monitor_task
        if monitor_task:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        await task.queue_frames([EndFrame()])

    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)

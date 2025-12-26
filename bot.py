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


def build_system_prompt(company_name: str) -> str:
    """Build the system prompt for the customer support agent."""
    return f"""
You are a helpful customer support agent for {company_name}. Your role is to assist customers with:

1. **Case Status Inquiries**: Help customers check the status of their support cases. You will need their case number to look up the status.

2. **Case Escalation**: If a customer requests escalation or if their case meets certain criteria, you can escalate their call to a human agent.

Keep your responses:
- Concise and professional (2-3 sentences max)
- Friendly and helpful
- Focused on solving the customer's issue

When a customer provides their case number, acknowledge it and let them know you're checking the status.
If they want to escalate, confirm and let them know you're connecting them to an agent.

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
    
    # TTS Service (Cartesia)
    cartesia_api_key = os.getenv("CARTESIA_API_KEY")
    cartesia_voice_id = CARTESIA_VOICE_ID
    
    cartesia_tts: CartesiaTTSService | None = None
    if cartesia_api_key and cartesia_voice_id:
        try:
            cartesia_tts = CartesiaTTSService(
                api_key=cartesia_api_key,
                voice_id=cartesia_voice_id,
                model=CARTESIA_MODEL,
            )
            logger.info("Cartesia TTS enabled.")
        except Exception as exc:
            logger.error(f"Failed to initialize Cartesia TTS: {exc}")
            cartesia_tts = None
    else:
        logger.warning("Cartesia TTS not configured; CARTESIA_API_KEY and CARTESIA_WELCOME_VOICE_ID required.")
    
    if not cartesia_tts:
        raise RuntimeError(
            "Cartesia TTS is not configured correctly. Set CARTESIA_API_KEY and CARTESIA_WELCOME_VOICE_ID."
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
    }
    
    # Create pipeline
    pipeline = Pipeline(
        [
            transport.input(),  # Websocket input from Twilio
            stt,  # Speech-To-Text
            context_aggregator.user(),
            llm,  # LLM
            cartesia_tts,  # Text-To-Speech (Cartesia)
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
                await asyncio.sleep(2)
                aggregated_messages = context.get_messages()
                if not aggregated_messages:
                    continue
                
                # Get latest user message
                user_messages = [m["content"] for m in aggregated_messages if m.get("role") == "user"]
                if not user_messages:
                    continue
                
                latest_user_text = user_messages[-1]
                
                # Extract case number if not already collected
                if not conversation_state["case_number_collected"]:
                    case_number = extract_case_number(latest_user_text)
                    if case_number:
                        conversation_state["case_number"] = case_number
                        conversation_state["case_number_collected"] = True
                
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
                
                # Route to LangGraph for policy decisions if inquiry not yet processed
                if not conversation_state["inquiry_processed"]:
                    try:
                        # Run LangGraph with the user's inquiry (not async, so no await)
                        result = run_graph(
                            user_input=latest_user_text,
                            case_number=conversation_state.get("case_number"),
                            call_sid=call_sid,
                        )
                        
                        conversation_state["inquiry_processed"] = True
                        escalated = result.get("escalated", False)
                        conversation_state["escalated"] = escalated
                        
                        # If escalation succeeded, stop the bot immediately
                        if escalated:
                            logger.info("Escalation successful - stopping bot pipeline")
                            # Send EndFrame to stop the pipeline and allow transfer to proceed
                            await task.queue_frames([EndFrame()])
                            # Break out of monitoring loop since call is being transferred
                            break
                        
                        # If LangGraph generated a response, inject it into the conversation
                        response_text = result.get("response_text")
                        if response_text:
                            logger.info(f"LangGraph response: {response_text}")
                            # Queue the response directly as a TextFrame to trigger TTS
                            # This ensures the response is spoken immediately
                            await task.queue_frames([TextFrame(text=response_text)])
                            
                    except Exception as e:
                        logger.error(f"Error in LangGraph processing: {e}", exc_info=True)
                
                # Check for escalation requests (only if not already processed)
                if not conversation_state["escalated"] and not conversation_state["escalation_processed"]:
                    escalation_keywords = [
                        "escalate", "agent", "human", "representative", "speak to someone",
                        "talk to a person", "transfer", "manager", "supervisor"
                    ]
                    if any(keyword in latest_user_text.lower() for keyword in escalation_keywords):
                        logger.info("Escalation requested by user")
                        # Mark as processed to prevent loops
                        conversation_state["escalation_processed"] = True
                        # Route to LangGraph for escalation decision
                        try:
                            result = run_graph(
                                user_input="I want to escalate my case to a human agent",
                                case_number=conversation_state.get("case_number"),
                                call_sid=call_sid,
                            )
                            escalated = result.get("escalated", False)
                            conversation_state["escalated"] = escalated
                            if escalated:
                                logger.info("Call escalated via LangGraph - stopping bot pipeline")
                                # Send EndFrame to stop the pipeline and allow transfer to proceed
                                await task.queue_frames([EndFrame()])
                                # Break out of monitoring loop since call is being transferred
                                break
                            else:
                                # Escalation was denied - speak the denial message
                                response_text = result.get("response_text")
                                if response_text:
                                    logger.info(f"Escalation denied - speaking response: {response_text}")
                                    await task.queue_frames([TextFrame(text=response_text)])
                        except Exception as e:
                            logger.error(f"Error in escalation: {e}", exc_info=True)
                
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

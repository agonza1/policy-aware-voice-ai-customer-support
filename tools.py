"""Backend actions and tools.

This module contains all backend actions that have side effects.
These tools are ONLY accessible through explicit LangGraph routing.
"""

import os
import re
from typing import Optional

from loguru import logger
from twilio.rest import Client


def get_base_url() -> str:
    """Get the base URL for TwiML endpoints.
    
    Uses BASE_URL environment variable if set, otherwise defaults to localhost.
    In production, this should be set to your public URL.
    """
    base_url = os.getenv("BASE_URL")
    if base_url:
        return base_url.rstrip("/")
    # Default to localhost for development
    return "http://localhost:8000"


def normalize_phone_number(phone_number: str) -> str:
    """Normalize phone number to E.164 format required by Twilio.
    
    Args:
        phone_number: Phone number in various formats (e.g., "8042221111", "+18042221111", "1-804-222-1111")
        
    Returns:
        Phone number in E.164 format (e.g., "+18042221111")
    """
    if not phone_number:
        return phone_number
    
    # Remove all non-digit characters except +
    cleaned = re.sub(r'[^\d+]', '', phone_number)
    
    # If it already starts with +, assume it's already in E.164 format
    if cleaned.startswith('+'):
        return cleaned
    
    # If it's 10 digits (US number without country code), add +1
    if len(cleaned) == 10:
        return f"+1{cleaned}"
    
    # If it's 11 digits starting with 1, add +
    if len(cleaned) == 11 and cleaned.startswith('1'):
        return f"+{cleaned}"
    
    # If it's already 11 digits with +1, return as-is (shouldn't happen after cleaning)
    # Otherwise, log warning and return with + prefix
    if len(cleaned) > 11:
        logger.warning(f"Phone number {phone_number} has unusual length after cleaning: {cleaned}")
    
    # Try to add +1 if it looks like a US number
    if cleaned.isdigit() and len(cleaned) >= 10:
        # Take last 10 digits and add +1
        last_10 = cleaned[-10:]
        return f"+1{last_10}"
    
    # Fallback: return with + prefix if it doesn't have one
    if not cleaned.startswith('+'):
        logger.warning(f"Could not normalize phone number {phone_number}, using as-is: {cleaned}")
        return f"+{cleaned}" if cleaned else phone_number
    
    return cleaned

# Initialize Twilio client
_twilio_client: Optional[Client] = None


def get_twilio_client() -> Client:
    """Get or create Twilio client."""
    global _twilio_client
    if _twilio_client is None:
        account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        if not account_sid or not auth_token:
            raise ValueError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN must be set")
        _twilio_client = Client(account_sid, auth_token)
    return _twilio_client


def get_case_status(case_number: str) -> dict:
    """Get case status (read-only operation).
    
    This is a mock implementation for PoC.
    In production, this would query a case management system.
    
    Args:
        case_number: The case number to look up
        
    Returns:
        dict: Case status information
    """
    logger.info(f"Looking up case status for case: {case_number}")
    
    # Mock case status for PoC
    # In production, this would query a real database/API
    mock_statuses = {
        "12345": {
            "case_number": "12345",
            "status": "open",
            "reason": "Awaiting customer response",
            "opened_date": "2024-01-15",
            "last_updated": "2024-01-20"
        },
        "VIP-001": {
            "case_number": "VIP-001",
            "status": "in_progress",
            "reason": "Technical review in progress",
            "opened_date": "2024-01-10",
            "last_updated": "2024-01-22"
        }
    }
    
    # Normalize case number for lookup (handle both VIP-001 and VIP001 formats)
    # Try exact match first
    status = mock_statuses.get(case_number)
    
    if not status:
        # Try normalized version (VIP001 -> VIP-001)
        normalized_case = case_number
        if case_number.upper().startswith("VIP") and "-" not in case_number:
            # Convert VIP001 to VIP-001 for lookup
            vip_match = re.match(r'(VIP)(\d+)', case_number.upper())
            if vip_match:
                normalized_case = f"{vip_match.group(1)}-{vip_match.group(2)}"
        
        status = mock_statuses.get(normalized_case)
    
    # If still not found, return default
    if not status:
        status = {
            "case_number": case_number,
            "status": "unknown",
            "reason": "Case not found in system",
            "opened_date": "unknown",
            "last_updated": "unknown"
        }
    
    logger.info(f"Case status retrieved: {status}")
    return status


def forward_call_to_agent(call_sid: str, support_phone_number: str) -> bool:
    """Forward a Twilio call to a human agent using TwiML Dial verb.
    
    This is a REAL side effect that transfers the call.
    This function MUST only be called from LangGraph escalation node.
    
    Args:
        call_sid: The Twilio Call SID to forward
        support_phone_number: The phone number to forward to
        
    Returns:
        bool: True if forwarding was successful, False otherwise
    """
    if not call_sid:
        logger.error("Cannot forward call: call_sid is missing")
        return False
    
    if not support_phone_number:
        logger.error("Cannot forward call: SUPPORT_PHONE_NUMBER is not configured")
        return False
    
    # Normalize phone number to E.164 format (required by Twilio)
    normalized_number = normalize_phone_number(support_phone_number)
    if normalized_number != support_phone_number:
        logger.info(f"Normalized phone number from {support_phone_number} to {normalized_number}")
    
    try:
        client = get_twilio_client()
        
        # First, verify the call exists and get its current status
        try:
            current_call = client.calls(call_sid).fetch()
            logger.info(f"Current call status before transfer: {current_call.status}")
            if current_call.status not in ['in-progress', 'ringing', 'queued']:
                logger.warning(f"Call {call_sid} is in status '{current_call.status}' - may not be able to transfer")
        except Exception as e:
            logger.error(f"Could not fetch call {call_sid} before transfer: {e}")
            return False
        
        # Use inline TwiML directly (simple approach like the example)
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Connecting you to one of our agents now. Please hold.</Say>
    <Dial>{normalized_number}</Dial>
</Response>"""
        
        logger.info(f"Updating call {call_sid} with inline transfer TwiML to {normalized_number}")
        logger.debug(f"TwiML being sent: {twiml}")
        
        # Update the call with inline TwiML - this redirects the call away from WebSocket
        call = client.calls(call_sid).update(twiml=twiml)
        
        # Verify the update was successful by checking call status
        # After update, the call should be in-progress or ringing
        call_status = call.status
        logger.info(f"Call {call_sid} update successful. Status: {call_status}. Forwarded to {normalized_number}")
        logger.info(f"Call will be redirected - WebSocket connection closing is expected behavior")
        
        # Verify the phone number format one more time
        if not normalized_number.startswith('+'):
            logger.error(f"Phone number {normalized_number} does not start with + - this may cause dialing issues")
            return False
        
        if len(normalized_number) < 10:
            logger.error(f"Phone number {normalized_number} seems too short - this may cause dialing issues")
            return False
        
        # Log additional call details for debugging (safely, non-fatal)
        # Only log safe attributes that we know exist
        try:
            call_to = getattr(call, 'to', 'N/A')
            call_direction = getattr(call, 'direction', 'N/A')
            logger.debug(f"Call details after update - To: {call_to}, Direction: {call_direction}")
        except Exception as e:
            # Non-fatal - just log and continue, don't let this affect the return value
            logger.debug(f"Could not log call details (non-fatal): {e}")
        
        # Return True - the call update was successful
        # The debug logging above is non-fatal and won't affect this return
        return True
        
    except Exception as e:
        logger.error(f"Error forwarding call {call_sid} to {support_phone_number}: {e}", exc_info=True)
        return False


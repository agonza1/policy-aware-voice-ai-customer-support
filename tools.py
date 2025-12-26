"""Backend actions and tools.

This module contains all backend actions that have side effects.
These tools are ONLY accessible through explicit LangGraph routing.
"""

import os
from typing import Optional

from loguru import logger
from twilio.rest import Client

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
    
    # Return mock data or default
    status = mock_statuses.get(
        case_number,
        {
            "case_number": case_number,
            "status": "unknown",
            "reason": "Case not found in system",
            "opened_date": "unknown",
            "last_updated": "unknown"
        }
    )
    
    logger.info(f"Case status retrieved: {status}")
    return status


def forward_call_to_agent(call_sid: str, support_phone_number: str) -> bool:
    """Forward an active Twilio call to a human agent.
    
    This is a REAL side effect that transfers the call.
    This function MUST only be called from LangGraph escalation node.
    
    Args:
        call_sid: The Twilio Call SID to forward
        support_phone_number: The phone number to forward to
        
    Returns:
        bool: True if forwarding was successful, False otherwise
    """
    logger.info(f"Forwarding call {call_sid} to agent at {support_phone_number}")
    
    try:
        client = get_twilio_client()
        call = client.calls(call_sid)
        
        # Update the call to redirect to the support number
        call.update(
            twiml=f'<Response><Dial>{support_phone_number}</Dial></Response>'
        )
        
        logger.info(f"Successfully forwarded call {call_sid} to {support_phone_number}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to forward call {call_sid}: {str(e)}")
        return False


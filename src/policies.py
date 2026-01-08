"""In-memory decision table for policy evaluation.

This module implements a simple, deterministic policy engine.
Missing rules default to deny (default-deny execution).
"""

from typing import Literal, Optional

# Policy decision types
Decision = Literal["allow_status", "allow_escalate", "deny"]
Intent = Literal["case_status", "escalate"]
AuthLevel = Literal["weak", "strong", "any"]


def evaluate_policy(intent: Intent, auth_level: AuthLevel) -> Decision:
    """Evaluate policy based on intent and auth level.
    
    Policy rules:
    - case_status + any auth_level → allow_status
    - escalate + weak auth_level → deny
    - escalate + strong auth_level → allow_escalate
    - Missing rule → deny (default-deny)
    
    Args:
        intent: The extracted intent from the user
        auth_level: The authentication level (simulated for PoC)
        
    Returns:
        Decision: allow_status, allow_escalate, or deny
    """
    # Policy decision table
    if intent == "case_status":
        return "allow_status"
    
    if intent == "escalate":
        if auth_level == "strong":
            return "allow_escalate"
        elif auth_level == "weak":
            return "deny"
    
    # Default-deny: missing rule or unknown combination
    return "deny"


def get_auth_level(case_number: Optional[str]) -> AuthLevel:
    """Simulate authentication level based on case number.
    
    For PoC purposes, this is a simple simulation:
    - Cases starting with "VIP" or "PRIORITY" → strong
    - All others → weak
    
    In production, this would query an auth service.
    
    Args:
        case_number: The case number to check
        
    Returns:
        AuthLevel: weak or strong
    """
    if not case_number:
        return "weak"
    
    case_upper = case_number.upper()
    if case_upper.startswith("VIP") or case_upper.startswith("PRIORITY"):
        return "strong"
    
    return "weak"


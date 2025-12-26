"""LangGraph state machine for policy enforcement.

This module implements the decision and execution plane using LangGraph.
It enforces default-deny execution - tools are unreachable unless explicitly routed.
"""

import json
import os
from typing import Annotated, Literal, Optional, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langsmith import traceable
from loguru import logger

from policies import Decision, evaluate_policy, get_auth_level
from prompts import INTENT_EXTRACTION_PROMPT
from tools import forward_call_to_agent, get_case_status


class GraphState(TypedDict):
    """State for the LangGraph state machine."""
    # Input
    user_input: str
    case_number: Optional[str]
    call_sid: Optional[str]
    
    # Extracted
    intent: Optional[Literal["case_status", "escalate"]]
    auth_level: Optional[Literal["weak", "strong", "any"]]
    
    # Decision
    decision: Optional[Decision]
    
    # Output
    response_text: Optional[str]
    escalated: bool


def extract_intent(state: GraphState) -> GraphState:
    """Extract intent from user input using LLM.
    
    LLM extracts intent only - no execution authority.
    """
    user_input = state.get("user_input", "")
    case_number = state.get("case_number")
    
    if not user_input:
        return {**state, "intent": None}
    
    # Initialize LLM for intent extraction
    llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.1)
    
    # Extract intent
    messages = [
        {"role": "system", "content": INTENT_EXTRACTION_PROMPT},
        {"role": "user", "content": user_input}
    ]
    
    try:
        response = llm.invoke(messages)
        content = response.content.strip()
        
        # Parse JSON response
        if content.startswith("```json"):
            content = content.replace("```json", "").replace("```", "").strip()
        elif content.startswith("```"):
            content = content.replace("```", "").strip()
        
        intent_data = json.loads(content)
        intent = intent_data.get("intent")
        
        logger.info(f"Extracted intent: {intent} from input: {user_input}")
        return {**state, "intent": intent}
        
    except Exception as e:
        logger.error(f"Failed to extract intent: {str(e)}")
        return {**state, "intent": None}


def evaluate_policy_node(state: GraphState) -> GraphState:
    """Evaluate policy and determine decision."""
    intent = state.get("intent")
    case_number = state.get("case_number")
    
    if not intent:
        logger.warning("No intent available for policy evaluation")
        return {**state, "decision": "deny"}
    
    # Get auth level
    auth_level = get_auth_level(case_number)
    
    # Evaluate policy
    decision = evaluate_policy(intent, auth_level)
    
    logger.info(f"Policy evaluation: intent={intent}, auth_level={auth_level}, decision={decision}")
    
    return {
        **state,
        "auth_level": auth_level,
        "decision": decision
    }


def route_decision(state: GraphState) -> Literal["status_node", "escalate_node", "deny_node"]:
    """Route to appropriate node based on decision."""
    decision = state.get("decision")
    
    if decision == "allow_status":
        return "status_node"
    elif decision == "allow_escalate":
        return "escalate_node"
    else:
        return "deny_node"


def status_node(state: GraphState) -> GraphState:
    """Handle case status lookup (read-only)."""
    case_number = state.get("case_number")
    
    if not case_number:
        return {
            **state,
            "response_text": "I need a case number to look up the status. Please provide your case number."
        }
    
    try:
        case_status = get_case_status(case_number)
        
        status = case_status.get("status", "unknown")
        reason = case_status.get("reason", "No reason available")
        
        response = f"Your case {case_number} is currently {status}. {reason}"
        
        logger.info(f"Case status retrieved: {response}")
        return {**state, "response_text": response}
        
    except Exception as e:
        logger.error(f"Failed to get case status: {str(e)}")
        return {
            **state,
            "response_text": "I'm sorry, I couldn't retrieve the case status at this time. Please try again later."
        }


def escalate_node(state: GraphState) -> GraphState:
    """Handle call escalation (REAL SIDE EFFECT)."""
    call_sid = state.get("call_sid")
    support_phone_number = os.getenv("SUPPORT_PHONE_NUMBER")
    
    if not call_sid:
        logger.error("Cannot escalate: no call_sid in state")
        return {
            **state,
            "response_text": "I'm sorry, I cannot escalate this call at this time.",
            "escalated": False
        }
    
    if not support_phone_number:
        logger.error("Cannot escalate: SUPPORT_PHONE_NUMBER not configured")
        return {
            **state,
            "response_text": "I'm sorry, escalation is not available at this time.",
            "escalated": False
        }
    
    try:
        success = forward_call_to_agent(call_sid, support_phone_number)
        
        if success:
            logger.info(f"Call {call_sid} successfully escalated")
            return {
                **state,
                "response_text": "I'm transferring you to a human agent now.",
                "escalated": True
            }
        else:
            logger.error(f"Failed to escalate call {call_sid}")
            return {
                **state,
                "response_text": "I'm sorry, I couldn't transfer you to an agent. Please try again later.",
                "escalated": False
            }
            
    except Exception as e:
        logger.error(f"Exception during escalation: {str(e)}")
        return {
            **state,
            "response_text": "I'm sorry, an error occurred while trying to escalate your call.",
            "escalated": False
        }


def deny_node(state: GraphState) -> GraphState:
    """Handle denied requests."""
    intent = state.get("intent")
    
    if intent == "escalate":
        response = "I'm sorry, I cannot escalate this case at this time. Please contact support through other channels."
    else:
        response = "I'm sorry, I cannot process that request."
    
    logger.info(f"Request denied: {response}")
    return {**state, "response_text": response}


def create_graph() -> StateGraph:
    """Create and configure the LangGraph state machine."""
    workflow = StateGraph(GraphState)
    
    # Add nodes
    workflow.add_node("extract_intent", extract_intent)
    workflow.add_node("evaluate_policy", evaluate_policy_node)
    workflow.add_node("status_node", status_node)
    workflow.add_node("escalate_node", escalate_node)
    workflow.add_node("deny_node", deny_node)
    
    # Set entry point
    workflow.set_entry_point("extract_intent")
    
    # Add edges
    workflow.add_edge("extract_intent", "evaluate_policy")
    workflow.add_conditional_edges(
        "evaluate_policy",
        route_decision,
        {
            "status_node": "status_node",
            "escalate_node": "escalate_node",
            "deny_node": "deny_node"
        }
    )
    
    # All nodes end
    workflow.add_edge("status_node", END)
    workflow.add_edge("escalate_node", END)
    workflow.add_edge("deny_node", END)
    
    return workflow.compile()


# Global graph instance
_graph = None


def get_graph():
    """Get or create the LangGraph instance."""
    global _graph
    if _graph is None:
        _graph = create_graph()
    return _graph


@traceable(name="policy_graph")
def run_graph(user_input: str, case_number: Optional[str] = None, call_sid: Optional[str] = None) -> dict:
    """Run the policy graph with given inputs.
    
    Args:
        user_input: The user's spoken input
        case_number: The case number (if collected)
        call_sid: The Twilio call SID
        
    Returns:
        dict: Graph execution result with response_text and escalated flag
    """
    graph = get_graph()
    
    initial_state: GraphState = {
        "user_input": user_input,
        "case_number": case_number,
        "call_sid": call_sid,
        "intent": None,
        "auth_level": None,
        "decision": None,
        "response_text": None,
        "escalated": False
    }
    
    try:
        result = graph.invoke(initial_state)
        logger.info(f"Graph execution completed: {result}")
        return result
    except Exception as e:
        logger.error(f"Graph execution failed: {str(e)}")
        return {
            **initial_state,
            "response_text": "I'm sorry, an error occurred while processing your request.",
            "escalated": False
        }


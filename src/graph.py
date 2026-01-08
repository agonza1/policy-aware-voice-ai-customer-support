"""LangGraph state machine for policy enforcement.

This module implements the decision and execution plane using LangGraph.
It enforces default-deny execution - tools are unreachable unless explicitly routed.
"""

import json
import os
import re
from typing import Annotated, Literal, Optional, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langsmith import traceable
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
from loguru import logger

from src.policies import Decision, evaluate_policy, get_auth_level
from src.prompts import INTENT_EXTRACTION_PROMPT
from src.tools import forward_call_to_agent, get_case_status

# Node name constants
NODE_EXTRACT_INTENT = "extract_intent"
NODE_EVALUATE_POLICY = "evaluate_policy"
NODE_STATUS = "status_node"
NODE_ESCALATE = "escalate_node"
NODE_DENY = "deny_node"

# Valid intent values
VALID_INTENTS = {"case_status", "escalate"}

# Configure Langfuse tracing if environment variables are set
# Use Langfuse's callback handler for proper LangChain integration
# IMPORTANT: Disable LANGCHAIN_TRACING_V2 to avoid LangSmith endpoint conflicts
_langfuse_handler = None


def _get_langfuse_host() -> str:
    """Determine Langfuse host based on environment.
    
    In Docker (detected via DOCKER env var or /.dockerenv), use service name.
    Otherwise, use localhost or configured host.
    """
    langfuse_host = os.getenv("LANGFUSE_HOST")
    
    if not langfuse_host:
        # Check if running in Docker
        is_docker = os.getenv("DOCKER") == "true" or os.path.exists("/.dockerenv")
        langfuse_host = "langfuse:3000" if is_docker else "localhost:3000"
    
    return langfuse_host


def _initialize_langfuse_handler() -> Optional[LangfuseCallbackHandler]:
    """Initialize Langfuse callback handler if configuration is available.
    
    Returns:
        LangfuseCallbackHandler if successfully initialized, None otherwise.
    """
    # Check if any Langfuse key is configured
    if not (os.getenv("LANGFUSE_SECRET_KEY") or os.getenv("LANGCHAIN_API_KEY")):
        return None
    
    # Disable LangSmith tracing (incompatible with Langfuse)
    os.environ.pop("LANGCHAIN_TRACING_V2", None)
    os.environ.pop("LANGCHAIN_ENDPOINT", None)
    
    # Get configuration
    langfuse_host = _get_langfuse_host()
    langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY") or os.getenv("LANGCHAIN_API_KEY")
    langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY") or os.getenv("LANGCHAIN_PUBLIC_KEY", "")
    project = os.getenv("LANGCHAIN_PROJECT") or os.getenv("LANGFUSE_PROJECT", "policy-aware-voice-ai")
    
    # Public key is REQUIRED
    if not langfuse_public_key:
        logger.warning(
            "LANGFUSE_PUBLIC_KEY not set! CallbackHandler requires both keys. "
            "Traces may not be sent. Set LANGCHAIN_PUBLIC_KEY or LANGFUSE_PUBLIC_KEY in .env"
        )
        return None
    
    # Set environment variables for Langfuse SDK (reads from env automatically)
    langfuse_url = f"http://{langfuse_host}"
    os.environ["LANGFUSE_SECRET_KEY"] = langfuse_secret_key
    os.environ["LANGFUSE_PUBLIC_KEY"] = langfuse_public_key
    os.environ["LANGFUSE_HOST"] = langfuse_url
    os.environ["LANGFUSE_PROJECT"] = project
    
    try:
        # Create callback handler - it will create internal Langfuse client from env vars
        handler = LangfuseCallbackHandler(public_key=langfuse_public_key)
        
        # IMPORTANT: The SDK may disable tracing during initialization if it can't verify credentials
        # (e.g., if Langfuse info endpoint is not available). We manually enable tracing
        # to ensure traces are sent even if the verification step fails.
        # Note: Accessing private attributes is fragile but necessary for Langfuse 2.40.0
        if hasattr(handler, 'client'):
            client = handler.client
            if hasattr(client, '_tracing_enabled'):
                if not client._tracing_enabled:
                    logger.warning(
                        f"Langfuse tracing was disabled during initialization. "
                        f"Manually enabling to ensure traces are sent. "
                        f"If traces don't appear, check Langfuse server at {langfuse_host}"
                    )
                    client._tracing_enabled = True
                else:
                    logger.info(f"Langfuse tracing enabled for project: {project}, host: {langfuse_host}")
            else:
                logger.info(f"Langfuse tracing configured for project: {project}, host: {langfuse_host}")
        else:
            logger.info(f"Langfuse tracing configured for project: {project}, host: {langfuse_host}")
        
        return handler
        
    except Exception as e:
        logger.error(f"Failed to initialize Langfuse: {str(e)}")
        return None


# Initialize Langfuse handler at module load time
_langfuse_handler = _initialize_langfuse_handler()

def get_langfuse_handler():
    """Get the Langfuse callback handler if configured."""
    return _langfuse_handler


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


def _parse_json_from_markdown(content: str) -> str:
    """Extract JSON from markdown code blocks.
    
    Handles various markdown formats:
    - ```json\n{...}\n```
    - ```\n{...}\n```
    - Plain JSON
    """
    # Remove markdown code blocks more reliably using regex
    content = re.sub(r'^```(?:json)?\s*', '', content, flags=re.MULTILINE)
    content = re.sub(r'\s*```$', '', content, flags=re.MULTILINE)
    return content.strip()


@traceable(name="extract_intent")
def extract_intent(state: GraphState) -> GraphState:
    """Extract intent from user input using LLM.
    
    LLM extracts intent only - no execution authority.
    """
    user_input = state.get("user_input", "")
    case_number = state.get("case_number")
    
    if not user_input:
        return {**state, "intent": None}
    
    # Get handler once to avoid double function call
    handler = get_langfuse_handler()
    callbacks = [handler] if handler else None
    
    # Initialize LLM for intent extraction
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, callbacks=callbacks)
    
    # Extract intent
    messages = [
        {"role": "system", "content": INTENT_EXTRACTION_PROMPT},
        {"role": "user", "content": user_input}
    ]
    
    try:
        response = llm.invoke(messages, config={"callbacks": callbacks})
        content = response.content.strip()
        
        # Parse JSON response (handles markdown code blocks)
        cleaned_content = _parse_json_from_markdown(content)
        intent_data = json.loads(cleaned_content)
        intent = intent_data.get("intent")
        
        # Validate intent against allowed values
        if intent not in VALID_INTENTS:
            logger.warning(f"Invalid intent extracted: {intent} from input: {user_input}")
            intent = None
        
        logger.info(f"Extracted intent: {intent} from input: {user_input}")
        return {**state, "intent": intent}
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from LLM response: {str(e)}. Content: {content[:100]}")
        return {**state, "intent": None}
    except Exception as e:
        logger.error(f"Failed to extract intent: {str(e)}")
        return {**state, "intent": None}


@traceable(name="evaluate_policy")
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
        return NODE_STATUS
    elif decision == "allow_escalate":
        return NODE_ESCALATE
    else:
        return NODE_DENY


@traceable(name="status_node")
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


@traceable(name="escalate_node")
def escalate_node(state: GraphState) -> GraphState:
    """Handle call escalation (REAL SIDE EFFECT)."""
    call_sid = state.get("call_sid")
    support_phone_number = os.getenv("SUPPORT_PHONE_NUMBER")
    auth_level = state.get("auth_level")
    
    logger.info(f"Escalation approved by policy (auth_level={auth_level})")
    
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
    workflow.add_node(NODE_EXTRACT_INTENT, extract_intent)
    workflow.add_node(NODE_EVALUATE_POLICY, evaluate_policy_node)
    workflow.add_node(NODE_STATUS, status_node)
    workflow.add_node(NODE_ESCALATE, escalate_node)
    workflow.add_node(NODE_DENY, deny_node)
    
    # Set entry point
    workflow.set_entry_point(NODE_EXTRACT_INTENT)
    
    # Add edges
    workflow.add_edge(NODE_EXTRACT_INTENT, NODE_EVALUATE_POLICY)
    workflow.add_conditional_edges(
        NODE_EVALUATE_POLICY,
        route_decision,
        {
            NODE_STATUS: NODE_STATUS,
            NODE_ESCALATE: NODE_ESCALATE,
            NODE_DENY: NODE_DENY
        }
    )
    
    # All nodes end
    workflow.add_edge(NODE_STATUS, END)
    workflow.add_edge(NODE_ESCALATE, END)
    workflow.add_edge(NODE_DENY, END)
    
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


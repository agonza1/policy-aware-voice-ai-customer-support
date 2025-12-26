"""Minimal unit tests for policy evaluation."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from policies import evaluate_policy, get_auth_level


def test_case_status_allowed():
    """Case status should be allowed for any auth level."""
    assert evaluate_policy("case_status", "weak") == "allow_status"
    assert evaluate_policy("case_status", "strong") == "allow_status"


def test_escalate_weak_denied():
    """Escalation should be denied for weak auth."""
    assert evaluate_policy("escalate", "weak") == "deny"


def test_escalate_strong_allowed():
    """Escalation should be allowed for strong auth."""
    assert evaluate_policy("escalate", "strong") == "allow_escalate"


def test_default_deny():
    """Unknown combinations should default to deny."""
    assert evaluate_policy("unknown_intent", "weak") == "deny"


def test_auth_level_vip():
    """VIP cases should have strong auth."""
    assert get_auth_level("VIP-001") == "strong"
    assert get_auth_level("vip-123") == "strong"


def test_auth_level_priority():
    """Priority cases should have strong auth."""
    assert get_auth_level("PRIORITY-001") == "strong"
    assert get_auth_level("priority-123") == "strong"


def test_auth_level_regular():
    """Regular cases should have weak auth."""
    assert get_auth_level("12345") == "weak"
    assert get_auth_level("ABC-123") == "weak"
    assert get_auth_level(None) == "weak"


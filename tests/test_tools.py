"""Minimal unit tests for backend tools."""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools import get_case_status


def test_get_case_status_existing():
    """Should return status for existing cases."""
    status = get_case_status("12345")
    assert status["case_number"] == "12345"
    assert status["status"] == "open"


def test_get_case_status_vip():
    """Should return status for VIP cases."""
    status = get_case_status("VIP-001")
    assert status["case_number"] == "VIP-001"
    assert status["status"] == "in_progress"


def test_get_case_status_unknown():
    """Should return unknown status for non-existent cases."""
    status = get_case_status("UNKNOWN-999")
    assert status["case_number"] == "UNKNOWN-999"
    assert status["status"] == "unknown"


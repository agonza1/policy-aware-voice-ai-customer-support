"""Simple test runner - run with: python tests/test_runner.py or pytest tests/"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from tests.test_policies import (
        test_auth_level_priority,
        test_auth_level_regular,
        test_auth_level_vip,
        test_case_status_allowed,
        test_default_deny,
        test_escalate_strong_allowed,
        test_escalate_weak_denied,
    )
    from tests.test_tools import (
        test_get_case_status_existing,
        test_get_case_status_unknown,
        test_get_case_status_vip,
    )
    TESTS = [
        test_case_status_allowed,
        test_escalate_weak_denied,
        test_escalate_strong_allowed,
        test_default_deny,
        test_auth_level_vip,
        test_auth_level_priority,
        test_auth_level_regular,
        test_get_case_status_existing,
        test_get_case_status_vip,
        test_get_case_status_unknown,
    ]
except ImportError as e:
    print(f"Import error: {e}")
    print("Note: Run tests with dependencies installed: pip install -e '.[dev]'")
    sys.exit(1)

if __name__ == "__main__":
    passed = 0
    failed = 0
    
    for test in TESTS:
        try:
            test()
            print(f"✓ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1
    
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed > 0 else 0)


# Tests

Minimal unit tests for core policy and tool logic.

## Run Tests

**With pytest (recommended):**
```bash
pytest tests/ -v
```

**With test runner:**
```bash
python tests/test_runner.py
```

**Policy tests only (no dependencies needed):**
```bash
python -c "import sys; sys.path.insert(0, '.'); from tests.test_policies import *; test_case_status_allowed(); print('✓')"
```

## Test Coverage

- **tests/test_policies.py**: Policy evaluation and auth level logic (7 tests)
- **tests/test_tools.py**: Case status lookup (3 tests)

Total: 10 minimal tests covering critical decision paths.


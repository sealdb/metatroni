#!/bin/bash
# Run Patroni tests with MySQL support and coverage reporting.
# Requires: pip install pymysql pytest-cov
python -m pytest tests/test_mysql.py tests/test_api.py tests/test_ha.py tests/test_validator.py \
    --cov=patroni --cov-report=term-missing --cov-report=html \
    -q --deselect tests/test_ha.py::TestHa::test_manual_failover_process_no_leader 2>&1 | tail -20
echo ""
echo "Coverage report: htmlcov/index.html"

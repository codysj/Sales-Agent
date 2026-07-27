"""Matrix Power Always-On AI Sales Agent backend.

Owns workflow state, scheduling, jobs, retries, approvals, policy enforcement, and
external execution (specification v0.3 §1.2, ADR-001). Runs as two processes over one
codebase and one database schema: an API process and a worker process (§18.1).

Module boundaries are defined in specification §18.2 and created by task T-005.
"""

# Kept in step with ``backend/pyproject.toml`` by ``tests/test_health.py``; it is reported in
# every log line and in the OpenAPI document, so drift would make both lie.
APP_VERSION = "0.1.0"

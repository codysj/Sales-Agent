"""Provider-neutral model gateway (specification §18.4, §10.4, GP-04, GP-14, ADR-017).

Owns the typed task interface, versioned JSON Schemas for model output, validation with bounded
retry then escalation to human review, ``ModelRun`` records with prompt/schema/model-config/policy
versions, deterministic budget enforcement, and the provider registry. Provider and model names
live in configuration, never in business logic. Only the deterministic fake exists until gate
**G-03** and `Q-012`.

Must not own: eligibility, approval, suppression, or execution (§5.1). Note the distinction §5.1
draws — the *provider adapter* owns none of the deterministic controls; the **gateway** enforces
budgets and schema validity before any adapter is invoked. Enforced by
``tests/test_module_boundaries.py``: this package imports no domain module, so it cannot reach the
rules it must not decide.
"""

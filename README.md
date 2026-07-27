# Sales-Agent

Matrix Power Always-On AI Sales Agent — an application-owned sales workflow for product-specific
prospecting, evidence-backed qualification, and human-approved outreach drafting.

A conventional FastAPI + PostgreSQL application owns workflow state, scheduling, jobs, retries,
approvals, policy enforcement, and external execution. A bounded, provider-neutral model gateway
handles research synthesis, classification, and drafting. An authenticated dashboard is the authority
for evidence review and exact approval. A WhatsApp/iMessage overlay and an optional isolated
OpenClaw/NemoClaw client are complementary and stay off the critical path.

> ⚠️ **Shadow mode. Live outreach is gated.** No email, message, CRM mutation, production credential,
> deployment, or LinkedIn automation is permitted until the corresponding gate in
> [tasks.md](tasks.md) §5 is explicitly unlocked. All data in this repository is synthetic.

## Status

Greenfield. Stage 1 (core shadow backend) is in progress; no application code exists yet.

| Document | Purpose |
|---|---|
| [docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md](docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md) | Authoritative specification (v0.3) — architecture, workflow, safety model, launch gates |
| [tasks.md](tasks.md) | Implementation backlog, stage gates, stakeholder-decision register, progress log |
| [process.md](process.md) | Development-loop operating procedure |
| [AGENTS.md](AGENTS.md) | Repository instructions and hard safety rules |

## License

Apache-2.0 — see [LICENSE](LICENSE).

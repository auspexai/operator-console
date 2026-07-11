# AuspexAI Operator Console

Private, auth-gated maintainer dashboard for [AuspexAI](https://github.com/auspexai) — a volunteer-driven, open-source distributed compute network for AI safety research.

## Status

**LIVE — deployed (v0.1.77).** The maintainer console runs against the live coordinator (default bind 127.0.0.1:4227). One of four Phase-1 UI surfaces per §5.18.

## Scope

The operator console is the **maintainer's union view**: see and intervene across experiments, fleet, receipts, alerts, and system health. Sibling Phase 1 UI surfaces — researcher dashboard, tenant onboarding form, public receipt verifier — are separate codebases per §5.18.

### What's live

- Experiments list + detail + lifecycle actions (pause / resume / abort / archive)
- Worker fleet view (connected, tier, capabilities, last-seen) + worker detail
- Alerts list + resolution
- System health (coordinator process, scheduler queue, DB connectivity)
- Approver review queue (Maintainer-as-Approver per §6.5 softer-floor-of-1)
- Live SSE streams for experiments + workers
- Receipt browser with COSE + in-toto + Rekor verification
- Audit log
- Historical experiment browser

## Stack

- **Frontend:** SvelteKit + TypeScript
- **Backend:** FastAPI (Python) — colocated with the frontend for harness invocation, key signing, and SSE proxying. Speaks to the coordinator daemon via the published HTTP API contract; never deployed standalone.
- **Auth:** maintainer bearer token (Phase 1) → OAuth Device Flow (Phase 2-3)

## Development

The Python backend lives in `backend/`. Quick start:

```bash
cd backend
pip install -e ".[dev]"
auspexai-operator-console serve         # binds 127.0.0.1:4227
```

## License

[Apache-2.0](LICENSE) — matches the [tenant SDK](https://github.com/auspexai/tenant-sdk) per the Q16 SDK boundary precedent. The operator console consumes the coordinator's published HTTP API contract; it is not a platform internal.

## Governance & policies

- [Governance](https://github.com/auspexai/.github/blob/main/GOVERNANCE.md) — roles, decision rules, recruitment, conflict of interest
- [Code of Conduct](https://github.com/auspexai/.github/blob/main/CODE_OF_CONDUCT.md) — community standards, reporting, escalation pathway
- [Contributing](https://github.com/auspexai/.github/blob/main/CONTRIBUTING.md) — DCO sign-off, PR workflow, RFC requirement for substantial architectural changes
- [Research Ethics Policy](https://github.com/auspexai/.github/blob/main/RESEARCH_ETHICS_POLICY.md) — what AI safety research can run on the network and how it's reviewed

## Watch this repo

The console is live in open beta against the running coordinator. Issues and discussion welcome.

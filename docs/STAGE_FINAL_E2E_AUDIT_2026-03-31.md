# Stage Final E2E Audit

Date: `2026-03-31`

Purpose:
- identify the screens that are strongest for the final competition stage
- verify them against the live local stack
- seed missing data where the screen story was weak
- separate primary demo screens from reserve-only screens

## Primary Screen Path

Use this live order:

1. `C1 Command`
2. `S7 Dashboard`
3. `S1 Live Feed`
4. `S2 Threat Graph`
5. `S3 Investigate`
6. `S6 Defense`
7. `A6 Federation`

Why this path:
- it tells the national story first
- it proves the platform is alive
- it shows real signals, graph correlation, explainable AI, bounded response, and cross-agency value
- it avoids the slowest or most fragile interactions

## Browser-Validated Screens

These passed live browser smoke checks after the audit:

- `C1 Command`
- `S1 Live Feed`
- `S2 Threat Graph`
- `S4 Campaigns`
- `S6 Defense`
- `A6 Federation`

`A5 Corruption Intel` is now data-backed and presentation-safe, but it may briefly show a syncing state right after sign-in. That screen was hardened so it no longer opens with a misleading all-zero operational summary while feeds are still loading.

## API-Validated Screens

These were verified directly through the live backend:

- `S7 Dashboard`
  - events around `83k`
  - graph deltas around `52k`
  - anomalies `110`
  - mitigations `473`

- `S3 Investigate`
  - strong live GNN prediction present for `ip:50.16.16.211`
  - current score observed around `67.11`
  - reason codes include campaign linkage and elevated GNN risk

- `A5 Corruption Intel`
  - procurement anomaly seeded and verified:
    - `TND-KE-2026-0001`
    - vendor `vendor-axon`
    - agency `KEMSA`
    - amount `KES 125,000,000`
    - score `1.0`
    - severity `critical`
  - guardrail decision seeded and verified:
    - decision `block`
    - actions include anti-fraud review, ownership validation, and audit escalation
  - integrity alert seeded and verified through legal grant flow:
    - source `ifmis`
    - record `INV-9001`
    - alert type `RECORD_DELETION`
    - severity `high`
    - confidence `0.9`
    - status `open`

## Cross-Agency Demo Status

Federation remains one of the strongest final-stage differentiators.

Verified scenarios:
- `federated_vpn`
- `federated_sim_swap`
- `federated_malware`

These are appropriate for the final-stage rubric because they make the national coordination value visible.

## Reserve Screens

Use these only when asked:

- `A3 GNN Intelligence`
  - strong for explaining model governance and how AI is actually used
  - not a good opening screen

- `A5 Corruption Intel`
  - now credible and data-backed
  - good for ethics, public trust, and national-integrity discussions
  - better as a reserve screen than as the first operational proof

## Screens / Interactions To Avoid As Primary Live Clicks

- `S8 Reports` preview path
  - backend generate API is healthy
  - the browser preview path is still too slow / inconsistent to treat as a primary stage click
  - keep Reports as a reserve screen or pre-open it if needed

- `S5 Cases`
  - useful, but not as strong as Investigate or Defense for the final stage

## Final Recommendation

If the goal is position `1`, do not try to show everything.

Show:
- national command
- proof the platform is alive
- real incoming cyber signal
- graph correlation
- explainable AI prioritization
- bounded containment
- cross-agency federation

Then keep corruption and GNN governance for questions.

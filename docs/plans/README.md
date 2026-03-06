# Change Planning Protocol

Use this folder for any non-trivial change before or during implementation.

## When a plan file is required

Create/update a plan file in `docs/plans/` when a PR has one or more:

- broad scope (many files/modules)
- high churn (large line delta)
- architecture changes
- security/auth changes
- data/ML pipeline contract changes

## Why this matters

- lowers rework by forcing scope clarity up front
- improves review quality
- creates an audit trail of intended vs delivered behavior

## Naming

Use one of:

- `YYYY-MM-DD-short-topic.md`
- `ticket-id-short-topic.md`

## Minimum structure

1. Problem and objective
2. Scope in / scope out
3. Proposed design
4. Risks and rollback
5. Test and evidence plan
6. Completion checklist

Start from `_TEMPLATE.md`.


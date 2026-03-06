# Engineering Workflow Guardrails

This workflow addresses two quality risks:

- missing code review discipline
- high churn rework

## 1) Review policy

Repository settings should enforce:

1. Pull requests required for `main`
2. At least 1 approval before merge
3. Require Code Owner review
4. Require status checks:
   - `Sentinel-KE CI`
   - `Repository Health`
   - `PR Guardrails`

`CODEOWNERS` is defined in `.github/CODEOWNERS`.

## 2) Planning policy

For medium/large changes:

1. Create a plan doc in `docs/plans/`
2. Link it in PR template section `Planned work link`
3. Keep scope strict (`In scope` / `Out of scope`)

Template: `docs/plans/_TEMPLATE.md`

## 3) Churn guardrails

Workflow: `.github/workflows/pr-guardrails.yml`  
Script: `scripts/pr_guardrails.py`

Current thresholds:

- line churn > 1600 requires a plan doc update
- file span > 60 requires a plan doc update
- code churn > 300 with backend/frontend changes requires test updates

## 4) Expected outcome

- smaller, reviewable PR slices
- fewer rollback fixes
- improved quality score stability across commits


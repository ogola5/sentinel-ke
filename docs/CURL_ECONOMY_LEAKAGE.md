# Economy Leakage / Guardrail CURL Tests

Base URL:
```bash
export BASE_URL="http://localhost:8000"
export API_KEY="change-me-frontend-key"
```

## 1) Seed procurement anomalies

Run this three to five times with different `tender_id` and similar amounts to trigger split-tender and concentration patterns.

```bash
curl -sS -X POST "$BASE_URL/v1/economy/procurement/analyze" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "tender_id": "T-LEAK-001",
    "vendor_id": "V-CAPTURE-01",
    "project_id": "P-ALPHA",
    "agency": "min-finance",
    "sector": "public",
    "amount": 930000,
    "baseline_amount": 650000,
    "currency": "KES",
    "competitive_bids": 1,
    "vendor_award_count_90d": 5,
    "single_source": true,
    "change_order_count": 2
  }'
```

Example high change-order inflation record:
```bash
curl -sS -X POST "$BASE_URL/v1/economy/procurement/analyze" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "tender_id": "T-LEAK-CO-001",
    "vendor_id": "V-CAPTURE-01",
    "project_id": "P-BETA",
    "agency": "min-finance",
    "sector": "public",
    "amount": 2200000,
    "baseline_amount": 1300000,
    "currency": "KES",
    "competitive_bids": 1,
    "vendor_award_count_90d": 5,
    "single_source": true,
    "change_order_count": 4
  }'
```

## 2) Guardrail decision endpoint

```bash
curl -sS -X POST "$BASE_URL/v1/economy/guardrail/evaluate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "tender_id": "T-GUARD-001",
    "vendor_id": "V-CAPTURE-01",
    "project_id": "P-GAMMA",
    "agency": "min-finance",
    "sector": "public",
    "amount": 1800000,
    "baseline_amount": 900000,
    "currency": "KES",
    "competitive_bids": 1,
    "vendor_award_count_90d": 6,
    "single_source": true,
    "change_order_count": 3
  }'
```

List decisions:
```bash
curl -sS "$BASE_URL/v1/economy/guardrail/decisions?agency=min-finance&min_score=0.5" \
  -H "X-API-Key: $API_KEY"
```

## 3) Tamper/deletion integrity snapshots

Initial snapshot:
```bash
curl -sS -X POST "$BASE_URL/v1/economy/integrity/snapshot" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "source_system": "ifmis",
    "record_type": "invoice",
    "record_id": "INV-9001",
    "payload": {"amount": 1500000, "status": "posted"},
    "actor_id": "sync-service"
  }'
```

Delete snapshot (should trigger deletion alert):
```bash
curl -sS -X POST "$BASE_URL/v1/economy/integrity/snapshot" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{
    "source_system": "ifmis",
    "record_type": "invoice",
    "record_id": "INV-9001",
    "is_deleted": true,
    "actor_id": "unknown-user"
  }'
```

List integrity alerts:
```bash
curl -sS "$BASE_URL/v1/economy/integrity/alerts?source_system=ifmis&status=open" \
  -H "X-API-Key: $API_KEY"
```

## 4) Run leakage detection and query outputs

Run:
```bash
curl -sS -X POST "$BASE_URL/v1/economy/leakage/run?window_days=30" \
  -H "X-API-Key: $API_KEY"
```

List alerts:
```bash
curl -sS "$BASE_URL/v1/economy/leakage/alerts?agency=min-finance" \
  -H "X-API-Key: $API_KEY"
```

Summary:
```bash
curl -sS "$BASE_URL/v1/economy/leakage/summary?window_days=30" \
  -H "X-API-Key: $API_KEY"
```

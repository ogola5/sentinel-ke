# Sentinel-KE Frontend

This frontend is wired to consume real backend APIs from `backend/app/main.py`.
It no longer uses bundled demo data as runtime fallback.

## Local Backend Wiring

Default API base behavior:

- `VITE_API_BASE_URL` set: frontend calls that URL.
- no env var and running on localhost: frontend defaults to `http://localhost:8000`.

The app calls these backend routes:

- `/ready`, `/health`
- `/v1/events/*`, `/v1/ddos/*`, `/v1/campaigns/*`, `/v1/infra/*`
- `/v1/cases/*`, `/v1/stix/*`
- `/v1/metrics`, `/v1/anomalies`, `/v1/mitigations/*`
- `/v1/ai/*`, `/v1/economy/*`

## Auth Headers

Requests support:

- `X-API-Key`
- `Authorization: Bearer <token>`
- `X-Legal-Grant-Token` and `X-Legal-Target` (for legal-gated economy routes)

You can provide these via:

- Vite env variables (`VITE_API_KEY`, `VITE_ACCESS_TOKEN`, `VITE_LEGAL_GRANT_TOKEN`, `VITE_LEGAL_TARGET`)
- the in-app **API Credentials** panel (stored in browser localStorage)

## Run

```bash
npm run dev
```

## Quality Check

```bash
npm run build
```

# Auth Hardening Runbook

This runbook covers the hardened authentication flow now implemented in backend:

- Bearer token takes priority over API key.
- Central routes reject service/development principals unless explicitly enabled.
- Central users can be forced to enroll MFA before login succeeds.
- Intrusion guard blocks brute-force / credential-stuffing patterns.
- Breakglass developer access exists, but is disabled by default and gated.

## 1) Required env settings

Set these in your backend runtime (compose env, `.env`, or deployment secret manager):

```bash
AUTH_ENABLED=true
AUTH_CENTRAL_MFA_REQUIRED=true
AUTH_CENTRAL_MFA_ENROLLMENT_REQUIRED=true
AUTH_SERVICE_CENTRAL_ACCESS=false

AUTH_INTRUSION_WINDOW_MINUTES=15
AUTH_INTRUSION_MAX_FAILURES_PER_IP=20
AUTH_INTRUSION_MAX_FAILURES_PER_USERNAME=8
AUTH_INTRUSION_MIN_DISTINCT_USERNAMES=5

# breakglass (recommended dev-only)
AUTH_BREAKGLASS_ENABLED=false
AUTH_BREAKGLASS_LOCAL_ONLY=true
AUTH_BREAKGLASS_ALLOW_IN_PRODUCTION=false
AUTH_BREAKGLASS_USERNAME=dev-breakglass
```

## 2) Configure breakglass password safely (optional)

Use hash mode so raw password is not stored in env:

```bash
export BREAKGLASS_PLAIN='replace-with-long-random-secret'
export AUTH_BREAKGLASS_PASSWORD_SHA3_512="$(python3 - <<'PY'
import hashlib, os
print(hashlib.sha3_512(os.environ['BREAKGLASS_PLAIN'].encode('utf-8')).hexdigest())
PY
)"
```

Then set:

```bash
AUTH_BREAKGLASS_ENABLED=true
AUTH_BREAKGLASS_PASSWORD_SHA3_512=<value-from-command-above>
AUTH_BREAKGLASS_PASSWORD=
```

## 3) Validate central API-key restriction

With `AUTH_SERVICE_CENTRAL_ACCESS=false`, API key alone cannot call central routes:

```bash
curl -sS -i \
  -H "X-API-Key: $FRONTEND_API_KEY" \
  http://localhost:8000/v1/auth/users
```

Expected: `403` with `central_user_session_required`.

## 4) Validate bearer precedence over API key

```bash
ACCESS_TOKEN="<valid-user-access-token>"
curl -sS \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "X-API-Key: $FRONTEND_API_KEY" \
  http://localhost:8000/v1/auth/me
```

Expected: authenticated user principal (`principal_type=user`), not service principal.

## 5) Validate central MFA enrollment enforcement

Try login for a central user with MFA not enrolled:

```bash
curl -sS -X POST http://localhost:8000/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{
    "username":"central-admin",
    "password":"<central-password>"
  }'
```

Expected: `403` with `mfa_enrollment_required`.

## 6) Validate intrusion guard

Generate repeated failed logins (same username or spray from one IP):

```bash
for i in $(seq 1 10); do
  curl -sS -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"central-admin","password":"wrong-password"}'
done
```

Expected: initially `401`/`423`, then `429` (`source_temporarily_blocked`) once thresholds are crossed.

## 7) Validate breakglass (dev emergency path)

Only works when enabled and allowed by env policy:

```bash
curl -sS \
  -H "X-Breakglass-Password: $BREAKGLASS_PLAIN" \
  http://localhost:8000/v1/auth/me
```

Expected:

- `200` with `principal_type=breakglass` if allowed.
- `403 breakglass_not_enabled` if disabled.
- `403 breakglass_local_only` if called remotely while local-only is enabled.

## 8) Post-change checks in DB

```bash
docker compose exec -T postgres psql -U sentinel -d sentinel -c \
"SELECT outcome, reason, count(*) FROM auth_login_event GROUP BY outcome, reason ORDER BY count(*) DESC;"
```

Use this to confirm:

- `blocked` events appear during brute-force tests.
- `mfa_enrollment_required` appears for central users without MFA.
- breakglass usage can be audited from request logs (`auth_breakglass_used`).

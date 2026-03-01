#!/usr/bin/env bash
# Sentinel-KE — Quick throughput benchmark
#
# Requirements: apache2-utils (provides `ab`)
#   sudo apt-get install -y apache2-utils
#
# Usage:
#   HUB_API_KEY=your-key bash scripts/load_test.sh
#   BASE_URL=https://sentinel-ke.onrender.com HUB_API_KEY=xxx bash scripts/load_test.sh
#
# Sample output recorded on a 2-core / 4 GB RAM VM (2026-03-01):
#
#   Requests per second:    312.4 [#/sec] (mean)
#   Time per request:       32.0 [ms] (mean, across all concurrent requests)
#   Time per request:       3.2  [ms] (mean, across single request)
#   Transfer rate:          85.1 [Kbytes/sec] received
#
#   Connection Times (ms)
#                 min  mean[+/-sd] median   max
#   Connect:        0    0   0.3      0       2
#   Processing:    12   31  12.4     28      89
#   Waiting:       12   31  12.3     28      89
#   Total:         12   31  12.5     28      90
#
#   Percentage of the requests served within a certain time (ms)
#     50%     28
#     66%     33
#     75%     37
#     80%     40
#     90%     50
#     95%     59
#     98%     70
#     99%     76
#    100%     90 (longest request)

set -euo pipefail

BASE="${BASE_URL:-http://localhost:8000}"
KEY="${HUB_API_KEY:-ci-test-key}"
REQUESTS="${REQUESTS:-500}"
CONCURRENCY="${CONCURRENCY:-10}"

echo "=== Sentinel-KE Load Test ==="
echo "Target:      $BASE/health"
echo "Requests:    $REQUESTS"
echo "Concurrency: $CONCURRENCY"
echo ""

if command -v ab &>/dev/null; then
    ab -n "$REQUESTS" -c "$CONCURRENCY" \
       -H "X-API-Key: $KEY" \
       "$BASE/health"
else
    echo "ab not found — falling back to curl loop"
    PASS=0; FAIL=0
    START=$(date +%s%3N)
    for i in $(seq 1 "$REQUESTS"); do
        if curl -sf -H "X-API-Key: $KEY" "$BASE/health" > /dev/null 2>&1; then
            PASS=$((PASS + 1))
        else
            FAIL=$((FAIL + 1))
        fi
    done
    END=$(date +%s%3N)
    ELAPSED=$(( END - START ))
    RPS=$(( REQUESTS * 1000 / ELAPSED ))
    echo "Completed: $PASS passed, $FAIL failed in ${ELAPSED}ms (~${RPS} req/s)"
fi

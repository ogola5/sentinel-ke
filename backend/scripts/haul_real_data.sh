#!/usr/bin/env bash
# =============================================================================
# haul_real_data.sh — SentinelKE Real-Data Heavy Haul
# Downloads and ingests all open real-world datasets into the pipeline.
#
# Usage (inside backend container or local venv):
#   INGEST_API_KEY=<your-key> bash scripts/haul_real_data.sh
#
# Optional env overrides:
#   DATA_DIR         — where to store downloaded files   (default: /tmp/sentinel_haul)
#   OTX_API_KEY      — AlienVault OTX key (get free at otx.alienvault.com)
#   URLHAUS_AUTH_KEY — URLhaus key (register free at abuse.ch)
#   PAYSIM_CSV       — path to already-downloaded PaySim CSV (skip Kaggle download prompt)
#   PPRA_CSV         — path to already-downloaded PPRA CSV   (skip curl download)
#   UNSW_CSV         — path to already-downloaded UNSW-NB15 CSV
#   SKIP_FEODO       — set to 1 to skip
#   SKIP_KEV         — set to 1 to skip
#   SKIP_OTX         — set to 1 to skip
#   SKIP_URLHAUS     — set to 1 to skip
#   SKIP_CIC         — set to 1 to skip CIC-IDS2018 (large AWS download)
#   SKIP_PAYSIM      — set to 1 to skip
#   SKIP_PPRA        — set to 1 to skip
#   SKIP_UNSW        — set to 1 to skip
# =============================================================================

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
# Each source has its own registered API key in the source_registry table.
# These must match what seed_sources.py writes to Postgres (read from .env).
# Fallback to INGEST_API_KEY if a specific key is not set.
INGEST_API_KEY="${INGEST_API_KEY:-a488444a8f1f676715b503a9326a307b36ec575d483c33ce}"
FEODO_SOURCE_API_KEY="${FEODO_SOURCE_API_KEY:-d6c42c36bfe70bc8aff1113e544dff11e96b9d521c64c719}"
URLHAUS_SOURCE_API_KEY="${URLHAUS_SOURCE_API_KEY:-2ce8ef011178e0850d7eb3aa9d4b058c3c842a230c76f6c1}"
OTX_SOURCE_API_KEY="${OTX_SOURCE_API_KEY:-${OTX_API_KEY:-766244cbed3884485db14c711bcfc933bf3e916373a18f9d6c04cc55c7c7eb52}}"
PPRA_SOURCE_API_KEY="${PPRA_SOURCE_API_KEY:-cf2bc3a7d0656a4b8037ad1b2dbc704b234326f8adfcffad}"
PAYSIM_SOURCE_API_KEY="${PAYSIM_SOURCE_API_KEY:-f80e6fb8df01f07cb810099b8b7ecbe22c7d44ba8fb13c83}"
UNSW_SOURCE_API_KEY="${UNSW_SOURCE_API_KEY:-30b7fa8e9c7646ab34e4a061ebc24ab79cb7b3e04a182bed}"

DATA_DIR="${DATA_DIR:-/tmp/sentinel_haul}"
CLASSIFICATION="RESTRICTED"
BASE_PIPELINE="python -m app.integrations.real_data_pipeline --classification ${CLASSIFICATION}"

# ── Colours ─────────────────────────────────────────────────────────────────
G="\033[0;32m"; Y="\033[0;33m"; R="\033[0;31m"; B="\033[0;34m"; NC="\033[0m"
info()    { echo -e "${B}[haul]${NC} $*"; }
ok()      { echo -e "${G}[ok]${NC}   $*"; }
warn()    { echo -e "${Y}[skip]${NC} $*"; }
fail()    { echo -e "${R}[fail]${NC} $*"; }
section() { echo -e "\n${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; \
            echo -e "${B}  $*${NC}"; \
            echo -e "${B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }

mkdir -p "${DATA_DIR}"
TOTAL_ACCEPTED=0
TOTAL_ERRORS=0

run_job() {
    # run_job <label> <source-api-key> <pipeline-args...>
    local label="$1"; shift
    local key="$1"; shift
    info "Running: ${label}"
    local result exit_code
    result=$(${BASE_PIPELINE} --source-api-key "${key}" "$@" 2>&1)
    exit_code=$?
    # Extract JSON summary from last line of output (pipeline always ends with JSON)
    local json_line accepted errors
    json_line=$(echo "$result" | grep -o '{.*"job".*}' | tail -1)
    accepted=$(echo "$json_line" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('accepted',0))" 2>/dev/null || echo 0)
    errors=$(echo "$json_line"   | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('errors',0))"   2>/dev/null || echo 0)
    TOTAL_ACCEPTED=$((TOTAL_ACCEPTED + accepted))
    TOTAL_ERRORS=$((TOTAL_ERRORS + errors))
    if [[ "${exit_code}" -eq 0 ]]; then
        ok "${label}: accepted=${accepted} errors=${errors}"
    else
        fail "${label} finished with errors — output:"
        echo "$result" | tail -20
        TOTAL_ERRORS=$((TOTAL_ERRORS + 1))
    fi
}

# =============================================================================
# 1. Feodo Tracker — live botnet C2 feed (CC0, no auth)
# =============================================================================
section "1/8  Feodo Tracker C2 Botnet Feed"
if [[ "${SKIP_FEODO:-0}" == "1" ]]; then
    warn "SKIP_FEODO=1, skipping"
else
    FEODO_FILE="${DATA_DIR}/feodo_ipblocklist.json"
    # Try curl first; if unavailable (e.g. inside Docker) let Python pipeline fetch directly
    if command -v curl &>/dev/null; then
        info "Downloading Feodo blocklist via curl…"
        curl -sSfL "https://feodotracker.abuse.ch/downloads/ipblocklist_recommended.json" \
            -o "${FEODO_FILE}" && ok "Downloaded ${FEODO_FILE}"
        run_job "feodo" "${FEODO_SOURCE_API_KEY}" feodo --feodo-file "${FEODO_FILE}"
    elif command -v wget &>/dev/null; then
        info "Downloading Feodo blocklist via wget…"
        wget -q "https://feodotracker.abuse.ch/downloads/ipblocklist_recommended.json" \
            -O "${FEODO_FILE}" && ok "Downloaded ${FEODO_FILE}"
        run_job "feodo" "${FEODO_SOURCE_API_KEY}" feodo --feodo-file "${FEODO_FILE}"
    else
        info "curl/wget not found — Python pipeline will fetch Feodo live via requests"
        run_job "feodo" "${FEODO_SOURCE_API_KEY}" feodo
    fi
fi

# =============================================================================
# 2. CISA KEV + FIRST EPSS — known exploited vulnerabilities (public domain)
# =============================================================================
section "2/8  CISA Known Exploited Vulnerabilities (KEV + EPSS)"
if [[ "${SKIP_KEV:-0}" == "1" ]]; then
    warn "SKIP_KEV=1, skipping"
else
    # ke-gov-infra is our symbolic asset representing national infrastructure
    # KEV is an OSINT source — use the feodo_live source key (same OSINT category)
    run_job "kev-epss" "${FEODO_SOURCE_API_KEY}" kev-epss --asset-id "ke-gov-infra" \
        --sleep-every 450 --sleep-sec 65
fi

# =============================================================================
# 3. URLhaus — malware URL feed (requires free abuse.ch auth key)
# =============================================================================
section "3/8  URLhaus Malware URL Feed"
if [[ "${SKIP_URLHAUS:-0}" == "1" ]]; then
    warn "SKIP_URLHAUS=1, skipping"
elif [[ -z "${URLHAUS_AUTH_KEY:-}" ]]; then
    warn "URLHAUS_AUTH_KEY not set — skipping URLhaus"
    warn "  Register free at https://urlhaus.abuse.ch/ and set URLHAUS_AUTH_KEY=<key>"
else
    URLHAUS_FILE="${DATA_DIR}/urlhaus_online.csv"
    info "Downloading URLhaus online CSV…"
    curl -sSfL "https://urlhaus.abuse.ch/downloads/csv_online/" \
        --data "auth-key=${URLHAUS_AUTH_KEY}" \
        -o "${URLHAUS_FILE}" && ok "Downloaded ${URLHAUS_FILE}"
    run_job "urlhaus" "${URLHAUS_SOURCE_API_KEY}" urlhaus --urlhaus-file "${URLHAUS_FILE}"
fi

# =============================================================================
# 4. AlienVault OTX — threat intelligence indicators (free API key)
# =============================================================================
section "4/8  AlienVault OTX Threat Intel"
if [[ "${SKIP_OTX:-0}" == "1" ]]; then
    warn "SKIP_OTX=1, skipping"
elif [[ -z "${OTX_API_KEY:-}" ]]; then
    warn "OTX_API_KEY not set — skipping OTX"
    warn "  Get free key at https://otx.alienvault.com and set OTX_API_KEY=<key>"
else
    run_job "otx" "${OTX_SOURCE_API_KEY}" otx \
        --otx-api-key "${OTX_API_KEY}" \
        --limit 200 \
        --threat-source "alienvault_otx"
fi

# =============================================================================
# 5. Kenya PPRA Open Contracting Dataset (open government data)
#    Download: https://data.open-contracting.org/en/publication/147/download
#    ~51 MB CSV  |  242K tenders  |  105K contracts  |  July 2018–Feb 2026
# =============================================================================
section "5/8  Kenya PPRA Open Contracting Procurement Data"
if [[ "${SKIP_PPRA:-0}" == "1" ]]; then
    warn "SKIP_PPRA=1, skipping"
else
    if [[ -n "${PPRA_CSV:-}" && -f "${PPRA_CSV}" ]]; then
        PPRA_FILE="${PPRA_CSV}"
        ok "Using provided PPRA file: ${PPRA_FILE}"
    else
        PPRA_FILE="${DATA_DIR}/ppra_ke_contracts.csv"
        info "Downloading Kenya PPRA OCDS CSV (~51 MB)…"
        _ppra_download_ok=0
        if command -v curl &>/dev/null; then
            curl -sSfL \
                "https://data.open-contracting.org/en/publication/147/download?format=csv" \
                -o "${PPRA_FILE}" && _ppra_download_ok=1
        elif command -v wget &>/dev/null; then
            wget -q "https://data.open-contracting.org/en/publication/147/download?format=csv" \
                -O "${PPRA_FILE}" && _ppra_download_ok=1
        else
            # Use Python requests as fallback
            python3 -c "
import requests, sys
url='https://data.open-contracting.org/en/publication/147/download?format=csv'
r=requests.get(url, timeout=120, stream=True)
r.raise_for_status()
with open('${PPRA_FILE}','wb') as f:
    for chunk in r.iter_content(65536): f.write(chunk)
" && _ppra_download_ok=1
        fi
        if [[ "${_ppra_download_ok}" == "1" ]]; then
            ok "Downloaded ${PPRA_FILE}"
        else
            fail "PPRA download failed. Download manually from:"
            fail "  https://data.open-contracting.org/en/publication/147/download"
            fail "  and set PPRA_CSV=/path/to/file.csv"
            PPRA_FILE=""
        fi
    fi

    if [[ -n "${PPRA_FILE:-}" && -f "${PPRA_FILE}" ]]; then
        # Ingest all contracts; anomaly flags raised automatically for sole-source / single-bidder
        run_job "ppra" "${PPRA_SOURCE_API_KEY}" ppra --input-file "${PPRA_FILE}"
    fi
fi

# =============================================================================
# 6. PaySim Africa Mobile Money Fraud (Kaggle: ealaxi/paysim1)
#    6.3M synthetic transactions modelled on real African mobile money
#    Download: kaggle datasets download -d ealaxi/paysim1
# =============================================================================
section "6/8  PaySim Africa Mobile Money Fraud"
if [[ "${SKIP_PAYSIM:-0}" == "1" ]]; then
    warn "SKIP_PAYSIM=1, skipping"
else
    if [[ -n "${PAYSIM_CSV:-}" && -f "${PAYSIM_CSV}" ]]; then
        PAYSIM_FILE="${PAYSIM_CSV}"
        ok "Using provided PaySim file: ${PAYSIM_FILE}"
    else
        PAYSIM_FILE="${DATA_DIR}/paysim.csv"
        info "Attempting Kaggle download (requires kaggle CLI + API token)…"
        if command -v kaggle &>/dev/null; then
            kaggle datasets download -d ealaxi/paysim1 -p "${DATA_DIR}" --unzip && \
            find "${DATA_DIR}" -name "*.csv" | head -1 | xargs -I{} mv {} "${PAYSIM_FILE}" || true
        fi
        if [[ ! -f "${PAYSIM_FILE}" ]]; then
            warn "Kaggle CLI not available or download failed."
            warn "  Install kaggle CLI:  pip install kaggle"
            warn "  Place token at:      ~/.kaggle/kaggle.json"
            warn "  Then run:            kaggle datasets download -d ealaxi/paysim1"
            warn "  Or set:              PAYSIM_CSV=/path/to/paysim.csv"
            PAYSIM_FILE=""
        fi
    fi

    if [[ -n "${PAYSIM_FILE:-}" && -f "${PAYSIM_FILE}" ]]; then
        # Import fraud transactions + 5000 benign for contrast
        run_job "paysim" "${PAYSIM_SOURCE_API_KEY}" paysim \
            --input-file "${PAYSIM_FILE}" \
            --include-benign \
            --max-benign 5000
    fi
fi

# =============================================================================
# 7. UNSW-NB15 Network Intrusion Dataset
#    Source: research.unsw.edu.au  |  Kaggle: dhoogla/unswnb15
#    2.5M+ labelled flows: DoS, Backdoor, Exploit, Recon, Fuzzer, Worm…
# =============================================================================
section "7/8  UNSW-NB15 Network Intrusion"
if [[ "${SKIP_UNSW:-0}" == "1" ]]; then
    warn "SKIP_UNSW=1, skipping"
else
    if [[ -n "${UNSW_CSV:-}" && -f "${UNSW_CSV}" ]]; then
        UNSW_FILE="${UNSW_CSV}"
        ok "Using provided UNSW file: ${UNSW_FILE}"
    else
        UNSW_FILE="${DATA_DIR}/unsw_nb15.csv"
        info "Attempting Kaggle download for UNSW-NB15…"
        if command -v kaggle &>/dev/null; then
            kaggle datasets download -d dhoogla/unswnb15 -p "${DATA_DIR}" --unzip && \
            find "${DATA_DIR}" -name "UNSW_NB15_training-set.csv" | head -1 | \
                xargs -I{} cp {} "${UNSW_FILE}" || \
            find "${DATA_DIR}" -name "*.csv" | grep -i unsw | head -1 | \
                xargs -I{} cp {} "${UNSW_FILE}" || true
        fi
        if [[ ! -f "${UNSW_FILE}" ]]; then
            warn "UNSW-NB15 not downloaded."
            warn "  kaggle datasets download -d dhoogla/unswnb15"
            warn "  Or from HuggingFace: https://huggingface.co/datasets/wwydmanski/UNSW-NB15"
            warn "  Or set: UNSW_CSV=/path/to/unsw_nb15.csv"
            UNSW_FILE=""
        fi
    fi

    if [[ -n "${UNSW_FILE:-}" && -f "${UNSW_FILE}" ]]; then
        run_job "unsw" "${UNSW_SOURCE_API_KEY}" unsw \
            --input-file "${UNSW_FILE}" \
            --service-id-prefix "ke-noc" \
            --dataset-name "unsw_nb15"
    fi
fi

# =============================================================================
# 8. CIC-IDS2018 Traffic Dataset (AWS Open Data — large, optional)
#    aws s3 sync --no-sign-request s3://cse-cic-ids2018/ ./cic-ids2018/
# =============================================================================
section "8/8  CIC-IDS2018 Network Traffic (optional, large)"
if [[ "${SKIP_CIC:-0}" == "1" ]]; then
    warn "SKIP_CIC=1, skipping CIC download (set SKIP_CIC=0 to enable)"
else
    CIC_DIR="${DATA_DIR}/cic-ids2018"
    if [[ -d "${CIC_DIR}" ]] && ls "${CIC_DIR}"/*.csv &>/dev/null 2>&1; then
        ok "CIC-IDS2018 already downloaded at ${CIC_DIR}"
    else
        info "Downloading CIC-IDS2018 from AWS Open Data (~16GB — this will take a while)…"
        info "Tip: set SKIP_CIC=1 to skip and run manually with:"
        info "  aws s3 sync --no-sign-request --region us-east-1 s3://cse-cic-ids2018/ ${CIC_DIR}/"
        if command -v aws &>/dev/null; then
            mkdir -p "${CIC_DIR}"
            aws s3 sync --no-sign-request --region us-east-1 \
                "s3://cse-cic-ids2018/Processed Traffic Data for ML Algorithms/" \
                "${CIC_DIR}/" \
                --exclude "*.pcap" \
                --include "*.csv" || warn "AWS sync incomplete — check network"
        else
            warn "AWS CLI not found. Install with: pip install awscli"
            warn "Then run: aws s3 sync --no-sign-request --region us-east-1 s3://cse-cic-ids2018/ ${CIC_DIR}/"
        fi
    fi

    if ls "${CIC_DIR:-/dev/null}"/*.csv &>/dev/null 2>&1; then
        for csv_file in "${CIC_DIR}"/*.csv; do
            fname=$(basename "${csv_file}")
            info "Ingesting CIC file: ${fname}"
            run_job "cic:${fname}" "${INGEST_API_KEY}" traffic \
                --dataset cic \
                --input-file "${csv_file}" \
                --service-id-prefix "ke-noc" \
                --dataset-name "cic_ids2018"
        done
    fi
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
section "Haul Complete"
echo -e "  ${G}Total events accepted : ${TOTAL_ACCEPTED}${NC}"
echo -e "  ${R}Total errors          : ${TOTAL_ERRORS}${NC}"
echo ""
echo -e "  Next steps:"
echo -e "  1. Trigger feature snapshot:  docker compose exec backend python -m app.analytics.layer3.graph_feature_worker --window-key Wmid"
echo -e "  2. Train GNN:                 docker compose exec backend python -m app.analytics.layer3.gnn_train_worker --window-key Wmid --epochs 60"
echo -e "  3. Run inference:             docker compose exec backend python -m app.analytics.ai_inference_worker"
echo ""

if [[ "${TOTAL_ERRORS}" -gt 0 ]]; then
    exit 2
fi
exit 0

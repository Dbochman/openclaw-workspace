#!/usr/bin/env bash
set +euo pipefail

REPO="$HOME/repos/financial-dashboard"
PYTHON="./venv/bin/python3"
LOG_DIR="$HOME/.openclaw/workspace/tmp"
LOG="$LOG_DIR/financial-scrape-$(date +%Y%m%d-%H%M%S).log"
SUMMARY="$LOG_DIR/financial-scrape-summary-$(date +%Y%m%d-%H%M%S).txt"
mkdir -p "$LOG_DIR"
cd "$REPO" || { echo "fatal: could not cd to $REPO" | tee -a "$LOG"; exit 2; }

export OP_SERVICE_ACCOUNT_TOKEN="$(cat "$HOME/.openclaw/.env-token")"

failures=()
notes=()

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }

run_cmd() {
  local label="$1"; shift
  log "START $label: $*"
  "$@" >>"$LOG" 2>&1
  local rc=$?
  log "END $label rc=$rc"
  return $rc
}

read_secret_pair() {
  local item="$1"
  SCRAPER_USER="$(op read "$item/username" 2>>"$LOG")" || return 1
  SCRAPER_PW="$(op read "$item/password" 2>>"$LOG")" || return 1
  export SCRAPER_USER SCRAPER_PW
  return 0
}

clear_secret_pair() {
  unset SCRAPER_USER SCRAPER_PW
}

run_api() {
  local label="$1"; shift
  if ! run_cmd "$label" "$@"; then
    failures+=("$label | tier=API | recovery=not applicable | result=failed original command")
  fi
}

run_tier2() {
  local label="$1" item="$2" script="$3"; shift 3
  local -a orig=("$PYTHON" "$script" "$@")
  if run_cmd "$label original" "${orig[@]}"; then
    notes+=("$label succeeded")
    return 0
  fi

  log "$label original failed; attempting Tier 2 --re-auth once"
  local reauth_result="not attempted"
  if read_secret_pair "$item"; then
    if run_cmd "$label re-auth" "$PYTHON" "$script" --re-auth --headless; then
      reauth_result="succeeded"
    else
      reauth_result="failed"
    fi
  else
    reauth_result="credential read failed"
    log "$label credential read failed"
  fi
  clear_secret_pair

  if [[ "$reauth_result" == "succeeded" ]]; then
    if run_cmd "$label retry original" "${orig[@]}"; then
      notes+=("$label recovered after Tier 2 re-auth")
      return 0
    fi
    failures+=("$label | tier=Tier 2 | recovery=--re-auth succeeded | result=retry original failed")
  else
    failures+=("$label | tier=Tier 2 | recovery=--re-auth $reauth_result | result=original failed")
  fi
  return 1
}

run_boa() {
  local label="BOA mortgage"
  local -a orig=("$PYTHON" scrape_mortgage.py --lender boa --headless --merge)
  if run_cmd "$label original" "${orig[@]}"; then
    notes+=("$label succeeded")
    return 0
  fi

  log "$label original failed; running guarded verify-auth"
  local verify_out verify_rc verify_file
  verify_file="$LOG_DIR/boa-verify-$(date +%s).txt"
  "$PYTHON" scrape_mortgage.py --lender boa --verify-auth >"$verify_file" 2>&1
  verify_rc=$?
  cat "$verify_file" >>"$LOG"
  log "$label verify-auth rc=$verify_rc"
  verify_out="$(cat "$verify_file")"

  if printf '%s' "$verify_out" | grep -qi 'authenticated'; then
    failures+=("$label | tier=guarded BoA | recovery=verify-auth authenticated; credential submission skipped | result=original scrape failed")
    return 1
  fi
  if printf '%s' "$verify_out" | grep -qi 'cdp_unavailable'; then
    failures+=("$label | tier=guarded BoA | recovery=verify-auth cdp_unavailable; credential submission skipped | result=Pinchtab tab unavailable; Dylan should VNC into the Mini")
    return 1
  fi
  if ! printf '%s' "$verify_out" | grep -qi 'not_authenticated'; then
    failures+=("$label | tier=guarded BoA | recovery=verify-auth inconclusive (rc=$verify_rc); credential submission skipped | result=manual recovery needed")
    return 1
  fi

  log "$label verify-auth reported not_authenticated; making one guarded --boa-re-auth attempt"
  local recovery_result="not attempted"
  if read_secret_pair 'op://OpenClaw/Bank of America'; then
    local reauth_file="$LOG_DIR/boa-reauth-$(date +%s).txt"
    "$PYTHON" scrape_mortgage.py --lender boa --boa-re-auth >"$reauth_file" 2>&1
    local reauth_rc=$?
    cat "$reauth_file" >>"$LOG"
    log "$label boa-re-auth rc=$reauth_rc"
    if [[ $reauth_rc -eq 0 ]]; then
      recovery_result="succeeded"
    else
      if grep -Eiq 'mfa_or_challenge|login_form_unavailable|login_rejected|login_timeout|cdp_unavailable' "$reauth_file"; then
        recovery_result="$(grep -Eio 'mfa_or_challenge|login_form_unavailable|login_rejected|login_timeout|cdp_unavailable' "$reauth_file" | tail -1)"
      else
        recovery_result="failed rc=$reauth_rc"
      fi
    fi
  else
    recovery_result="credential read failed"
    log "$label credential read failed"
  fi
  clear_secret_pair

  if [[ "$recovery_result" == "succeeded" ]]; then
    if run_cmd "$label retry original" "${orig[@]}"; then
      notes+=("$label recovered after guarded BoA re-auth")
      return 0
    fi
    failures+=("$label | tier=guarded BoA | recovery=--boa-re-auth succeeded | result=retry original failed; Dylan should VNC into the Mini")
  else
    failures+=("$label | tier=guarded BoA | recovery=--boa-re-auth $recovery_result | result=manual recovery required; Dylan should VNC into the Mini")
  fi
  return 1
}

log "Financial scrape started"

# Tier 1
run_api "Tesla solar" "$PYTHON" scrape_tesla_solar.py --merge

# Tier 2
run_tier2 "Eversource" 'op://OpenClaw/www.eversource.com' scrape_eversource.py --headless --merge
run_tier2 "National Grid electric" 'op://OpenClaw/login.nationalgridus.com' scrape_national_grid_electric.py --headless --merge
run_tier2 "National Grid gas" 'op://OpenClaw/login.nationalgridus.com' scrape_national_grid.py --headless --merge
run_tier2 "BWSC" 'op://OpenClaw/umaxcustomerportalprod.b2clogin.com' scrape_bwsc.py --headless --merge
run_tier2 "PennyMac mortgage" 'op://OpenClaw/PennyMac' scrape_mortgage.py --lender pennymac --headless --merge

# BoA guarded path
run_boa

# Imports: idempotent, always run
log "Starting imports"
run_cmd "import-json-utilities" "$PYTHON" update_data.py import-json-utilities
run_cmd "import-json-gas" "$PYTHON" update_data.py import-json-gas
run_cmd "import-json-electric-cabin" "$PYTHON" update_data.py import-json-electric-cabin
run_cmd "import-json-solar-cabin" "$PYTHON" update_data.py import-json-solar-cabin
run_cmd "import-json-water" "$PYTHON" update_data.py import-json-water
run_cmd "import-json-boa-mortgage" "$PYTHON" update_data.py import-json-boa-mortgage
run_cmd "import-json-pennymac-mortgage" "$PYTHON" update_data.py import-json-pennymac-mortgage

if [[ -f .env ]] && grep -Eq '^PLAID_CLIENT_ID=.+' .env; then
  run_cmd "Plaid sync" "$PYTHON" update_data.py sync
else
  log "Skipping Plaid sync: .env missing PLAID_CLIENT_ID"
fi

unset OP_SERVICE_ACCOUNT_TOKEN

{
  echo "log=$LOG"
  echo "failures=${#failures[@]}"
  if (( ${#failures[@]} )); then
    printf '%s\n' "${failures[@]}"
  fi
} > "$SUMMARY"

log "Financial scrape finished with ${#failures[@]} scraper failure(s). Summary: $SUMMARY"
echo "$SUMMARY"
exit 0

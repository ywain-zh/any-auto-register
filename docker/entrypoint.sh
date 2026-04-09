#!/bin/sh
set -eu

APP_DIR="/app"
RUNTIME_DIR="${APP_RUNTIME_DIR:-/runtime}"

mkdir -p "${RUNTIME_DIR}" "${RUNTIME_DIR}/logs" "${RUNTIME_DIR}/smstome_used" "${RUNTIME_DIR}/reports"
touch \
  "${RUNTIME_DIR}/account_manager.db" \
  "${RUNTIME_DIR}/smstome_all_numbers.txt" \
  "${RUNTIME_DIR}/smstome_uk_deep_numbers.txt" \
  "${RUNTIME_DIR}/logs/solver.log"

ln -sfn "${RUNTIME_DIR}/account_manager.db" "${APP_DIR}/account_manager.db"
ln -sfn "${RUNTIME_DIR}/smstome_used" "${APP_DIR}/smstome_used"
ln -sfn "${RUNTIME_DIR}/smstome_all_numbers.txt" "${APP_DIR}/smstome_all_numbers.txt"
ln -sfn "${RUNTIME_DIR}/smstome_uk_deep_numbers.txt" "${APP_DIR}/smstome_uk_deep_numbers.txt"
ln -sfn "${RUNTIME_DIR}/logs/solver.log" "${APP_DIR}/services/turnstile_solver/solver.log"
rm -rf "${APP_DIR}/reports"
ln -s "${RUNTIME_DIR}/reports" "${APP_DIR}/reports"

exec python main.py

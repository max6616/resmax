#!/usr/bin/env bash
set -euo pipefail

CASE_ID="${1:?Usage: prepare-run.sh <case-id>}"

STAMP="$(date +%Y%m%d-%H%M%S)"
RAND="$RANDOM"
RUN_ID="${CASE_ID}-${STAMP}-${RAND}"
RUN_DIR="skill-tests/runs/${RUN_ID}"
SNAPSHOT_DIR="${RUN_DIR}/repo"

mkdir -p "${SNAPSHOT_DIR}"

rsync -a --delete \
  --exclude '.git' \
  --exclude 'skill-tests/runs' \
  --exclude 'node_modules' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.pytest_cache' \
  ./ "${SNAPSHOT_DIR}/"

git -C "${SNAPSHOT_DIR}" init -q
git -C "${SNAPSHOT_DIR}" config user.email "skill-test@example.local"
git -C "${SNAPSHOT_DIR}" config user.name "Skill Test Snapshot"
git -C "${SNAPSHOT_DIR}" add -A
git -C "${SNAPSHOT_DIR}" commit -q -m "snapshot before skill test"

mkdir -p "${RUN_DIR}/reports"
mkdir -p "${SNAPSHOT_DIR}/outputs/${CASE_ID}"

echo "${RUN_DIR}"
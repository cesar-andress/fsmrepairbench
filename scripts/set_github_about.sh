#!/usr/bin/env bash
set -euo pipefail

REPO="${GITHUB_REPOSITORY:-cesar-andress/fsmrepairbench}"

gh repo edit "$REPO" \
  --description "Benchmark toolkit for behavioural finite-state machine repair with oracle scoring, seeded mutation, and stratified dataset generation." \
  --homepage "https://github.com/${REPO}#readme" \
  --add-topic finite-state-machines \
  --add-topic fsm \
  --add-topic benchmark \
  --add-topic mutation-testing \
  --add-topic oracle-testing \
  --add-topic software-repair \
  --add-topic llm \
  --add-topic mealy-machine \
  --add-topic moore-machine \
  --add-topic efsm \
  --add-topic python

echo "Updated GitHub About metadata for ${REPO}"

#!/usr/bin/env bash
set -euo pipefail

# Izolyatsiya kesha i zapret setevogo fallback vo vremya inference.
export HF_HOME=/opt/Tester/market-lab-doc-llm/cache/huggingface
export HF_HUB_CACHE=/opt/Tester/market-lab-doc-llm/cache/huggingface/hub
export TRANSFORMERS_CACHE=/opt/Tester/market-lab-doc-llm/cache/transformers
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export CUBLAS_WORKSPACE_CONFIG=:4096:8

exec /opt/Tester/market-lab-doc-llm/.venv/bin/python \
  /opt/Tester/market-lab-doc-llm/app/doc_extract.py "$@"

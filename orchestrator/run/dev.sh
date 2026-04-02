#!/bin/bash

cd /data3/peirongcan/PaperIgnitionV1

# Load environment variables
set -a
source .env
set +a

# Set proxy (optional)
export http_proxy="http://127.0.0.1:7890"
export https_proxy="http://127.0.0.1:7890"
export NO_PROXY="localhost,127.0.0.1,10.0.1.226"

# Set project root for PYTHONPATH
PROJECT_ROOT="/data3/peirongcan/PaperIgnitionV1"
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

# Set local mode (uses test_config.yaml for backend, development.yaml for orchestrator)
export PAPERIGNITION_LOCAL_MODE=true

# Run orchestrator with development.yaml config
python orchestrator/orchestrator.py configs/development.yaml "$@"
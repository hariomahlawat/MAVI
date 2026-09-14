#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 9 ]]; then
  echo "usage: qualify_linux_offline.sh <cpu-bundle> <cuda-bundle> <cpu-worker-evidence> <cuda-worker-evidence> <source-commit> <target-verified-manifest-sha256> <acceptance-profile> <work-root> <output>" >&2
  exit 2
fi

CPU_BUNDLE="$1"
CUDA_BUNDLE="$2"
CPU_WORKER="$3"
CUDA_WORKER="$4"
SOURCE_COMMIT="$5"
TARGET_MANIFEST_SHA="$6"
ACCEPTANCE_PROFILE="$7"
WORK_ROOT="$8"
OUTPUT="$9"

if [[ -e "$OUTPUT" ]]; then
  echo "linux_offline_evidence_exists" >&2
  exit 2
fi

mkdir -p "$WORK_ROOT"
CPU_OUT="$WORK_ROOT/linux-x86_64-cpu.json"
CUDA_OUT="$WORK_ROOT/linux-x86_64-cuda.json"
CPU_VENV="$WORK_ROOT/venv-cpu"
CUDA_VENV="$WORK_ROOT/venv-cuda"

python "$PWD/tools/phase1/qualify_offline_variant.py"   --bundle-dir "$CPU_BUNDLE"   --variant linux-x86_64-cpu   --source-commit "$SOURCE_COMMIT"   --target-verified-manifest-sha256 "$TARGET_MANIFEST_SHA"   --worker-flow-evidence "$CPU_WORKER"   --acceptance-profile "$ACCEPTANCE_PROFILE"   --venv "$CPU_VENV"   --network-isolated   --output "$CPU_OUT"

python "$PWD/tools/phase1/qualify_offline_variant.py"   --bundle-dir "$CUDA_BUNDLE"   --variant linux-x86_64-cuda   --source-commit "$SOURCE_COMMIT"   --target-verified-manifest-sha256 "$TARGET_MANIFEST_SHA"   --worker-flow-evidence "$CUDA_WORKER"   --acceptance-profile "$ACCEPTANCE_PROFILE"   --venv "$CUDA_VENV"   --network-isolated   --output "$CUDA_OUT"

python "$PWD/tools/phase1/assemble_offline_install_evidence.py"   --os linux   --cpu "$CPU_OUT"   --cuda "$CUDA_OUT"   --isolation-method disconnected-linux-qualification-host   --output "$OUTPUT"

python "$PWD/tools/phase1/verify_phase1_evidence.py"   --offline-install "$OUTPUT"   --expected-source-commit "$SOURCE_COMMIT"

echo "Task-17 Linux CPU+CUDA offline qualification PASSED."

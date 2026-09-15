#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 18 ]]; then
  echo "usage: qualify_linux_offline.sh <cpu-bundle> <cuda-bundle> <source-commit> <target-verified-manifest-sha256> <acceptance-profile> <base-url> <media-root> <camera-code> <camera-name> <camera-timezone> <recording-local> <video> <environment-label> <mavi-build> <corpus-manifest> <ground-truth> <work-root> <output>" >&2
  exit 2
fi

CPU_BUNDLE="$1"
CUDA_BUNDLE="$2"
SOURCE_COMMIT="$3"
TARGET_MANIFEST_SHA="$4"
ACCEPTANCE_PROFILE="$5"
BASE_URL="$6"
MEDIA_ROOT="$7"
CAMERA_CODE="$8"
CAMERA_NAME="$9"
CAMERA_TIMEZONE="${10}"
RECORDING_LOCAL="${11}"
VIDEO="${12}"
ENVIRONMENT_LABEL="${13}"
MAVI_BUILD="${14}"
CORPUS_MANIFEST="${15}"
GROUND_TRUTH="${16}"
WORK_ROOT="${17}"
OUTPUT="${18}"

if [[ -e "$OUTPUT" ]]; then
  echo "linux_offline_evidence_exists" >&2
  exit 2
fi

mkdir -p "$WORK_ROOT"
CPU_OUT="$WORK_ROOT/linux-x86_64-cpu.json"
CUDA_OUT="$WORK_ROOT/linux-x86_64-cuda.json"
CPU_WORKER="$WORK_ROOT/linux-x86_64-cpu.worker.json"
CUDA_WORKER="$WORK_ROOT/linux-x86_64-cuda.worker.json"
CPU_VENV="$WORK_ROOT/venv-cpu"
CUDA_VENV="$WORK_ROOT/venv-cuda"

qualify_variant() {
  local bundle="$1"
  local variant="$2"
  local venv="$3"
  local worker_out="$4"
  local evidence_out="$5"

  python "$PWD/tools/phase1/qualify_offline_variant.py" \
    --bundle-dir "$bundle" \
    --variant "$variant" \
    --source-commit "$SOURCE_COMMIT" \
    --target-verified-manifest-sha256 "$TARGET_MANIFEST_SHA" \
    --acceptance-profile "$ACCEPTANCE_PROFILE" \
    --base-url "$BASE_URL" \
    --media-root "$MEDIA_ROOT" \
    --camera-code "$CAMERA_CODE" \
    --camera-name "$CAMERA_NAME" \
    --camera-timezone "$CAMERA_TIMEZONE" \
    --recording-local "$RECORDING_LOCAL" \
    --video "$VIDEO" \
    --environment-label "$ENVIRONMENT_LABEL-$variant" \
    --expected-mavi-build "$MAVI_BUILD" \
    --corpus-manifest "$CORPUS_MANIFEST" \
    --ground-truth "$GROUND_TRUTH" \
    --worker-flow-output "$worker_out" \
    --venv "$venv" \
    --network-isolated \
    --output "$evidence_out"
}

qualify_variant "$CPU_BUNDLE" linux-x86_64-cpu "$CPU_VENV" "$CPU_WORKER" "$CPU_OUT"
qualify_variant "$CUDA_BUNDLE" linux-x86_64-cuda "$CUDA_VENV" "$CUDA_WORKER" "$CUDA_OUT"

python "$PWD/tools/phase1/assemble_offline_install_evidence.py" \
  --os linux \
  --cpu "$CPU_OUT" \
  --cuda "$CUDA_OUT" \
  --isolation-method disconnected-linux-qualification-host \
  --output "$OUTPUT"

python "$PWD/tools/phase1/verify_phase1_evidence.py" \
  --offline-install "$OUTPUT" \
  --expected-source-commit "$SOURCE_COMMIT"

echo "Task-17 Linux CPU+CUDA offline qualification PASSED."

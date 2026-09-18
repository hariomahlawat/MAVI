#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 17 && $# -ne 18 ]]; then
  echo "usage: qualify_linux_offline.sh <cuda-bundle> <source-commit> <target-verified-manifest-sha256> <acceptance-profile> <base-url> <media-root> <camera-code> <camera-name> <camera-timezone> <recording-local> <video> <environment-label> <mavi-build> <corpus-manifest> <ground-truth> <work-root> <output> [deployment-profile-policy]" >&2
  exit 2
fi

BUNDLE="$1"
SOURCE_COMMIT="$2"
TARGET_MANIFEST_SHA="$3"
ACCEPTANCE_PROFILE="$4"
BASE_URL="$5"
MEDIA_ROOT="$6"
CAMERA_CODE="$7"
CAMERA_NAME="$8"
CAMERA_TIMEZONE="$9"
RECORDING_LOCAL="${10}"
VIDEO="${11}"
ENVIRONMENT_LABEL="${12}"
MAVI_BUILD="${13}"
CORPUS_MANIFEST="${14}"
GROUND_TRUTH="${15}"
WORK_ROOT="${16}"
OUTPUT="${17}"
DEPLOYMENT_PROFILE_POLICY="${18:-}"

PROFILE="P2"
VARIANT="linux-x86_64-cuda"

if [[ -e "$OUTPUT" ]]; then
  echo "linux_offline_evidence_exists" >&2
  exit 2
fi

mkdir -p "$WORK_ROOT"
VARIANT_OUT="$WORK_ROOT/$VARIANT.json"
WORKER_OUT="$WORK_ROOT/$VARIANT.worker.json"
VENV="$WORK_ROOT/venv-$PROFILE"

python "$PWD/tools/phase1/qualify_offline_variant.py" \
  --bundle-dir "$BUNDLE" \
  --variant "$VARIANT" \
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
  --environment-label "$ENVIRONMENT_LABEL-$PROFILE" \
  --expected-mavi-build "$MAVI_BUILD" \
  --corpus-manifest "$CORPUS_MANIFEST" \
  --ground-truth "$GROUND_TRUTH" \
  --worker-flow-output "$WORKER_OUT" \
  --venv "$VENV" \
  --network-isolated \
  --output "$VARIANT_OUT"

ASSEMBLE_ARGS=(
  "$PWD/tools/phase1/assemble_offline_install_evidence.py"
  --deployment-profile "$PROFILE"
  --variant "$VARIANT_OUT"
  --isolation-method disconnected-linux-qualification-host
  --output "$OUTPUT"
)
if [[ -n "$DEPLOYMENT_PROFILE_POLICY" ]]; then
  ASSEMBLE_ARGS+=(--deployment-profile-policy "$DEPLOYMENT_PROFILE_POLICY")
fi
python "${ASSEMBLE_ARGS[@]}"

python "$PWD/tools/phase1/verify_phase1_evidence.py" \
  --offline-install "$OUTPUT" \
  --expected-source-commit "$SOURCE_COMMIT"

echo "Task-18 Linux offline qualification PASSED for P2 ($VARIANT)."

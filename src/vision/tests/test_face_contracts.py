"""The ``faces`` role's pure parts: YuNet decoding, alignment, identity, profile and contracts (PoC S6; ADR-022)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from mavi_vision.faces.align import ALIGNED_SIZE, ARCFACE_TEMPLATE, align_face, similarity_transform
from mavi_vision.faces.contracts import FaceLease, FaceQueryLease
from mavi_vision.faces.detector import (
    FaceDetection,
    clip_to_crop,
    decode,
    detect_faces,
    non_maximum_suppression,
    padded_input,
)
from mavi_vision.faces.identity import load_pipeline_profile, resolve_face_pack
from mavi_vision.faces.model import (
    QueryImageInvalid,
    decode_crop,
    decode_query_image,
    embedder_input,
)

VISION_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = VISION_ROOT.parents[1]
CONTRACTS = REPOSITORY_ROOT / "contracts"
FIXTURE_MANIFEST = VISION_ROOT / "tests" / "fixtures" / "model-manifests" / "embedding-fixture-v2.json"
FIXTURE_PROFILE = VISION_ROOT / "tests" / "fixtures" / "faces" / "fixture-pipeline-v1.json"


# --- YuNet decoding ----------------------------------------------------------------------------------------


def _outputs(pad_h: int, pad_w: int, anchors: dict[tuple[int, int], tuple[float, list[float], list[float]]]) -> dict[str, np.ndarray]:
    """Synthetic YuNet outputs: ``anchors`` maps (stride, index) to (score, bbox offsets, 10 landmark offsets)."""
    outputs = {}
    for stride in (8, 16, 32):
        n = (pad_h // stride) * (pad_w // stride)
        outputs[f"cls_{stride}"] = np.zeros((1, n, 1), np.float32)
        outputs[f"obj_{stride}"] = np.zeros((1, n, 1), np.float32)
        outputs[f"bbox_{stride}"] = np.zeros((1, n, 4), np.float32)
        outputs[f"kps_{stride}"] = np.zeros((1, n, 10), np.float32)
    for (stride, index), (score, bbox, kps) in anchors.items():
        outputs[f"cls_{stride}"][0, index, 0] = score
        outputs[f"obj_{stride}"][0, index, 0] = score
        outputs[f"bbox_{stride}"][0, index] = bbox
        outputs[f"kps_{stride}"][0, index] = kps
    return outputs


def test_decode_follows_opencv_face_detector_yn_anchor_arithmetic() -> None:
    # Padded 32x32: stride 8 has a 4x4 grid; index 6 is row 1, column 2.
    kps = [0.5, 0.25] * 5
    outputs = _outputs(32, 32, {(8, 6): (0.95, [0.5, 0.5, math.log(2.0), math.log(3.0)], kps)})
    faces = decode(outputs, 32, 32, score_threshold=0.9)
    assert len(faces) == 1
    face = faces[0]
    # cx = (2 + 0.5) * 8 = 20, cy = (1 + 0.5) * 8 = 12, w = 2 * 8, h = 3 * 8; score = sqrt(cls * obj).
    assert (face.x, face.y, face.width, face.height) == pytest.approx((12.0, 0.0, 16.0, 24.0))
    assert face.score == pytest.approx(0.95)
    assert face.landmarks[0] == pytest.approx(((2 + 0.5) * 8, (1 + 0.25) * 8))
    assert decode(outputs, 32, 32, score_threshold=0.96) == []


def test_decode_refuses_outputs_that_do_not_match_the_padded_grid() -> None:
    outputs = _outputs(64, 64, {})
    with pytest.raises(ValueError, match="face_detector_output_shape"):
        decode(outputs, 32, 32, score_threshold=0.5)


def test_nms_keeps_the_best_of_overlapping_faces_and_is_deterministic() -> None:
    marks = ((0.0, 0.0),) * 5
    a = FaceDetection(0, 0, 10, 10, 0.9, marks)
    b = FaceDetection(1, 1, 10, 10, 0.95, marks)
    c = FaceDetection(50, 50, 10, 10, 0.91, marks)
    assert non_maximum_suppression([a, b, c], 0.3, 5000) == [b, c]
    assert non_maximum_suppression([a, b, c], 0.3, 1) == [b]


def test_padding_never_resizes_and_boxes_are_clipped_to_the_crop() -> None:
    rgb = np.zeros((33, 40, 3), np.uint8)
    rgb[..., 0] = 200  # red
    tensor, pad_h, pad_w = padded_input(rgb)
    assert (pad_h, pad_w) == (64, 64) and tensor.shape == (1, 3, 64, 64)
    assert tensor[0, 2, 0, 0] == 200 and tensor[0, 0, 0, 0] == 0  # BGR order, no normalisation
    assert tensor[0, 2, 40, 50] == 0  # padding
    marks = ((0.0, 0.0),) * 5
    assert clip_to_crop(FaceDetection(-5, 30, 20, 10, 0.9, marks), 33, 40) == FaceDetection(0, 30, 15, 3, 0.9, marks)
    assert clip_to_crop(FaceDetection(50, 50, 5, 5, 0.9, marks), 33, 40) is None


def test_detect_faces_runs_the_session_on_the_padded_tensor() -> None:
    class Session:
        def __init__(self) -> None:
            self.shapes: list[tuple[int, ...]] = []

        def run(self, names, feed):
            self.shapes.append(feed["input"].shape)
            outputs = _outputs(32, 32, {(8, 6): (0.95, [0.5, 0.5, math.log(2.0), math.log(3.0)], [0.0] * 10)})
            return [outputs[name] for name in names]

    session = Session()
    faces = detect_faces(session, np.zeros((20, 30, 3), np.uint8), score_threshold=0.9, nms_threshold=0.3, top_k=10)
    assert session.shapes == [(1, 3, 32, 32)]
    # The 16x24 box at (12, 0) is clipped to the 30x20 crop.
    assert [(f.x, f.y, f.width, f.height) for f in faces] == [pytest.approx((12.0, 0.0, 16.0, 20.0))]


# --- alignment ---------------------------------------------------------------------------------------------


def test_template_landmarks_on_a_112_image_are_the_identity_transform() -> None:
    matrix = similarity_transform(ARCFACE_TEMPLATE, ARCFACE_TEMPLATE)
    assert np.allclose(matrix, [[1, 0, 0], [0, 1, 0]], atol=1e-9)
    rng = np.random.default_rng(3)
    image = rng.integers(0, 255, (ALIGNED_SIZE, ALIGNED_SIZE, 3), dtype=np.uint8)
    aligned = align_face(image, [tuple(point) for point in ARCFACE_TEMPLATE])
    assert aligned.shape == (112, 112, 3) and aligned.dtype == np.uint8
    assert np.abs(aligned.astype(int) - image.astype(int)).max() <= 1


def test_the_similarity_transform_recovers_rotation_scale_and_translation() -> None:
    angle, scale, shift = math.radians(20), 0.5, np.array([7.0, -3.0])
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    source = (ARCFACE_TEMPLATE - shift) @ np.linalg.inv(scale * rotation).T
    matrix = similarity_transform(source, ARCFACE_TEMPLATE)
    assert np.allclose(matrix[:, :2], scale * rotation, atol=1e-9)
    assert np.allclose(source @ matrix[:, :2].T + matrix[:, 2], ARCFACE_TEMPLATE, atol=1e-9)


def test_alignment_refuses_degenerate_or_malformed_landmarks() -> None:
    image = np.zeros((50, 50, 3), np.uint8)
    with pytest.raises(ValueError, match="face_alignment_points"):
        align_face(image, [(1.0, 1.0)] * 4)
    with pytest.raises(ValueError, match="face_alignment_degenerate"):
        align_face(image, [(1.0, 1.0)] * 5)
    with pytest.raises(ValueError, match="face_alignment_points"):
        align_face(image, [(float("nan"), 1.0)] * 5)


# --- preprocessing and decoding ----------------------------------------------------------------------------


def test_embedder_preprocessing_ids() -> None:
    face = np.full((112, 112, 3), 255, np.uint8)
    face[0, 0] = (0, 51, 102)
    adaface = embedder_input(face, "adaface-ir50-v1")
    sface = embedder_input(face, "sface-v1")
    assert adaface.shape == sface.shape == (3, 112, 112)
    assert adaface[:, 0, 0] == pytest.approx([-1.0, -0.6, -0.2]) and adaface[0, 1, 1] == pytest.approx(1.0)
    assert sface[:, 0, 0] == pytest.approx([0.0, 51.0, 102.0])  # RGB, raw 0-255
    with pytest.raises(ValueError, match="face_preprocessing_unsupported"):
        embedder_input(face, "other")


def _encoded(fmt: str, size=(40, 30)) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(np.zeros((size[1], size[0], 3), np.uint8)).save(buffer, fmt)
    return buffer.getvalue()


def test_query_images_are_only_jpeg_or_png_of_their_declared_type_within_bounds() -> None:
    jpeg, png = _encoded("JPEG"), _encoded("PNG")
    assert decode_query_image(jpeg, "image/jpeg", 2_000_000).shape == (30, 40, 3)
    assert decode_query_image(png, "image/png", 2_000_000).shape == (30, 40, 3)
    for data, mime, limit in [(png, "image/jpeg", 2_000_000), (jpeg, "image/gif", 2_000_000), (jpeg, "image/jpeg", 10),
                              (b"", "image/jpeg", 2_000_000), (b"not an image", "image/png", 2_000_000),
                              (_encoded("BMP"), "image/png", 2_000_000)]:
        with pytest.raises(QueryImageInvalid):
            decode_query_image(data, mime, limit)


def test_a_query_image_over_the_pixel_bound_is_refused_before_decoding() -> None:
    huge = _encoded("PNG", (5000, 4000))  # 20 MP of black compresses well under the byte bound
    with pytest.raises(QueryImageInvalid):
        decode_query_image(huge, "image/png", 2_000_000)


def test_an_undecodable_crop_is_none() -> None:
    assert decode_crop(b"\xff\xd8 truncated") is None
    assert decode_crop(_encoded("JPEG")).shape == (30, 40, 3)


# --- identity, profile and contracts ----------------------------------------------------------------------


def test_the_fixture_identity_equals_its_test_vector() -> None:
    vectors = json.loads((CONTRACTS / "test-vectors" / "face-identity-v1.json").read_text(encoding="utf-8"))["vectors"]
    fixture = next(vector for vector in vectors if vector["name"] == "fixture")
    resolved = resolve_face_pack(REPOSITORY_ROOT / fixture["modelManifest"], REPOSITORY_ROOT / fixture["pipelineProfile"])
    assert resolved.identity.canonical == fixture["canonicalIdentity"]
    assert resolved.identity.fingerprint == fixture["fingerprint"]
    assert json.loads(resolved.identity.canonical)["schemaVersion"] == "mavi-face-identity-v1"


def test_every_identity_vector_re_derives_from_its_files() -> None:
    vectors = json.loads((CONTRACTS / "test-vectors" / "face-identity-v1.json").read_text(encoding="utf-8"))["vectors"]
    for vector in vectors:
        resolved = resolve_face_pack(REPOSITORY_ROOT / vector["modelManifest"], REPOSITORY_ROOT / vector["pipelineProfile"])
        assert resolved.identity.fingerprint == vector["fingerprint"], vector["name"]


def test_the_profile_is_strict(tmp_path: Path) -> None:
    profile, digest = load_pipeline_profile(FIXTURE_PROFILE)
    assert profile.minimum_face_side == 32 and profile.detector.score_threshold == 0.9 and len(digest) == 64
    document = json.loads(FIXTURE_PROFILE.read_text(encoding="utf-8"))
    for change in [{"extra": 1}, {"preprocessing": "siglip2-fixed-224-v1"}, {"objectClasses": ["Vehicle"]},
                   {"referenceThreshold": {"cosine": 1.5, "provenance": "x"}}, {"queryImageMaximumBytes": 3_000_000},
                   {"alignment": "other"}]:
        path = tmp_path / "profile.json"
        path.write_text(json.dumps({**document, **change}), encoding="utf-8")
        with pytest.raises(ValueError, match="face_pipeline_profile_invalid"):
            load_pipeline_profile(path)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({**document, "schemaVersion": "mavi-embedding-pipeline-v1"}), encoding="utf-8")
    with pytest.raises(ValueError, match="face_pipeline_profile_schema_unsupported"):
        load_pipeline_profile(path)


def test_a_profile_naming_another_manifest_or_dimension_is_refused(tmp_path: Path) -> None:
    document = json.loads(FIXTURE_PROFILE.read_text(encoding="utf-8"))
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({**document, "dimension": 128}), encoding="utf-8")
    with pytest.raises(ValueError, match="face_profile_dimension_mismatch"):
        resolve_face_pack(FIXTURE_MANIFEST, path)
    path.write_text(json.dumps({**document, "modelManifest": "models/manifests/other.json"}), encoding="utf-8")
    with pytest.raises(ValueError, match="face_profile_manifest_mismatch"):
        resolve_face_pack(FIXTURE_MANIFEST, path)


def _example(name: str) -> dict:
    return json.loads((CONTRACTS / "examples" / f"{name}.example.json").read_text(encoding="utf-8"))


def test_the_lease_examples_parse_and_validate() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    for name in ("face-lease-v1", "face-complete-v1", "face-query-lease-v1", "face-query-complete-v1"):
        schema = json.loads((CONTRACTS / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(_example(name), schema)
    lease = FaceLease.model_validate_json(json.dumps(_example("face-lease-v1")))
    query = FaceQueryLease.model_validate_json(json.dumps(_example("face-query-lease-v1")))
    assert lease.identity.fingerprint == query.identity.fingerprint
    assert all(track.object_class == "Person" for track in lease.tracks)


def test_the_completion_schema_refuses_what_the_contract_forbids() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((CONTRACTS / "schemas" / "face-complete-v1.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    body = _example("face-complete-v1")
    usable = body["tracks"][0]["faces"][0]
    unusable = body["tracks"][0]["faces"][1]
    cases = [
        # An unknown Track never carries a usable face.
        {**body, "tracks": [{**body["tracks"][1], "faces": [usable]}]},
        # An observed Track has at least one face.
        {**body, "tracks": [{**body["tracks"][0], "faces": []}]},
        # An unusable face carries no vector; a usable one must.
        {**body, "tracks": [{**body["tracks"][0], "faces": [usable, {**unusable, "embedding": usable["embedding"]}]}]},
        {**body, "tracks": [{**body["tracks"][0], "faces": [{k: v for k, v in usable.items() if k != "embedding"}]}]},
        # "no match" is not a reason.
        {**body, "tracks": [{**body["tracks"][2], "reason": "no_match"}]},
        {**body, "provenance": {**body["provenance"], "roleId": "embeddings"}},
    ]
    for case in cases:
        assert not validator.is_valid(case)

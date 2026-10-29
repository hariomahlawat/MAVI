"""PoC S4 (ADR-021): build the SigLIP 2 embeddings Model Pack payloads from a pinned local snapshot (connected host).

Exports the image tower and the text tower of ``google/siglip2-base-patch16-224`` to ONNX, checks ONNX against
PyTorch and the pack tokenizer (SentencePiece, ``tokenizer.model``) against the reference Hugging Face tokenizer,
and writes the payload directory the committed manifest names. The pack is consumed offline; this script is the
only place PyTorch/transformers are used, and they never enter a MAVI runtime.

    python tools/vision/build_siglip2_pack.py --source <snapshot@75de2d55> --licence <big_vision LICENSE> --out <dir>

The snapshot files are verified against ``SOURCE_SHA256`` before anything is loaded (``--record-source`` prints the
hashes of a fresh download once, to be committed). Re-exports are not guaranteed to be byte-identical across
PyTorch/ONNX versions; the committed manifest pins the bytes actually built, and the builder records its toolchain.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from pathlib import Path

REPOSITORY = "google/siglip2-base-patch16-224"
REVISION = "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2"
PACK_DIRECTORY = "embeddings-siglip2-base-p16-224-dev-v1"
TEXT_LENGTH = 64
# Filled from --record-source on the first connected download (2026-10-29); the build refuses any other bytes.
SOURCE_SHA256: dict[str, str] = {
    "README.md": "39ac3705d62af9ffa1a14675b8ccb220a75f2d81acd530e564a3b1e3dfe418d8",
    "config.json": "fe8b5fe6d5734360678fd71c11c21e1ea3364bd8598d34295d9206335973ffd7",
    "model.safetensors": "612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b",
    "preprocessor_config.json": "9b36b57ebaf20f09bf4c22100ccc21877ea6bfe5aead0c00c59f8af8ccefacfc",
    "special_tokens_map.json": "baec30ea10906f16adb8c18af7a34023002c1746542612b8b41c9f09e1351351",
    "tokenizer.json": "cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322",
    "tokenizer.model": "61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2",
    "tokenizer_config.json": "14afe629fe4959b9e0d51e1852b8d9f7ad074f90a1a7125a4fcdd17f06e78fc8",
}
PARITY_TEXTS = [
    "a person wearing a red jacket",
    "white car",
    "Person, RED upper clothing, backpack",
    "a cyclist with a yellow helmet at night",
    "dark blue pickup truck",
    "",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sentencepiece_ids(processor, text: str) -> list[int]:
    """The runtime tokenizer contract (mavi_vision.embeddings.tokenizer): lowercase, SentencePiece ids, EOS, pad."""
    ids = processor.encode(text.lower())[: TEXT_LENGTH - 1] + [1]
    return ids + [0] * (TEXT_LENGTH - len(ids))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--licence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--record-source", action="store_true")
    args = parser.parse_args()

    files = sorted(p.name for p in args.source.iterdir() if p.is_file())
    hashes = {name: sha256(args.source / name) for name in files}
    if args.record_source:
        print(json.dumps(hashes, indent=2))
        return 0
    if SOURCE_SHA256 and hashes != SOURCE_SHA256:
        raise SystemExit(f"source_snapshot_mismatch: {hashes}")

    import numpy as np
    import onnxruntime as ort
    import sentencepiece
    import torch
    from transformers import AutoTokenizer, SiglipModel

    model = SiglipModel.from_pretrained(args.source, local_files_only=True).eval()
    reference_tokenizer = AutoTokenizer.from_pretrained(args.source, local_files_only=True)
    pack = args.out / PACK_DIRECTORY
    pack.mkdir(parents=True, exist_ok=True)

    def pooled(output):
        # transformers >= 5 returns a ModelOutput whose pooler_output is the projected embedding; 4.x a tensor.
        return output if isinstance(output, torch.Tensor) else output.pooler_output

    class Vision(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.model = model

        def forward(self, pixel_values):
            return pooled(self.model.get_image_features(pixel_values=pixel_values))

    class Text(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.model = model

        def forward(self, input_ids):
            return pooled(self.model.get_text_features(input_ids=input_ids))

    pixels = torch.randn(2, 3, 224, 224)
    ids = torch.zeros(2, TEXT_LENGTH, dtype=torch.int64)
    with torch.no_grad():
        torch.onnx.export(Vision(), (pixels,), pack / "vision.onnx", input_names=["pixel_values"],
                          output_names=["image_embeds"], dynamic_axes={"pixel_values": {0: "n"}, "image_embeds": {0: "n"}},
                          opset_version=17, dynamo=False)
        torch.onnx.export(Text(), (ids,), pack / "text.onnx", input_names=["input_ids"],
                          output_names=["text_embeds"], dynamic_axes={"input_ids": {0: "n"}, "text_embeds": {0: "n"}},
                          opset_version=17, dynamo=False)
    shutil.copyfile(args.source / "tokenizer.model", pack / "tokenizer.model")
    shutil.copyfile(args.source / "README.md", pack / "README.md")
    shutil.copyfile(args.licence, pack / "LICENSE")

    # Parity: ONNX vs PyTorch (both towers) and pack tokenizer vs the reference tokenizer.
    processor = sentencepiece.SentencePieceProcessor(model_file=str(pack / "tokenizer.model"))
    token_rows = []
    for text in PARITY_TEXTS:
        reference = reference_tokenizer(text.lower(), padding="max_length", max_length=TEXT_LENGTH,
                                        truncation=True)["input_ids"]
        ours = sentencepiece_ids(processor, text)
        if reference != ours:
            raise SystemExit(f"tokenizer_parity_failed: {text!r} {reference[:12]} {ours[:12]}")
        token_rows.append(ours)
    torch.manual_seed(0)
    pixels = torch.rand(4, 3, 224, 224) * 2 - 1
    ids = torch.tensor(token_rows, dtype=torch.int64)
    with torch.no_grad():
        torch_image = pooled(model.get_image_features(pixel_values=pixels)).numpy()
        torch_text = pooled(model.get_text_features(input_ids=ids)).numpy()
    vision = ort.InferenceSession(str(pack / "vision.onnx"), providers=["CPUExecutionProvider"])
    text = ort.InferenceSession(str(pack / "text.onnx"), providers=["CPUExecutionProvider"])
    onnx_image = vision.run(None, {"pixel_values": pixels.numpy()})[0]
    onnx_text = text.run(None, {"input_ids": ids.numpy()})[0]

    def min_cosine(a, b):
        a = a / np.linalg.norm(a, axis=1, keepdims=True)
        b = b / np.linalg.norm(b, axis=1, keepdims=True)
        return float(np.min(np.sum(a * b, axis=1)))

    parity = {"imageMinCosine": min_cosine(torch_image, onnx_image), "textMinCosine": min_cosine(torch_text, onnx_text),
              "tokenizerTexts": len(PARITY_TEXTS)}
    if parity["imageMinCosine"] < 0.9999 or parity["textMinCosine"] < 0.9999:
        raise SystemExit(f"onnx_parity_failed: {parity}")

    import onnx
    import transformers

    build = {
        "repository": REPOSITORY,
        "revision": REVISION,
        "sourceSha256": hashes,
        "embeddingDimension": int(onnx_image.shape[1]),
        "logitScale": float(model.logit_scale.exp().item()),
        "logitBias": float(model.logit_bias.item()),
        "parity": parity,
        "toolchain": {"python": platform.python_version(), "torch": torch.__version__,
                      "transformers": transformers.__version__, "onnx": onnx.__version__,
                      "onnxruntime": ort.__version__, "sentencepiece": sentencepiece.__version__, "opset": 17},
        "artifacts": {name: sha256(pack / name) for name in sorted(p.name for p in pack.iterdir())},
    }
    (args.out / "build-record.json").write_text(json.dumps(build, indent=2), encoding="utf-8")
    print(json.dumps(build, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

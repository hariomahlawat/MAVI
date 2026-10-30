"""PoC S6 (ADR-022 §2): build the face Model Pack payloads from pinned local sources (connected host).

One Model Pack per face pipeline: the YuNet detector and one embedder, each with its own LICENSE file.

* ``faces-yunet-adaface-ir50-dev-v1``: YuNet ``face_detection_yunet_2026may.onnx`` (opencv_zoo, MIT) and AdaFace
  IR-50 WebFace4M (``minchul/cvlface_adaface_ir50_webface4m``; code MIT, checkpoint research-only). The IR-50 graph
  is rebuilt here from the AdaFace architecture (MIT) and loaded from ``model.safetensors`` only: the snapshot's
  pickled ``model.pt`` and its remote code are never loaded or executed. It is exported to ONNX and checked
  against PyTorch.
* ``faces-yunet-sface-dev-v1``: YuNet and SFace ``face_recognition_sface_2021dec.onnx`` (opencv_zoo, Apache-2.0),
  copied byte-for-byte.

    python tools/vision/build_face_packs.py --yunet <dir> --adaface <dir> --adaface-licence <LICENSE> --sface <dir> --out <dir>

Every source file is verified against ``SOURCE_SHA256`` before it is read. PyTorch and safetensors are used only
here and never enter a MAVI runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from pathlib import Path

ADAFACE_PACK = "faces-yunet-adaface-ir50-dev-v1"
SFACE_PACK = "faces-yunet-sface-dev-v1"
SOURCE_SHA256 = {
    "yunet/LICENSE": "c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958",
    "yunet/README.md": "a140c9e9574ff99d3dc1c435d5e8b5e60690dc91597e66387cbbb52be12cce4c",
    "yunet/face_detection_yunet_2026may.onnx": "ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
    "sface/LICENSE": "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
    "sface/README.md": "e090e126f3fb5c0b0b2d84ee644b17e42a70b2e45a90616814970b811e91d063",
    "sface/face_recognition_sface_2021dec.onnx": "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    "adaface/model.safetensors": "da82e6e1dbe98ce23afb78283b858ad65e32484a2bac82e9adae298d04ff845d",
}
STATE_PREFIX = "model.net."
IR50_UNITS = ((64, 64, 3), (64, 128, 4), (128, 256, 14), (256, 512, 3))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ir50():
    """AdaFace IR-50 (``Backbone(input_size=(112, 112), num_layers=50, mode='ir')``), module names as upstream."""
    import torch
    from torch import nn

    class BasicBlockIR(nn.Module):
        def __init__(self, in_channel: int, depth: int, stride: int) -> None:
            super().__init__()
            if in_channel == depth:
                self.shortcut_layer = nn.MaxPool2d(1, stride)
            else:
                self.shortcut_layer = nn.Sequential(nn.Conv2d(in_channel, depth, (1, 1), stride, bias=False), nn.BatchNorm2d(depth))
            self.res_layer = nn.Sequential(
                nn.BatchNorm2d(in_channel),
                nn.Conv2d(in_channel, depth, (3, 3), (1, 1), 1, bias=False),
                nn.BatchNorm2d(depth),
                nn.PReLU(depth),
                nn.Conv2d(depth, depth, (3, 3), stride, 1, bias=False),
                nn.BatchNorm2d(depth),
            )

        def forward(self, x):
            return self.res_layer(x) + self.shortcut_layer(x)

    class Backbone(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.input_layer = nn.Sequential(nn.Conv2d(3, 64, (3, 3), 1, 1, bias=False), nn.BatchNorm2d(64), nn.PReLU(64))
            units = []
            for in_channel, depth, count in IR50_UNITS:
                units.append(BasicBlockIR(in_channel, depth, 2))
                units.extend(BasicBlockIR(depth, depth, 1) for _ in range(count - 1))
            self.body = nn.Sequential(*units)
            self.output_layer = nn.Sequential(
                nn.BatchNorm2d(512), nn.Dropout(0.4), nn.Flatten(), nn.Linear(512 * 7 * 7, 512), nn.BatchNorm1d(512, affine=False)
            )

        def forward(self, x):
            return self.output_layer(self.body(self.input_layer(x)))

    torch.manual_seed(0)
    return Backbone()


def build_adaface(source: Path, out: Path) -> dict:
    import numpy as np
    import onnxruntime as ort
    import torch
    from safetensors.torch import load_file

    state = load_file(str(source / "model.safetensors"))
    state = {key[len(STATE_PREFIX):]: value for key, value in state.items() if key.startswith(STATE_PREFIX)}
    model = ir50().eval()
    model.load_state_dict(state, strict=True)
    target = out / "embedder.onnx"
    sample = torch.randn(4, 3, 112, 112)
    with torch.no_grad():
        torch.onnx.export(model, (sample,), target, input_names=["input"], output_names=["embedding"],
                          dynamic_axes={"input": {0: "n"}, "embedding": {0: "n"}}, opset_version=17, dynamo=False)
        reference = model(sample).numpy()
    session = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"])
    exported = session.run(None, {"input": sample.numpy()})[0]
    a = reference / np.linalg.norm(reference, axis=1, keepdims=True)
    b = exported / np.linalg.norm(exported, axis=1, keepdims=True)
    return {"parityMinCosine": float((a * b).sum(axis=1).min()), "torch": torch.__version__, "onnxruntime": ort.__version__}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yunet", type=Path, required=True)
    parser.add_argument("--adaface", type=Path, required=True)
    parser.add_argument("--adaface-licence", type=Path, required=True)
    parser.add_argument("--adaface-card", type=Path, required=True)
    parser.add_argument("--sface", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    roots = {"yunet": args.yunet, "sface": args.sface, "adaface": args.adaface}
    for relative, expected in SOURCE_SHA256.items():
        group, name = relative.split("/", 1)
        actual = sha256(roots[group] / name)
        if actual != expected:
            raise SystemExit(f"source_mismatch: {relative} {actual}")

    record: dict = {"python": platform.python_version(), "packs": {}}
    for pack, embedder in ((ADAFACE_PACK, "adaface"), (SFACE_PACK, "sface")):
        directory = args.out / pack
        directory.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.yunet / "face_detection_yunet_2026may.onnx", directory / "detector.onnx")
        shutil.copyfile(args.yunet / "LICENSE", directory / "LICENSE-yunet")
        shutil.copyfile(args.yunet / "README.md", directory / "README-yunet.md")
        if embedder == "sface":
            shutil.copyfile(args.sface / "face_recognition_sface_2021dec.onnx", directory / "embedder.onnx")
            shutil.copyfile(args.sface / "LICENSE", directory / "LICENSE")
            shutil.copyfile(args.sface / "README.md", directory / "README.md")
            build = {}
        else:
            build = build_adaface(args.adaface, directory)
            shutil.copyfile(args.adaface_licence, directory / "LICENSE")
            shutil.copyfile(args.adaface_card, directory / "README.md")
        record["packs"][pack] = {
            "build": build,
            "files": {p.name: sha256(p) for p in sorted(directory.iterdir()) if p.is_file()},
        }
    (args.out / "build-record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

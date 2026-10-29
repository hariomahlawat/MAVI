# PoC S6: face embedder spike (plan D6; register C5A.3)

**Protocol:** `s6-embedder-spike-v1`, frozen in `tools/poc/faces_embedder_spike.py` before it ran (2026-10-29).
**Evidence class:** Development (ADR-020).
**Evidence:**
- `E:\MAVI-Controlled\PoC\S6\embedder-spike\`: `SHA256SUMS` SHA-256 `5495a8d43f1171a14e47bab681b1847b57fc518d90310d5aaa13a30f04985c48`.
- Pack payloads: `E:\MAVI-Controlled\PoC\S6\pack\` (`SHA256SUMS`).

## Packs built (`tools/vision/build_face_packs.py`)

Every source file is checked against a pinned SHA-256. The model files also equal their Git LFS oids.

| Component | Source | Licence, from its own LICENSE file | Payload SHA-256 |
|---|---|---|---|
| YuNet detector | opencv_zoo `48b10fa5`, `face_detection_yunet_2026may.onnx` | **MIT** (Shiqi Yu), `LICENSE-yunet` `c83b8120…d30` | `ebafce4e…f0f0` |
| AdaFace IR-50 WebFace4M | `minchul/cvlface_adaface_ir50_webface4m` `60a65bef`, `model.safetensors` `da82e6e1…845d`, exported to ONNX (opset 17) | **MIT** for the code (CVLface `308142aa`, `LICENSE` `95b6e493…1583`). The checkpoint ships no LICENSE file, and its card says to follow the training dataset's licence. WebFace4M is non-commercial research only, so the pack is **Development-only** (ADR-022 §2). | `fc9ced86…f344` |
| SFace (fallback) | opencv_zoo `48b10fa5`, `face_recognition_sface_2021dec.onnx` | **Apache-2.0**, `LICENSE` `cfc7749b…3d30` | `0ba9fbfa…4e79` |

**How the AdaFace pack was made:**
- The IR-50 graph is rebuilt from the AdaFace architecture (MIT) in the build script and loaded strictly from the safetensors file: all 467 tensors match.
- The snapshot's pickled `model.pt` and its remote code are never loaded or executed.
- The ONNX export matches PyTorch to a minimum cosine of 1.0.

**Checks of the pipeline code against OpenCV.** These compare the role's numpy pipeline with OpenCV 4.12:
- *YuNet decoding* equals `FaceDetectorYN` on 137 demo crops: 43 of 43 faces, with a maximum difference of 3e-5.
- *Five-landmark alignment plus SFace* agrees with `FaceRecognizerSF.alignCrop` and `feature` on 40 LFW images. The minimum embedding cosine is 0.996, and the mean absolute pixel difference is 0.84, from interpolation conventions.

## Method

**Data.** LFW, the standard 6,000-pair verification protocol: 10 folds, each of 300 matched and 300 mismatched pairs. Files: `lfw.tgz` SHA-256 `055f7d9c…36c0` and `pairs.txt` SHA-256 `ea42330c…1592`, both from scikit-learn's mirror. They stay on the Development host. LFW is an established public benchmark (ADR-017), and no MAVI labels were made.

**Pipeline.** This is the role's own code:
1. YuNet with score ≥ 0.5 on the whole image.
2. Pick the central face.
3. Align to 112×112.
4. Embed, L2-normalise and compare by cosine.

**Two conditions:**
- `native`: the median face shorter side is 92.8 px.
- `face32`: the image is downscaled so the face is 32 px, the floor of a usable face (ADR-022 §3).

**Detection failures:** 0 of 7,701 images in either condition.

**Decision rule (frozen).** Choose AdaFace if all three hold:
- ONNX parity ≥ 0.999;
- `native` accuracy ≥ 99.0 %;
- `face32` accuracy at least SFace's.

Otherwise choose SFace if its `native` accuracy ≥ 98.0 %.

## Result

| | 10-fold accuracy, native | 10-fold accuracy, face32 | face32 cosine at FAR 0.1 % (TAR) | face32 cosine at FAR 1 % (TAR) | Embed latency, CPU median |
|---|---:|---:|---:|---:|---:|
| **AdaFace IR-50** | **0.998** | **0.997** | 0.2121 (0.9957) | 0.1518 (0.998) | 115 ms |
| SFace | 0.9927 | 0.987 | 0.3484 (0.970) | 0.2953 (0.9813) | 24 ms |

The latency was measured on the laptop CPU under load from another session's job, so it is indicative only.

**Chosen: AdaFace IR-50.** The reference threshold is **cosine 0.2121**: AdaFace `face32` at FAR 0.1 %. It is recorded in `src/vision/config/faces/development-faces-adaface-v1.json` with its provenance.

## Limits (stated on the known-limits page)

- **LFW is easy.** It is frontal, well lit, and its faces are celebrities. WebFace4M is also built from web images of public figures, so identity overlap with LFW is possible and the accuracy above may be optimistic. Downscaling to 32 px simulates resolution, but not CCTV pose, blur, compression or lighting.
- **The threshold is context, not a decision rule.** It was not calibrated on CCTV.
- **The AdaFace checkpoint is research-only.** If the owner rules it out (decision D-S6-3), SFace is the built and hashed fallback. Its own numbers are above, and its reference threshold would be 0.3484.

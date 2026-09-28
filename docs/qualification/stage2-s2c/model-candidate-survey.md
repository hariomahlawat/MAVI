# Stage 2 S2c — Model Candidate Survey (planning record)

**Status:** Planning record for `docs/superpowers/plans/2026-09-28-stage2-s2c-learned-attribute-model-packs.md` §9. Survey date 2026-09-28.
**Nature of every figure below:** *reported by the cited source; not reproduced by MAVI.* No MAVI measurement exists yet. Nothing here selects a model; it feeds the shortlist that the S2c bake-off protocol freezes (plan §9.2, slice S2c.2), which re-runs this survey at freeze time.
**Licence statements** are what the cited page says. Model-card use statements, dataset terms and "do weights inherit dataset restrictions" are **not legal conclusions**; every one is an input to the human licence review (plan §23, U1). "UNVERIFIED" marks a claim that could not be confirmed from a primary source.

## 1. Findings that shape S2c

1. **Colour is rarely what published PAR scores measure.** Standard PETA-35 and RAPv1-51 evaluation subsets drop the colour labels, and PA-100K has none. Colour is scored on Market-1501 attributes and UPAR, and exists in the full PETA/RAP label sets.
2. **Cross-domain performance is much lower than in-domain.** MSP60K random vs cross-domain split: PromptPAR 78.8 → 63.2 mA, VTB 76.1 → 58.6 mA ([LLM-PAR, arXiv 2408.09720 Table 3](https://arxiv.org/html/2408.09720v1)). UPAR leave-one-dataset-out mA ≈ 64–71 vs 80+ in-domain ([arXiv 2209.02522](https://arxiv.org/abs/2209.02522)). Vehicle colour: the same ViT-B/16 reports 92.8 % top-1 on the Chen 2014 set and 66.2 % on UFPR-VCR; night images are < 10 % of UFPR-VCR and 32.4 % of its errors ([Lima et al., arXiv 2408.11589](https://arxiv.org/html/2408.11589)).
3. **Licence is the binding constraint.** PA-100K is stated as CC-BY 4.0 ([HydraPlus-Net README](https://github.com/xh-liu/HydraPlus-Net#pa-100k-dataset)); PETA is research-only/non-commercial, Market-1501 has no licence, UPAR annotations are CC-BY-NC-SA 3.0 ([UPAR README](https://github.com/speckean/upar_challenge)); RAP terms UNVERIFIED (site unreachable); DukeMTMC withdrawn in 2019 ([AIAAIC](https://www.aiaaic.org/aiaaic-repository/ai-algorithmic-and-automation-incidents/dukemtmc-dataset)); LUPerson (SOLIDER/HAP pre-training) forbids commercial use ([LUPerson](https://github.com/DengpanFu/LUPerson)). Vehicle: UFPR-VCR and UFPR-VeSV academic/non-commercial with signed agreement ([UFPR-VCR](https://github.com/Lima001/UFPR-VCR-Dataset)); VeRi-776 non-commercial on request ([VeRi](https://github.com/JDAI-CV/VeRidataset)); CompCars non-commercial, no derived commercial use ([CompCars](http://mmlab.ie.cuhk.edu.hk/datasets/comp_cars/index.html)); VCoR "© Original Authors"; Vehicle Color-24 repo has no licence ([repo](https://github.com/mendy-2013/Vehicle-Color-24-Dataset)); the Chen 2014 set is reported unavailable.
4. **Model-card and licence use restrictions:** OpenAI CLIP card — surveillance "always out-of-scope", any deployed use "currently out of scope" ([card](https://github.com/openai/CLIP/blob/main/model-card.md)); LAION/DataComp OpenCLIP cards repeat it ([B/16 LAION-2B](https://huggingface.co/laion/CLIP-ViT-B-16-laion2B-s34B-b88K)); Apple MobileCLIP/DFN weights research-only ([LICENSE_MODELS](https://github.com/apple/ml-mobileclip/blob/main/LICENSE_MODELS), [DFN](https://huggingface.co/apple/DFN5B-CLIP-ViT-H-14-378/blob/main/LICENSE)); MetaCLIP CC-BY-NC ([MetaCLIP](https://github.com/facebookresearch/MetaCLIP)); DINOv3 and SAM 3 licences prohibit military/warfare/espionage/ITAR use ([DINOv3](https://github.com/facebookresearch/dinov3/blob/main/LICENSE.md), [SAM 3](https://github.com/facebookresearch/sam3/blob/main/LICENSE)); SigLIP/SigLIP 2 and DINOv2 Apache-2.0 ([SigLIP 2](https://huggingface.co/google/siglip2-base-patch16-224), [DINOv2](https://github.com/facebookresearch/dinov2)); PaliGemma prohibited-use policy includes tracking/monitoring people without consent ([policy](https://ai.google.dev/gemma/prohibited_use_policy)); Qwen2.5-VL-3B non-commercial.
5. **torchvision pretrained weights:** the docs say pretrained models "may have their own licenses or terms and conditions derived from the dataset used for training" ([torchvision](https://docs.pytorch.org/vision/stable/models.html)); ImageNet terms are non-commercial research/education ([image-net.org](https://www.image-net.org/download.php)); SWAG weights CC-BY-NC.
6. **Task-shaped permissive checkpoints are industrial and opaque:** Intel Open Model Zoo models carry Apache-2.0 via `model.yml`, ship as OpenVINO IR only, and do not disclose training data; OMZ is in maintenance mode.

## 2. Person attributes (T-PC colour, T-PO carried objects/headwear)

### 2.1 Academic state of the art (reported mA / F1; research code, PyTorch)

| Model (venue) | Architecture | Input | PA-100K | PETA | RAPv1 | Weights | Code licence | Deployability note |
|---|---|---|---|---|---|---|---|---|
| Strong baseline / Rethinking PAR ([repo](https://github.com/valencebond/Rethinking_of_PAR)) | ResNet-50; Swin-S | 256×192 | 80.21/87.40 (Swin-S 82.19/88.18) | 83.96/86.35 | 79.27/79.95 | link empty | no LICENSE file | recipe only |
| fast-reid FastAttr ([repo](https://github.com/JDAI-CV/fast-reid/tree/master/projects/FastAttr)) | ResNet | — | 80.50 mA | — | — | none | Apache-2.0 | recipe (Apache) |
| UPAR baseline, WACV 2023 ([arXiv](https://arxiv.org/abs/2209.02522)) | ConvNeXt-B | — | 84.8/90.2 | 88.4/89.9 | RAPv2 79.9/81.0 | not found | CC-BY-NC-SA | covers colour; NC data |
| DAFL, AAAI 2022 | ResNet-50 + cross-attention | 256×192 | 83.54/88.09 | 87.07/86.40 | 83.72/80.29 | UNVERIFIED | — | — |
| VTB, TCSVT 2022 ([repo](https://github.com/cxh0519/VTB)) | ViT-B/16 + text | 256×192 | 83.72/88.21 | 85.31/86.71 | 82.67/80.84 | none | MIT | trained on restricted data |
| PARFormer, TCSVT 2023 ([repo](https://github.com/xwf199/PARFormer)) | Swin-L | — | 84.46/88.52 | 89.32/89.06 | 84.13/81.35 | not found | no LICENSE | heavy |
| SOLIDER, CVPR 2023 ([repo](https://github.com/tinyvision/SOLIDER)) | Swin, human-centric SSL | — | 84.14–86.37 | — | — | backbones | Apache-2.0 | LUPerson pre-training (NC) |
| HAP, NeurIPS 2023 ([repo](https://github.com/junkunyuan/HAP)) | ViT-B MIM | — | 86.54 mA | 88.36 | 82.91 | pre-trained only | no LICENSE found | LUPerson (NC) |
| PromptPAR, TCSVT 2024 ([OpenPAR](https://github.com/Event-AHU/OpenPAR/tree/main/PromptPAR)) | frozen CLIP ViT-L/14 + prompts | 224 | 87.47/90.15 | 88.76/89.18 | 85.45/82.38 | yes (RAP/PETA) | MIT | restricted data + CLIP card |
| ViTA-PAR, 2025 ([arXiv](https://arxiv.org/html/2506.01411)) | CLIP B/16, L/14 | — | 87.82/90.93 | 89.68 | 85.96 | — | CC BY-NC-ND 4.0 | NC |
| FRDL, ICML 2024 ([arXiv](https://arxiv.org/abs/2405.04858)) | — | — | 89.44/88.05 | 88.59/89.03 | 87.72/79.16 | not checked | — | — |
| LLM-PAR, AAAI 2025 ([arXiv](https://arxiv.org/abs/2408.09720)) | EVA-ViT-G + Q-Former + Vicuna-7B | — | 91.09/90.41 | 92.25/90.39 | 87.80/82.64 | UNVERIFIED | MIT | billions of parameters |
| VLM-PAR, Dec 2025 ([arXiv](https://arxiv.org/abs/2512.22217)) | frozen SigLIP 2 + cross-attention | — | 92.88/92.32 | 93.52/92.64 | Market 85.38/79.17 | not found | — | backbone Apache; fine-tune data restricted |

### 2.2 Released / industrial models

| Model | Size | Input | Attributes | Reported | Format | Licence | Training data |
|---|---|---|---|---|---|---|---|
| OMZ person-attributes-recognition-crossroad-0230 ([README](https://github.com/openvinotoolkit/open_model_zoo/blob/master/models/intel/person-attributes-recognition-crossroad-0230/README.md)) | 0.735 M params, 0.174 GFLOPs | 160×80 BGR | has_bag, has_backpack, has_hat (+ is_male etc. to discard), top/bottom colour-point outputs | F1 bag 0.66, backpack 0.77, hat 0.64 | OpenVINO IR | Apache-2.0 (`model.yml`) | not disclosed |
| OMZ …-0234 / …-0238 | 23.5 M / 21.8 M | 160×80 | 7 attributes (bag, hat; no backpack) | F1 bag 0.44/0.48, hat 0.74/0.42 | IR | Apache-2.0 | not disclosed |
| Awiros person-attribute-recognition ([HF](https://huggingface.co/Awiros/person-attribute-recognition), Aug 2026) | ConvNeXt V2-Tiny (≈ 28 M, estimate) | UNVERIFIED | top/bottom colour, backpack, handbag, head accessory (+ gender/age heads to discard) | vendor's gated CCTV benchmark: top 74.8 %, bottom 75.2 %, backpack 94.2 %, handbag 91.3 %, head accessory 84.7 % | ONNX | HF "other", terms not stated; gated | CCTV crops, SSL, pseudo-labels from an unnamed VLM |
| PP-Human attribute ([docs](https://github.com/PaddlePaddle/PaddleDetection/blob/release/2.8/deploy/pipeline/docs/tutorials/pphuman_attribute_en.md)) | PP-LCNet/HGNet | — | 26 (hat, bags; no colour) | mA 94.5–95.4 mixed set | Paddle | Apache-2.0 code | PA100k + RAPv2 + PETA + business data |

## 3. Vehicle colour (T-VC)

| Method / model | Architecture | Reported | Weights | Licence | Note |
|---|---|---|---|---|---|
| Lima et al. 2024 benchmark ([arXiv](https://arxiv.org/html/2408.11589)) | EfficientNet-V2 / MobileNet-V3 / ResNet-34 / ViT-B/16 at 224 | Chen top-1 84.6/90.6/89.0/92.8 %; UFPR-VCR ViT-B/16 66.2 % | none | — | benchmark saturation vs CCTV |
| Orrú et al. 2026 ([arXiv](https://arxiv.org/html/2606.13625v1)) | ensemble incl. frozen DINOv3 + synthetic minority data | UFPR-VeSV 94.6 % micro / 79.7 % macro; 58.5 % of errors "inherently ambiguous" | code "soon" | — | ambiguity ceiling (IR, grey/silver) |
| SMNN-MSFF ([arXiv](https://arxiv.org/abs/2107.09944)) | multi-scale fusion | Vehicle Color-24 94.96 % mAP | repo, no licence | none | — |
| OMZ vehicle-attributes-recognition-barrier-0042 ([README](https://github.com/openvinotoolkit/open_model_zoo/blob/master/models/intel/vehicle-attributes-recognition-barrier-0042/README.md)) | modified ResNet-18, 11.2 M | colour avg 82.71 %, yellow 61.5 % | IR | Apache-2.0 | 7 colours; front-facing, < 50 % occlusion; data not disclosed |
| OMZ …-0039 | 0.63 M | colour avg 81.15 %, yellow 54.0 % | IR | Apache-2.0 | ≥ 72 px width |
| PP-Vehicle PP-LCNet attribute ([docs](https://github.com/PaddlePaddle/PaddleDetection/blob/release/2.6/deploy/pipeline/docs/tutorials/ppvehicle_attribute.md)) | PP-LCNet | colour 90.81 % on VeRi val | Paddle | Apache-2.0 code | weights from VeRi (NC) |
| NVIDIA DeepStream Secondary_CarColor | ResNet-18 | — | TensorRT | DeepStream EULA | deprecated since DS 6.4 |
| NVIDIA TAO VehicleTypeNet/MakeNet | ResNet-18 | — | ETLT/TensorRT | NVIDIA model licence (per-version UNVERIFIED) | no colour output |
| HF piotreksl/vehicle-color-recognition ([HF](https://huggingface.co/piotreksl/vehicle-color-recognition)) | EfficientNet-B4 | none | .pth | MIT card | undisclosed data (likely VCoR) |

## 4. Foundation-model routes (both tasks)

| Family | Licence (weights) | Relevant evidence | Limitation |
|---|---|---|---|
| SigLIP / SigLIP 2 | Apache-2.0 | VLM-PAR builds on frozen SigLIP 2 | ≈ 0.2 B+ parameters at base; no training-free PAR result found; CPU cost |
| DINOv2 | Apache-2.0 | strong linear probes generally; none found for PAR/colour | colour may be suppressed by invariance training (UNVERIFIED hypothesis) |
| OpenAI CLIP / OpenCLIP (LAION, DataComp) | MIT, with card use statements | attribute-binding weakness documented ([arXiv 2502.03566](https://arxiv.org/pdf/2502.03566)); low-res degradation ([LR0.FM, arXiv 2502.03950](https://arxiv.org/abs/2502.03950)) | surveillance/deployed use out of scope on the cards |
| MobileCLIP/DFN, MetaCLIP, DINOv3, SAM 3 | research-only / NC / use-restricted | — | excluded pending review |
| Small generative VLMs (Florence-2 MIT; SmolVLM2, Moondream2, Qwen3-VL-2B Apache-2.0; InternVL3-1B MIT) | as listed | no PAR/colour result found | no native calibration; decoding determinism; cost per crop — labelling assistant only |
| Segmentation + colour naming (SAM 2.1 Apache-2.0; SCHP MIT code on NC data; van de Weijer w2c — no licence stated) | as listed | — | masks unreliable at 64 px and on IR; w2c licence unknown → MAVI builds its own Lab naming |

## 5. Questions for the human licence review (plan U1)

1. ImageNet-pretrained torchvision/timm weights: acceptable provenance for operational redistribution?
2. Intel OMZ person/vehicle models: training data; is Apache-2.0 on the IR sufficient?
3. Awiros model: licence terms, redistribution, identity of the pseudo-labelling model.
4. PA-100K: does CC-BY 4.0 cover the images as well as annotations; data-protection position for training on images of real people.
5. OpenAI/LAION card "surveillance out of scope": binding restriction or advisory?
6. SigLIP 2 / WebLI: any terms beyond Apache-2.0?
7. May checkpoints trained on non-commercial data (PETA, RAP, Market, UPAR, LUPerson, VeRi, UFPR) be used for **internal evaluation** as upper-bound references?
8. RAP v2, MSP60K, Chen 2014 dataset terms.
9. NVIDIA TAO / DeepStream model terms (only if revisited).
10. Privacy/retention for labelling operational CCTV crops (faces and plates visible).

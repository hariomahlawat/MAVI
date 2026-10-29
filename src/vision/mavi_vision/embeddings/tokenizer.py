"""The SigLIP 2 text tokenizer contract (ADR-021 §1): lowercase, SentencePiece ids, EOS, pad to 64.

The pack's ``tokenizer.model`` is read by ``sentencepiece`` alone; the runtime never uses ``transformers`` or
``tokenizers``. ``tools/vision/build_siglip2_pack.py::sentencepiece_ids`` checks this rule against the reference
Hugging Face tokenizer on the build's parity texts, so the two must stay identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

TEXT_LENGTH = 64
EOS_ID = 1
PAD_ID = 0


class SentencePieceEncoder(Protocol):
    def encode(self, text: str) -> list[int]: ...


def sentencepiece_ids(processor: SentencePieceEncoder, text: str, length: int = TEXT_LENGTH) -> list[int]:
    """``encode(text.lower())[:length-1] + [EOS]``, padded with ``PAD`` to ``length``."""
    ids = list(processor.encode(text.lower()))[: length - 1] + [EOS_ID]
    return ids + [PAD_ID] * (length - len(ids))


def load_sentencepiece(path: Path) -> SentencePieceEncoder:
    import sentencepiece  # noqa: PLC0415 - embeddings-onnx-v1 runtime only

    return sentencepiece.SentencePieceProcessor(model_file=str(path))


__all__ = ["EOS_ID", "PAD_ID", "TEXT_LENGTH", "SentencePieceEncoder", "load_sentencepiece", "sentencepiece_ids"]

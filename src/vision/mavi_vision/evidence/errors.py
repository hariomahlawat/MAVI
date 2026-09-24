from __future__ import annotations


class EvidenceError(ValueError):
    """A Track Evidence Set invariant failed; the attempt fails closed.

    The code is a stable internal identifier. It is never shown to operators
    or sent to the platform; the worker maps any processing failure to its
    reviewed wire failure code.
    """

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)

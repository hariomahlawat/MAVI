from __future__ import annotations

import asyncio
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Callable, ParamSpec, Protocol, TypeVar, runtime_checkable


P = ParamSpec("P")
T = TypeVar("T")


@runtime_checkable
class ProcessExecutor(Protocol):
    """Model-neutral executor for synchronous process-bound vision work."""

    async def run(
        self,
        func: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T: ...


class VisionExecutionLane:
    """Serialize all synchronous vision-runtime work onto one dedicated thread.

    The lane deliberately does not attempt thread cancellation. If the awaiting
    coroutine is cancelled, already-submitted native work is allowed to unwind
    on the dedicated thread. This is required for model runtimes that cannot be
    safely interrupted from Python.
    """

    def __init__(self, *, thread_name_prefix: str = "mavi-vision") -> None:
        if not thread_name_prefix or thread_name_prefix != thread_name_prefix.strip():
            raise ValueError("vision_execution_lane_thread_name_invalid")

        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=thread_name_prefix,
        )
        self._state_lock = threading.Lock()
        self._close_lock = asyncio.Lock()
        self._closed = False

    async def run(
        self,
        func: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        if inspect.iscoroutinefunction(func):
            raise TypeError("vision_execution_lane_requires_sync_callable")

        loop = asyncio.get_running_loop()
        invocation = partial(func, *args, **kwargs)

        # Submission and close-state transition share one lock so a call that
        # has been accepted cannot race with executor shutdown.
        with self._state_lock:
            if self._closed:
                raise RuntimeError("vision_execution_lane_closed")
            future = loop.run_in_executor(self._executor, invocation)

        try:
            # Shielding prevents asyncio cancellation from propagating into the
            # concurrent future. Python cannot safely cancel an active native
            # CUDA/MMDetection call; Task 10 containment happens above this lane.
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # The native call may still complete after its awaiter has gone away.
            # Consume any eventual exception to avoid an un-retrieved-future warning.
            future.add_done_callback(_consume_background_result)
            raise

    async def close(self) -> None:
        """Reject new work and wait for every accepted call to leave the lane."""
        async with self._close_lock:
            with self._state_lock:
                if self._closed:
                    return
                self._closed = True

            shutdown_task = asyncio.create_task(
                asyncio.to_thread(
                    self._executor.shutdown,
                    wait=True,
                    cancel_futures=False,
                )
            )
            try:
                await asyncio.shield(shutdown_task)
            except asyncio.CancelledError:
                # A close operation owns resource cleanup. Preserve cancellation
                # semantics only after the executor has actually shut down.
                await shutdown_task
                raise

    async def __aenter__(self) -> "VisionExecutionLane":
        with self._state_lock:
            if self._closed:
                raise RuntimeError("vision_execution_lane_closed")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> None:
        del exc_type, exc, traceback
        await self.close()


def _consume_background_result(future: asyncio.Future[object]) -> None:
    if future.cancelled():
        return
    try:
        future.exception()
    except asyncio.CancelledError:
        return

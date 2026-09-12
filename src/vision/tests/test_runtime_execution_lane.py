from __future__ import annotations

import asyncio
import threading

import pytest

from mavi_vision.runtime.execution_lane import ProcessExecutor, VisionExecutionLane


def test_execution_lane_serializes_work_on_one_dedicated_thread() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()
        event_loop_thread = threading.get_ident()
        first_started = threading.Event()
        release_first = threading.Event()
        state_lock = threading.Lock()
        active_count = 0
        maximum_active_count = 0
        thread_ids: list[int] = []

        def work(name: str, *, block: bool) -> tuple[str, int]:
            nonlocal active_count, maximum_active_count
            thread_id = threading.get_ident()
            with state_lock:
                active_count += 1
                maximum_active_count = max(maximum_active_count, active_count)
                thread_ids.append(thread_id)

            try:
                if block:
                    first_started.set()
                    if not release_first.wait(timeout=5.0):
                        raise TimeoutError("test release signal was not received")
                return name, thread_id
            finally:
                with state_lock:
                    active_count -= 1

        try:
            first = asyncio.create_task(lane.run(work, "first", block=True))
            assert await asyncio.to_thread(first_started.wait, 5.0) is True

            second = asyncio.create_task(lane.run(work, "second", block=False))
            await asyncio.sleep(0)
            assert second.done() is False

            release_first.set()
            first_result, second_result = await asyncio.gather(first, second)
        finally:
            release_first.set()
            await lane.close()

        assert first_result[0] == "first"
        assert second_result[0] == "second"
        assert first_result[1] == second_result[1]
        assert first_result[1] != event_loop_thread
        assert thread_ids == [first_result[1], second_result[1]]
        assert maximum_active_count == 1

    asyncio.run(scenario())


def test_execution_lane_structurally_implements_process_executor() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()
        try:
            assert isinstance(lane, ProcessExecutor)
        finally:
            await lane.close()

    asyncio.run(scenario())


def test_execution_lane_forwards_arguments_and_return_value() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()

        def combine(left: int, right: int, *, scale: int) -> int:
            return (left + right) * scale

        try:
            result = await lane.run(combine, 2, 3, scale=4)
        finally:
            await lane.close()

        assert result == 20

    asyncio.run(scenario())


def test_execution_lane_propagates_callable_exception() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()

        def fail() -> None:
            raise LookupError("backend failed")

        try:
            with pytest.raises(LookupError, match="backend failed"):
                await lane.run(fail)
        finally:
            await lane.close()

    asyncio.run(scenario())


def test_execution_lane_rejects_coroutine_function() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()

        async def invalid() -> None:
            return None

        try:
            with pytest.raises(
                TypeError,
                match="vision_execution_lane_requires_sync_callable",
            ):
                await lane.run(invalid)
        finally:
            await lane.close()

    asyncio.run(scenario())


def test_execution_lane_rejects_work_after_close() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()
        await lane.close()
        await lane.close()

        with pytest.raises(RuntimeError, match="vision_execution_lane_closed"):
            await lane.run(lambda: None)

    asyncio.run(scenario())


def test_execution_lane_cancellation_does_not_cancel_native_work() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()

        def native_work() -> None:
            started.set()
            try:
                if not release.wait(timeout=5.0):
                    raise TimeoutError("test release signal was not received")
            finally:
                completed.set()

        try:
            task = asyncio.create_task(lane.run(native_work))
            assert await asyncio.to_thread(started.wait, 5.0) is True

            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert completed.is_set() is False
            release.set()
            assert await asyncio.to_thread(completed.wait, 5.0) is True
        finally:
            release.set()
            await lane.close()

    asyncio.run(scenario())


def test_execution_lane_close_waits_for_already_submitted_work() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()
        started = threading.Event()
        release = threading.Event()
        completed = threading.Event()

        def work() -> None:
            started.set()
            if not release.wait(timeout=5.0):
                raise TimeoutError("test release signal was not received")
            completed.set()

        task = asyncio.create_task(lane.run(work))
        assert await asyncio.to_thread(started.wait, 5.0) is True

        close_task = asyncio.create_task(lane.close())
        await asyncio.sleep(0)
        assert close_task.done() is False

        release.set()
        await task
        await close_task
        assert completed.is_set() is True

    asyncio.run(scenario())


def test_execution_lane_context_manager_closes_lane() -> None:
    async def scenario() -> None:
        lane = VisionExecutionLane()
        async with lane:
            assert await lane.run(lambda: 7) == 7

        with pytest.raises(RuntimeError, match="vision_execution_lane_closed"):
            await lane.run(lambda: 8)

    asyncio.run(scenario())

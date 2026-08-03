from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

TaskResult = TypeVar("TaskResult")


async def cancel_task(task: asyncio.Task[Any] | None) -> None:
    """Cancel and await a task, including tasks not registered with a supervisor."""
    if task is None or task.done() or task is asyncio.current_task():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@dataclass(slots=True)
class _TaskRecord:
    """Metadata needed to identify and remove one supervised task."""

    task: asyncio.Task[Any]
    owner: str
    label: str
    scope: TaskScope


class TaskScope:
    """Own a related set of background tasks under one lifecycle boundary."""

    def __init__(self, supervisor: TaskSupervisor, name: str) -> None:
        """Create a named scope managed by ``supervisor``."""
        self._supervisor = supervisor
        self._name = name
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def name(self) -> str:
        """Return the stable owner name used in task diagnostics."""
        return self._name

    def child(self, name: str) -> TaskScope:
        """Create a child scope for a nested component or dialog."""
        return self._supervisor.create_scope(f"{self._name}/{name}")

    def create_task(
        self,
        coroutine: Coroutine[Any, Any, TaskResult],
        *,
        name: str,
    ) -> asyncio.Task[TaskResult]:
        """Create and register a task whose owner is this scope."""
        return self._supervisor._create_task(self, coroutine, name=name)

    async def cancel_task(self, task: asyncio.Task[Any] | None) -> None:
        """Cancel and await one task, including tasks created outside this scope."""
        await cancel_task(task)

    async def cancel_all(self) -> None:
        """Cancel and await every unfinished task owned by this scope."""
        await self._supervisor._cancel_tasks(tuple(self._tasks))

    def _add(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)

    def _discard(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)


class TaskSupervisor:
    """Track background tasks and make cancellation and failure ownership explicit."""

    def __init__(self) -> None:
        """Create an open supervisor for one application event loop."""
        self._tasks: dict[asyncio.Task[Any], _TaskRecord] = {}
        self._closing = False
        self._closed = False
        self._shutdown_future: asyncio.Future[None] | None = None

    def create_scope(self, name: str) -> TaskScope:
        """Create a task owner that participates in supervisor shutdown."""
        if self._closing:
            raise RuntimeError("任务监督器已关闭")
        if not name.strip():
            raise ValueError("任务所有者名称不能为空")
        return TaskScope(self, name)

    async def cancel_task(self, task: asyncio.Task[Any] | None) -> None:
        """Cancel and await a task without leaking its exception or cancellation."""
        await cancel_task(task)

    async def shutdown(self) -> None:
        """Cancel and await all supervised tasks; repeated calls are harmless."""
        if self._closed:
            return
        if self._shutdown_future is not None:
            await asyncio.shield(self._shutdown_future)
            return

        self._closing = True
        loop = asyncio.get_running_loop()
        self._shutdown_future = loop.create_future()
        try:
            await self._cancel_tasks(tuple(self._tasks))
        except BaseException as exc:
            self._shutdown_future.set_exception(exc)
            raise
        else:
            self._closed = True
            self._shutdown_future.set_result(None)

    def pending_tasks(self) -> tuple[asyncio.Task[Any], ...]:
        """Return unfinished supervised tasks for diagnostics and tests."""
        return tuple(task for task in self._tasks if not task.done())

    def _create_task(
        self,
        scope: TaskScope,
        coroutine: Coroutine[Any, Any, TaskResult],
        *,
        name: str,
    ) -> asyncio.Task[TaskResult]:
        """Create one task and record its owner before it can run."""
        if self._closing:
            coroutine.close()
            raise RuntimeError("任务监督器已关闭")
        if not name.strip():
            coroutine.close()
            raise ValueError("任务名称不能为空")

        task = asyncio.create_task(coroutine, name=f"{scope.name}:{name}")
        record = _TaskRecord(task=task, owner=scope.name, label=name, scope=scope)
        self._tasks[task] = record
        scope._add(task)
        task.add_done_callback(self._on_task_done)
        return task

    async def _cancel_tasks(self, tasks: tuple[asyncio.Task[Any], ...]) -> None:
        """Cancel a task snapshot while leaving the caller task alive."""
        current_task = asyncio.current_task()
        pending = tuple(task for task in tasks if not task.done() and task is not current_task)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        """Remove a completed task and log failures before they become unobserved."""
        record = self._tasks.pop(task, None)
        if record is None:
            return
        record.scope._discard(task)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            logger.error(
                "后台任务失败: owner=%s task=%s",
                record.owner,
                record.label,
                exc_info=(type(exception), exception, exception.__traceback__),
            )

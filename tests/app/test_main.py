import asyncio

from bilihud.main import cancel_pending_tasks


def test_cancel_pending_tasks_cancels_unfinished_tasks():
    cleanup_seen = False

    async def pending_task():
        nonlocal cleanup_seen
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleanup_seen = True
            raise

    async def run_test():
        task = asyncio.create_task(pending_task())
        await asyncio.sleep(0)

        await cancel_pending_tasks(asyncio.get_running_loop(), exclude={asyncio.current_task()})

        assert task.cancelled()
        assert cleanup_seen is True

    asyncio.run(run_test())

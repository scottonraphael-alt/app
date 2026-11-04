"""Bounded independent dossier processing, with structured cancellation."""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def process(cursor, callback, *, limit=3):
    queue = asyncio.Queue(maxsize=limit * 2)

    async def consume():
        while True:
            row = await queue.get()
            try:
                if row is None:
                    return
                try:
                    await callback(row)
                except Exception:
                    logger.exception('Traitement du dossier à reprendre (%s).', row.get('_id'))
            finally:
                queue.task_done()

    tasks = [asyncio.create_task(consume()) for _ in range(limit)]
    try:
        async for row in cursor:
            await queue.put(row)
        for _ in tasks:
            await queue.put(None)
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

import asyncio
import signal

import uvicorn
from temporalio.worker import Worker

from app.config.observability import init_tracer_provider
from app.config.settings import settings
from app.config.temporal import connect_temporal
from app.utils.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

# Investigation workflow definitions are registered here as they are built.
WORKFLOWS: list = []


async def _run_temporal_worker(stop_event: asyncio.Event) -> None:
    client = await connect_temporal()
    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE_WORKFLOW,
        workflows=WORKFLOWS,
        max_concurrent_workflow_tasks=settings.WORKFLOW_MAX_CONCURRENT_RUNS,
    )
    logger.info(
        "temporal_worker_starting",
        task_queue=settings.TEMPORAL_TASK_QUEUE_WORKFLOW,
        workflows=[w.__name__ for w in WORKFLOWS],
    )

    worker_task = asyncio.create_task(worker.run())
    stop_task = asyncio.create_task(stop_event.wait())

    done, _ = await asyncio.wait(
        {worker_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_task in done:
        logger.info("temporal_worker_shutting_down")
        await worker.shutdown()
        await worker_task


async def _run_health_server(stop_event: asyncio.Event) -> None:
    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=settings.HEALTH_PORT,
        log_config=None,
        access_log=False,
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(stop_event.wait())

    done, _ = await asyncio.wait(
        {serve_task, stop_task},
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_task in done:
        server.should_exit = True
        await serve_task


async def main() -> None:
    init_tracer_provider()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        if not stop_event.is_set():
            logger.info("shutdown_signal_received")
            stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            pass

    tasks = [_run_health_server(stop_event)]
    if WORKFLOWS:
        tasks.append(_run_temporal_worker(stop_event))
    else:
        logger.info("temporal_worker_idle_no_workflows_registered")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())

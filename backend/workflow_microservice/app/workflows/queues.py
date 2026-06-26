from app.config.settings import settings

WORKFLOW_QUEUE = settings.TEMPORAL_TASK_QUEUE_WORKFLOW
CPU_QUEUE = settings.TEMPORAL_TASK_QUEUE_CPU
DB_QUEUE = settings.TEMPORAL_TASK_QUEUE_DB

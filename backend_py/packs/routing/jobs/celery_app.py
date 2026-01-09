# =============================================================================
# SOLVEREIGN Routing Pack - Celery Application
# =============================================================================
# Celery configuration for async route optimization jobs.
#
# Usage:
#     celery -A packs.routing.jobs.celery_app worker --loglevel=info
# =============================================================================

import os
from celery import Celery

# Get broker URL from environment (defaults to local Redis)
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# Create Celery app
celery_app = Celery(
    "routing",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["packs.routing.jobs.tasks"]
)

# Configure Celery
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Berlin",
    enable_utc=True,

    # Task execution settings
    task_acks_late=True,                    # Acknowledge after task completes
    task_reject_on_worker_lost=True,        # Requeue if worker dies
    task_time_limit=600,                    # Hard limit: 10 minutes
    task_soft_time_limit=540,               # Soft limit: 9 minutes (allows cleanup)

    # Result settings
    result_expires=86400,                   # Results expire after 24 hours

    # Worker settings
    worker_prefetch_multiplier=1,           # One task at a time (routing is CPU intensive)
    worker_max_tasks_per_child=10,          # Restart worker after 10 tasks (memory cleanup)

    # Routing-specific queues
    task_routes={
        "packs.routing.jobs.tasks.solve_routing_scenario": {"queue": "routing"},
        "packs.routing.jobs.tasks.repair_route": {"queue": "routing"},
    },

    # Default queue
    task_default_queue="routing",
)

# Optional: Beat schedule for periodic tasks (future use)
celery_app.conf.beat_schedule = {
    # Example: Clean up old job results daily
    # "cleanup-old-results": {
    #     "task": "packs.routing.jobs.tasks.cleanup_old_results",
    #     "schedule": 86400.0,  # Daily
    # },
}

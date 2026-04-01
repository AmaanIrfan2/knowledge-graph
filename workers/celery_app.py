from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger

from config.settings import REDIS_URL, LOG_FORMAT, LOG_DATE_FORMAT, LOG_LEVEL
import logging

app = Celery("youtube_scraper", broker=REDIS_URL, backend=REDIS_URL, include=["workers.tasks"])

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,                # ack only after task completes — prevents loss on worker shutdown
    worker_prefetch_multiplier=1,       # prefetch 1 task per worker process — reduces lost-task window
    task_reject_on_worker_lost=True,    # requeue task if worker process is killed mid-execution
)


def _apply_log_format(logger, **kwargs):
    for handler in logger.handlers:
        handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))


after_setup_logger.connect(_apply_log_format)
after_setup_task_logger.connect(_apply_log_format)
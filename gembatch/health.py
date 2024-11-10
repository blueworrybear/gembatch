"""Define firebase cron jobs."""

from firebase_admin import firestore  # type: ignore
from firebase_functions import scheduler_fn
from google.cloud import firestore as fs  # type: ignore

from gembatch import configs, models, utils

POLL_INTERVAL = str(configs.GEMBATCH_HEALTH_CHECK_POLL_INTERVAL.value)


@scheduler_fn.on_schedule(
    schedule="*/" + POLL_INTERVAL + " * * * *",
    region=configs.GEMBATCH_REGION.value,
    max_instances=1,
    concurrency=1,
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
    timeout_sec=1800,
)
def gembatch_health_check(_):
    """Health check for gembatch."""
    db = firestore.client()
    docs = (
        db.collection(configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value)
        .where(filter=fs.FieldFilter("status", "==", models.StatusEnum.RUNNING))
        .stream()
    )
    check_status = utils.CloudRunQueue.open("checkRunningGemBatchJobStatus")
    for doc in docs:
        job = models.BatchJob.from_dict(doc.to_dict())
        check_status.run(job_id=job.uuid)

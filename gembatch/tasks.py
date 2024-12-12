"""Define firebase cloud run tasks."""

import datetime as dt
import itertools
import uuid
from typing import Iterable
import importlib

from firebase_admin import firestore  # type: ignore
from firebase_functions import firestore_fn, logger, options, tasks_fn  # type: ignore
from google.cloud import firestore as fs  # type: ignore

from gembatch import configs, gemini, models, utils, types

JOB_QUEUE_COLLECTION = configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value
JOBS_IN_QUEUE_FILTER = fs.Or(
    [
        fs.FieldFilter("status", "==", models.StatusEnum.NEW),
        fs.And(
            [
                fs.FieldFilter("status", "==", models.StatusEnum.FAILED),
                fs.FieldFilter("retries", "<", configs.GEMBATCH_MAX_RETRIES.value),
            ]
        ),
    ]
)


@firestore_fn.on_document_created(
    document=configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value + "/{job_id}",
    region=configs.GEMBATCH_REGION.value,
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
    timeout_sec=600,
)
def on_gembatch_job_created(
    event: firestore_fn.Event[firestore_fn.DocumentSnapshot | None],
):
    """Handle the creation of a new gem batch job."""
    if not event.data or not event.data.exists:
        raise ValueError("Document does not exist.")
    job = models.Job.from_dict(event.data.to_dict())
    q = utils.CloudRunQueue.open("consumeGemBatchJob")
    q.run(model=job.model)


@firestore_fn.on_document_updated(
    document=configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value + "/{job_id}",
    region=configs.GEMBATCH_REGION.value,
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
    timeout_sec=600,
)
def on_gembatch_job_updated(
    event: firestore_fn.Event[
        firestore_fn.Change[firestore_fn.DocumentSnapshot | None]
    ],
):
    """Handle the update of a gem batch job."""
    if not event.data.after or not event.data.after.exists:
        raise ValueError("Document does not exist.")
    job = models.Job.from_dict(event.data.after.to_dict())
    if job.status == models.StatusEnum.COMPLETED:
        logger.info("Job already completed.")
        return
    elif (
        job.status == models.StatusEnum.PENDING
        or job.status == models.StatusEnum.RUNNING
    ):
        logger.info("Job is ongoing.")
        return
    q = utils.CloudRunQueue.open("consumeGemBatchJob")
    q.run(model=job.model)


@firestore_fn.on_document_created(
    document=configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value + "/{job_id}",
    region=configs.GEMBATCH_REGION.value,
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
)
def on_gembatch_batch_job_created(_):
    """Handle the creation of a new gem batch job."""
    q = utils.CloudRunQueue.open("runGemBatchJob")
    q.run()


@firestore_fn.on_document_updated(
    document=configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value + "/{job_id}",
    region=configs.GEMBATCH_REGION.value,
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
    timeout_sec=600,
)
def on_gembatch_batch_job_updated(_):
    """Handle the update of a gem batch job."""
    q = utils.CloudRunQueue.open("runGemBatchJob")
    q.run()


@tasks_fn.on_task_dispatched(
    retry_config=options.RetryConfig(
        max_attempts=2, max_backoff_seconds=300, min_backoff_seconds=10
    ),
    rate_limits=options.RateLimits(max_concurrent_dispatches=1),
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
    max_instances=1,
    concurrency=1,
    region=configs.GEMBATCH_REGION.value,
    timeout_sec=1800,
)
def consumeGemBatchJob(req: tasks_fn.CallableRequest):  # pylint: disable=[invalid-name]
    """
    Consume a gem batch job from the queue.
    """
    model = req.data["model"]
    db = firestore.client()
    consume_gembatch_job(db, model)


def get_queueing_job_count_for_model(db: fs.Client, model: str) -> int:
    """
    Get the number of jobs in the queue for the model.
    """
    return (
        db.collection(JOB_QUEUE_COLLECTION)
        .where(filter=JOBS_IN_QUEUE_FILTER)
        .where(filter=fs.FieldFilter("model", "==", model))
        .count()
        .get()[0][0]
        .value
    )


def iterate_queueing_jobs(db: fs.Client, model: str) -> Iterable[models.Job]:
    """
    Iterate over queueing jobs for the model.
    """
    docs = (
        db.collection(JOB_QUEUE_COLLECTION)
        .where(filter=JOBS_IN_QUEUE_FILTER)
        .where(filter=fs.FieldFilter("model", "==", model))
        .order_by("created_at", direction=fs.Query.ASCENDING)
        .limit(configs.GEMBATCH_MAX_REQUESTS_PER_BATCH.value)
        .stream()
    )
    for doc in docs:
        yield models.Job.from_dict(doc.to_dict())


def get_oldest_queueing_job_for_model(db: fs.Client, model: str) -> models.Job | None:
    """
    Get the oldest job in the queue for the model.
    """
    docs = (
        db.collection(JOB_QUEUE_COLLECTION)
        .where(filter=JOBS_IN_QUEUE_FILTER)
        .where(filter=fs.FieldFilter("model", "==", model))
        .order_by("created_at", direction=fs.Query.ASCENDING)
        .limit(1)
        .get()
    )
    if not docs:
        return None
    return models.Job.from_dict(docs[0].to_dict())


def iterate_pending_jobs(db: fs.Client, model: str) -> Iterable[models.Job]:
    """
    Iterate over pending jobs for the model.
    """
    docs = (
        db.collection(JOB_QUEUE_COLLECTION)
        .where(filter=fs.FieldFilter("status", "==", models.StatusEnum.PENDING))
        .where(filter=fs.FieldFilter("model", "==", model))
        .order_by("created_at", direction=fs.Query.ASCENDING)
        .limit(configs.GEMBATCH_MAX_REQUESTS_PER_BATCH.value)
        .stream()
    )
    for doc in docs:
        yield models.Job.from_dict(doc.to_dict())


def consume_gembatch_job(db: fs.Client, model: str):
    """Consume a gem batch job from the queue."""
    count = get_queueing_job_count_for_model(db, model)
    if count <= 0:
        logger.debug("No jobs to consume.")
        return
    elif count >= configs.GEMBATCH_MAX_REQUESTS_PER_BATCH.value:
        prepare_to_flush_jobs(db, model)
        return

    batch_interval = configs.GEMBATCH_BATCH_INTERVAL_SECONDS.value
    if count < configs.GEMBATCH_MAX_REQUESTS_PER_BATCH.value // 10:
        batch_interval *= 2  # double the interval if the request is low

    status = models.Status.from_db(db)
    last_submit_time = status.get_last_submit_time(model)
    if last_submit_time is None:
        last_submit_time = dt.datetime.now(tz=dt.timezone.utc)
        status.set_last_submit_time(model, last_submit_time)
        status.save(db)
    logger.debug("last submit time:", last_submit_time.isoformat())
    next_submit_time = last_submit_time + dt.timedelta(seconds=batch_interval)

    if last_submit_time + dt.timedelta(seconds=batch_interval) <= dt.datetime.now(
        tz=dt.timezone.utc
    ):
        oldest_job = get_oldest_queueing_job_for_model(db, model)
        if oldest_job and oldest_job.created_at > next_submit_time:
            logger.debug("Last submit time is too old, wait for the next run.")
            status.set_last_submit_time(model, dt.datetime.now(tz=dt.timezone.utc))
            status.save(db)
            utils.CloudRunQueue.open(
                "consumeGemBatchJob",
                delay_seconds=batch_interval,
            ).run(model=model)
            return
        prepare_to_flush_jobs(db, model)
        return
    elif (
        recorded_time := status.get_next_submit_time(model)
    ) is None or next_submit_time > recorded_time:
        logger.debug(
            f"want next submit time to be {next_submit_time.isoformat()},"
            f"but got {recorded_time.isoformat() if recorded_time else 'None'}"
        )
        status.set_next_submit_time(model, next_submit_time)
        status.save(db)
        delta = next_submit_time - dt.datetime.now(tz=dt.timezone.utc)
        delta_seconds = max(0, int(delta.total_seconds()))
        utils.CloudRunQueue.open(
            "consumeGemBatchJob",
            delay_seconds=delta_seconds + 1,
        ).run(model=model)
    else:
        logger.debug("No jobs to consume.")


def prepare_to_flush_jobs(db: fs.Client, model: str):
    """Mark jobs to be flushed."""
    for jobs in itertools.batched(iterate_queueing_jobs(db, model), 50):
        batch = db.batch()
        for job in jobs:
            job.status = models.StatusEnum.PENDING
            batch.update(
                db.collection(JOB_QUEUE_COLLECTION).document(job.uuid),
                job.asdict(),
            )
        batch.commit()
    status = models.Status.from_db(db)
    status.set_last_submit_time(model, dt.datetime.now(tz=dt.timezone.utc))
    status.save(db)
    q = utils.CloudRunQueue.open("flushGemBatchJobQueue")
    q.run(model=model)


@tasks_fn.on_task_dispatched(
    retry_config=options.RetryConfig(
        max_attempts=2, max_backoff_seconds=300, min_backoff_seconds=10
    ),
    rate_limits=options.RateLimits(max_concurrent_dispatches=1),
    memory=configs.GEMBATCH_LARGE_JOB_MEMORY.value,
    max_instances=1,
    concurrency=1,
    region=configs.GEMBATCH_REGION.value,
    timeout_sec=1800,
)
def flushGemBatchJobQueue(
    req: tasks_fn.CallableRequest,
):  # pylint: disable=[invalid-name]
    """Flush the gem batch job queue."""
    model = req.data["model"]
    db = firestore.client()
    flush_gembatch_job_queue(db, model)


def flush_gembatch_job_queue(db: fs.Client, model: str):
    """Flush the gem batch job queue."""
    uid = uuid.uuid4().hex
    batch_job = gemini.GeminiBatchJob(uid, model)
    for jobs in itertools.batched(iterate_pending_jobs(db, model), 50):
        queries: list[gemini.PredictionQuery] = []
        for job in jobs:
            request = job.get_request(db)
            if not request:
                continue
            queries.append(
                gemini.PredictionQuery(
                    request=request.load_as_dict(),
                    metadata=job.get_metadata(),
                    params=job.params,
                )
            )
        batch_job.write_queries(queries)
        batch = db.batch()
        for job in jobs:
            job.batch_job_id = batch_job.uuid
            job.status = models.StatusEnum.RUNNING
            job.retries += 1
            batch.update(
                db.collection(JOB_QUEUE_COLLECTION).document(job.uuid),
                job.asdict(),
            )
        batch.commit()
    batch_job.submit(db)
    status = models.Status.from_db(db)
    status.set_last_submit_time(model, dt.datetime.now(tz=dt.timezone.utc))
    status.save(db)
    logger.debug("Flushed job queue for model:", model)
    q = utils.CloudRunQueue.open(
        "consumeGemBatchJob",
        delay_seconds=configs.GEMBATCH_BATCH_INTERVAL_SECONDS.value,
    )
    q.run(model=model)


@tasks_fn.on_task_dispatched(
    retry_config=options.RetryConfig(
        max_attempts=2, max_backoff_seconds=300, min_backoff_seconds=10
    ),
    rate_limits=options.RateLimits(max_concurrent_dispatches=1),
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
    max_instances=1,
    concurrency=1,
    region=configs.GEMBATCH_REGION.value,
    timeout_sec=1800,
)
def runGemBatchJob(_: tasks_fn.CallableRequest):  # pylint: disable=[invalid-name]
    """
    Run and submit a gem batch job.
    """
    db = firestore.client()
    active_jobs = gemini.count_active_prediction_jobs()
    if active_jobs >= configs.GEMBATCH_GEMINI_BATCH_JOBS_QUOTA.value:
        logger.info("Too many active jobs. Skipping.")
        return
    active_gembatch = count_gembatch_running_batch_jobs(db)
    if active_gembatch >= configs.GEMBATCH_MAX_GEMINI_BATCH_JOBS.value:
        logger.info("Too many active gem batch jobs. Skipping.")
        return
    docs = (
        db.collection(configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value)
        .where(
            filter=fs.Or(
                [
                    fs.FieldFilter("status", "==", models.StatusEnum.NEW),
                    fs.FieldFilter("status", "==", models.StatusEnum.PENDING),
                ]
            )
        )
        .order_by("created_at", direction=fs.Query.ASCENDING)
        .limit(1)
        .get()
    )
    if not docs:
        logger.info("No batch jobs to run.")
        return
    job = gemini.GeminiBatchJob.from_doc(docs[0])
    job.run()


def count_gembatch_running_batch_jobs(db: fs.Client) -> int:
    """
    Count the number of running gem batch jobs.
    """
    return (
        db.collection(configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value)
        .where(filter=fs.FieldFilter("status", "==", models.StatusEnum.RUNNING))
        .count()
        .get()[0][0]
        .value
    )


@tasks_fn.on_task_dispatched(
    retry_config=options.RetryConfig(max_attempts=2, max_backoff_seconds=300),
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
    max_instances=min(50, configs.GEMBATCH_MAX_REQUESTS_PER_BATCH.value // 5),
    concurrency=5,
    region=configs.GEMBATCH_REGION.value,
    timeout_sec=1800,
)
def handleGemBatchRequestComplete(
    req: tasks_fn.CallableRequest,
):  # pylint: disable=[invalid-name]
    """Handle the completion of a gembatch request job."""
    job_id = req.data["jobId"]
    job = models.Job.from_db(firestore.client(), job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found.")
    if job.status != models.StatusEnum.COMPLETED:
        raise RuntimeError(f"Job {job_id} not completed.")
    meta = job.get_metadata()
    module = importlib.import_module(meta["handler_module"])
    handler: types.ResponseHandler = getattr(module, meta["handler_name"])
    if not callable(handler):
        raise ValueError(f"Handler {handler} is not callable.")
    db = firestore.client()
    response = job.get_response(db)
    if not response:
        raise ValueError(f"Response for job {job_id} not found.")
    handler(response.load_as_response(), **job.params)


@tasks_fn.on_task_dispatched(
    retry_config=options.RetryConfig(
        max_attempts=2, max_backoff_seconds=300, min_backoff_seconds=10
    ),
    rate_limits=options.RateLimits(max_concurrent_dispatches=1),
    memory=configs.GEMBATCH_SMALL_JOB_MEMORY.value,
    max_instances=1,
    concurrency=1,
    region=configs.GEMBATCH_REGION.value,
    timeout_sec=1800,
)
def checkRunningGemBatchJobStatus(
    req: tasks_fn.CallableRequest,
):  # pylint: disable=[invalid-name]
    """Check the status of a running gem batch prediction job."""
    logger.debug("Checking job status: ", req.data)
    job_id = req.data["jobId"]
    db = firestore.client()
    doc = (
        db.collection(configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value)
        .document(job_id)
        .get()
    )
    if not doc.exists:
        logger.warn(f"Document {job_id} not found")
        return

    db_job = models.Job.from_dict(doc.to_dict())
    if db_job.status != models.StatusEnum.RUNNING:
        logger.warn(f"Job {job_id} is not running, no need to check.")
        return

    batch_job = gemini.GeminiBatchJob.from_doc(doc)
    state = batch_job.poll_job_state()

    if state == models.StatusEnum.RUNNING:
        logger.debug(f"Job {job_id} is still running.")
    elif state == models.StatusEnum.FAILED:
        batch_job.mark_as_done(success=False)
        mark_all_jobs_in_batch_as_failed(db, job_id)
    elif state == models.StatusEnum.COMPLETED:
        batch_job.mark_as_done()
        on_success = utils.CloudRunQueue.open("runOnGemBatchJobSuccess")
        on_success.run(job_id=job_id)
    else:
        logger.warn(f"Unknown job state: {state}")


def mark_all_jobs_in_batch_as_failed(db: fs.Client, batch_job_id: str):
    """Mark all jobs in a batch as failed."""
    docs = (
        db.collection(configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value)
        .where(filter=fs.FieldFilter("batch_job_id", "==", batch_job_id))
        .stream()
    )
    doc: fs.DocumentSnapshot
    for _docs in itertools.batched(docs, 50):
        batch = db.batch()
        for doc in _docs:
            job = models.Job.from_dict(doc.to_dict())
            # TODO: consider updating job creation time
            job.status = models.StatusEnum.FAILED
            batch.update(doc.reference, job.asdict())
        batch.commit()


@tasks_fn.on_task_dispatched(
    retry_config=options.RetryConfig(
        max_attempts=2, max_backoff_seconds=300, min_backoff_seconds=10
    ),
    rate_limits=options.RateLimits(max_concurrent_dispatches=10),
    memory=configs.GEMBATCH_LARGE_JOB_MEMORY.value,
    max_instances=10,
    concurrency=1,
    region=configs.GEMBATCH_REGION.value,
    timeout_sec=1800,
)
def runOnGemBatchJobSuccess(
    req: tasks_fn.CallableRequest,
):  # pylint: disable=[invalid-name]
    """Handle the completion of a gem batch prediction job."""
    job_id = req.data["jobId"]
    db = firestore.client()
    doc = (
        db.collection(configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value)
        .document(job_id)
        .get()
    )
    if not doc.exists:
        logger.warn(f"Document {job_id} not found")
        return

    batch_job = gemini.GeminiBatchJob.from_doc(doc)
    visited = set()
    for rows in itertools.batched(batch_job.list_results(), 50):
        batch = db.batch()
        for row in rows:
            job = models.Job.from_db(db, row.metadata["uuid"])
            if job is None:
                logger.warn(f"Job {row.metadata['uuid']} not found.")
                continue
            job.save_response(db, row.response)
            job.status = models.StatusEnum.COMPLETED
            batch.update(
                db.collection(JOB_QUEUE_COLLECTION).document(job.uuid),
                job.asdict(),
            )
            visited.add(job.uuid)
        batch.commit()

    # Trigger post-job completion tasks
    queue = utils.CloudRunQueue.open("handleGemBatchRequestComplete")
    for job_id in visited:
        queue.run(job_id=job_id)

    _clean_up_failed_jobs(db, batch_job.uuid, visited)


def _clean_up_failed_jobs(db: fs.Client, batch_job_id: str, success_jobs: set[str]):
    """Clean up failed jobs in a batch."""
    docs = (
        db.collection(JOB_QUEUE_COLLECTION)
        .where(filter=fs.FieldFilter("batch_job_id", "==", batch_job_id))
        .stream()
    )
    doc: fs.DocumentSnapshot
    for doc in docs:
        job = models.Job.from_dict(doc.to_dict())
        if job.uuid in success_jobs:
            continue
        job.status = models.StatusEnum.FAILED
        doc.reference.update(job.asdict())

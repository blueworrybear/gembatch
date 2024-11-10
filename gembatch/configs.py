"""Define firebase environment variables."""

from firebase_functions import params  # type: ignore
from firebase_functions import options  # type: ignore


GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION = params.StringParam(
    name="GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION",
    default="gembatch_queue",
    description="The collection name for the gemini job queue in firestore.",
)

GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION = params.StringParam(
    name="GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION",
    default="gembatch_batch_queue",
    description="The collection name for the gemini batch job queue in firestore.",
)

GEMBATCH_FIRESTORE_STATUS_COLLECTION = params.StringParam(
    name="GEMBATCH_FIRESTORE_STATUS_COLLECTION",
    default="gembatch_status",
    description="The collection name for the gembatch global status in firestore.",
)

GEMBATCH_FIRESTORE_REQUESTS_COLLECTION = params.StringParam(
    name="GEMBATCH_FIRESTORE_REQUESTS_COLLECTION",
    default="gembatch_requests",
    description="The collection name for the gemini requests in firestore.",
)

GEMBATCH_MAX_GEMINI_BATCH_JOBS = params.IntParam(
    name="GEMBATCH_MAX_GEMINI_BATCH_JOBS",
    default=1,
    description="The maximum number of gemini batch jobs can be run at the same time.",
)

GEMBATCH_GEMINI_BATCH_JOBS_QUOTA = params.IntParam(
    name="GEMBATCH_GEMINI_BATCH_JOBS_QUOTA",
    default=1,
    description="The quota for gemini batch jobs.",
)

GEMBATCH_MAX_REQUESTS_PER_BATCH = params.IntParam(
    name="GEMBATCH_MAX_REQUESTS_PER_BATCH",
    default=200,
    description="The maximum number of requests per batch job.",
)

GEMBATCH_BATCH_INTERVAL_SECONDS = params.IntParam(
    name="GEMBATCH_BATCH_INTERVAL_SECONDS",
    default=1800,  # 30 minutes
    description="The interval between batch jobs in seconds.",
)

GEMBATCH_REGION = params.StringParam(
    name="GEMBATCH_REGION",
    default="us-central1",
    description="The region where the cloud functions are deployed.",
)

GEMBATCH_SMALL_JOB_MEMORY = params.IntParam(
    name="GEMBATCH_SMALL_JOB_MEMORY",
    default=options.MemoryOption.MB_512,
    description="The memory allocated for small jobs.",
)

GEMBATCH_LARGE_JOB_MEMORY = params.IntParam(
    name="GEMBATCH_LARGE_JOB_MEMORY",
    default=options.MemoryOption.GB_4,
    description="The memory allocated for large jobs.",
)

GEMBATCH_MAX_RETRIES = params.IntParam(
    name="GEMBATCH_MAX_RETRIES",
    default=3,
    description="The maximum number of retries for a job.",
)

GEMBATCH_CLOUD_STORAGE_BUCKET = params.StringParam(
    name="GEMBATCH_CLOUD_STORAGE_BUCKET",
    default="gembatch",
    description="The name of the cloud storage bucket.",
)

GEMBATCH_PREDICTION_DATASET = params.StringParam(
    name="GEMBATCH_PREDICTION_DATASET",
    default="gembatch_prediction",
    description="The name of the bigquery dataset for predictions.",
)

GEMBATCH_BATCH_JOB_DISPLAY_NAME = params.StringParam(
    name="GEMBATCH_BATCH_JOB_DISPLAY_NAME",
    default="gembatch-prediction",
    description="The display name for the batch job.",
)

GEMBATCH_HEALTH_CHECK_POLL_INTERVAL = params.IntParam(
    name="GEMBATCH_HEALTH_CHECK_POLL_INTERVAL",
    default=15,
    description="The interval between health checks in minutes.",
)

GEMBATCH_BATCH_JOB_POST_PROCESSING_TIMEOUT = params.IntParam(
    name="GEMBATCH_BATCH_JOB_POST_PROCESSING_TIMEOUT",
    default=7200,  # 2 hours
    description="The timeout for post processing in seconds.",
)

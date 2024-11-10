"""Module to handle Eventarc events."""

import functions_framework
from cloudevents.http import event as cloud_event  # type: ignore
from firebase_functions import logger  # type: ignore

from gembatch import gemini, utils


@functions_framework.cloud_event
def on_receive_gembatch_bigquery_batch_updates(event: cloud_event.CloudEvent):
    """Handle the completion of a batch prediction job."""

    resource: str | None = event.get("resourcename")
    if not resource:
        raise ValueError(f"Need bigquery event, got {event}.")
    tokens = resource.strip("/").split("/")
    attributes = {k: v for k, v in zip(tokens[0::2], tokens[1::2])}
    table = attributes["tables"]
    logger.info(f"Received bigquery event for {table}")
    if not table.startswith(f"{gemini.BATCH_DISPLAY_NAME}-destination"):
        logger.info(f"Skipping event for {table}")
        return

    batch_job = gemini.GeminiBatchJob.from_bq_event(event)
    check_status = utils.CloudRunQueue.open("checkRunningGemBatchJobStatus")
    check_status.run(job_id=batch_job.uuid)

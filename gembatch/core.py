"""Define core methods for the gem-batch project."""

import datetime as dt
import inspect
import uuid

from firebase_admin import firestore  # type: ignore
from vertexai import generative_models  # type: ignore

from gembatch import models, types, configs


def no_action(_: generative_models.GenerationResponse):
    """Do nothing with the response."""


def submit(
    request: dict,
    model: str,
    handler: types.ResponseHandler,
    params: dict | None = None,
) -> str:
    """Enqueue a new generation job.

    Args:
        request: The Gemini generation request in dictionary form.
        model: The model to be used for generation.
        handler: The handler for the generation job.
        params: The parameters for the handler.

    Returns:
        The UUID of the job.

    Raises:
        ValueError: If the handler does not belong to a module or is a lambda function.

    Example:
        >>> submit(
        ...     {"contents": [{"role": "user", "parts": [{"text": "Hi! How are you?"}]}]},
        ...     "publishers/google/models/gemini-1.5-flash-002",
        ...     echo_action,
        ... )
    """
    m = inspect.getmodule(handler)
    if m is None:
        raise ValueError(f"Handler {handler} doesn't belong to a module.")
    if handler.__name__ == "<lambda>":
        raise ValueError("Lambda functions are not supported.")
    uid = uuid.uuid4().hex
    meta: types.JobMetadata = {
        "uuid": uid,
        "handler_module": m.__name__,
        "handler_name": handler.__name__,
    }
    job = models.Job(
        uuid=uid,
        model=model,
        params=params or {},
        metadata=dict(meta),
        created_at=dt.datetime.now(tz=dt.timezone.utc),
    )

    db = firestore.client()
    doc = db.collection(configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value).document(
        job.uuid
    )
    doc.set(job.asdict(), merge=True)
    job.save_request(db, request)
    return job.uuid

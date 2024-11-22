"""Define the models representing data in the firestore database."""

import abc
import dataclasses
import datetime as dt
import enum
from typing import Type, TypeVar, Optional
import json
from google.cloud import firestore as fs  # type: ignore
from vertexai import generative_models  # type: ignore
from gembatch import types, utils, configs

K = TypeVar("K", bound="BaseDocument")

COLLECTION_REQUESTS = configs.GEMBATCH_FIRESTORE_REQUESTS_COLLECTION.value
DOCUMENT_REQUEST = "request"
DOCUMENT_RESPONSE = "response"
FIRESTORE_SIZE_LIMIT = 1048576 - 500  # 1MB - 500 bytes (buffer)


class StatusEnum(str, enum.Enum):
    """Enum representing the status of a gem batch."""

    NEW = "new"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DateTimeField:
    """
    A field that stores a datetime.
    """

    def __init__(self, *, default: dt.datetime | None = None):
        if default and default.tzinfo is None:
            default = default.replace(tzinfo=dt.timezone.utc)
        self._default = (
            default
            if default is not None
            else dt.datetime(year=1, month=1, day=1, tzinfo=dt.timezone.utc)
        )

    def __set_name__(self, _: object, name: str) -> None:
        self._name = "_" + name  # pylint: disable=attribute-defined-outside-init
        self._default_name = name  # pylint: disable=attribute-defined-outside-init

    def __get__(self, instance: object, _: type) -> dt.datetime:
        if instance is None:
            return self._default
        return getattr(instance, self._name)

    def __set__(self, instance: object, value: str | dt.datetime | None) -> None:
        if value is None:
            setattr(instance, self._name, dt.datetime.min)
        elif isinstance(value, type(self)):
            setattr(instance, self._name, value._default)
        elif isinstance(value, dt.datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=dt.timezone.utc)
            setattr(instance, self._name, value.astimezone(dt.timezone.utc))
        elif isinstance(value, str):
            setattr(
                instance,
                self._name,
                dt.datetime.strptime(value, "%Y/%m/%d %H:%M").replace(
                    tzinfo=dt.timezone.utc
                ),
            )
        else:
            raise TypeError(
                f"{self._default_name} must be a dt.datetime or str, not {value}"
            )


@dataclasses.dataclass
class BaseDocument(abc.ABC):
    """Base class for firestore documents."""

    @classmethod
    def from_dict(cls: Type[K], data: dict | None) -> K:
        """
        Creates a new instance from a dictionary.
        """
        if data is None:
            raise ValueError("data must be a dict.")
        fields = {field.name for field in dataclasses.fields(cls)}
        _data = {utils.camel_to_snake(k): v for k, v in data.items()}
        return cls(**{k: v for k, v in _data.items() if k in fields})

    def asdict(self) -> dict:
        """
        Returns a dictionary representation of the object.
        """
        return dataclasses.asdict(self)


@dataclasses.dataclass
class Status(BaseDocument):
    """Represents the status of a gem batch."""

    last_batch_submit_time: dict = dataclasses.field(default_factory=dict)
    next_batch_submit_time: dict = dataclasses.field(default_factory=dict)

    def get_last_submit_time(self, model: str) -> dt.datetime | None:
        """
        Returns the last submit time for the model.
        """
        if model not in self.last_batch_submit_time:
            return None
        ts = self.last_batch_submit_time.get(
            model, dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        )
        if isinstance(ts, str):
            return dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc)
        return ts

    def set_last_submit_time(self, model: str, ts: dt.datetime):
        """
        Set the last submit time for the model.
        """
        self.last_batch_submit_time[model] = ts

    def get_next_submit_time(self, model: str) -> dt.datetime | None:
        """
        Returns the next submit time for the model.
        """
        if model not in self.next_batch_submit_time:
            return None
        ts = self.next_batch_submit_time.get(
            model, dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        )
        if isinstance(ts, str):
            return dt.datetime.fromisoformat(ts).replace(tzinfo=dt.timezone.utc)
        return ts

    def set_next_submit_time(self, model: str, ts: dt.datetime):
        """
        Set the next submit time for the model.
        """
        self.next_batch_submit_time[model] = ts

    @classmethod
    def from_db(cls, db: fs.Client) -> "Status":
        """Get the status from the database."""
        ref = db.collection(
            configs.GEMBATCH_FIRESTORE_STATUS_COLLECTION.value
        ).document("global")
        doc = ref.get()
        if not doc.exists:
            return cls()
        return cls.from_dict(doc.to_dict())

    def save(self, db: fs.Client):
        """Save the status to the database."""
        ref = db.collection(
            configs.GEMBATCH_FIRESTORE_STATUS_COLLECTION.value
        ).document("global")
        ref.set(self.asdict(), merge=True)


@dataclasses.dataclass
class Job(BaseDocument):
    """Represents a gem batch job for single GenAI request."""

    uuid: str
    model: str  # Gemini model name
    batch_job_id: str | None = None
    status: str = StatusEnum.NEW
    retries: int = 0
    params: dict = dataclasses.field(default_factory=dict)
    metadata: dict = dataclasses.field(default_factory=dict)
    created_at: DateTimeField = DateTimeField()
    ttl: DateTimeField = DateTimeField()

    def __post_init__(self):
        self.ttl = self.created_at + dt.timedelta(days=5)

    @classmethod
    def from_db(cls, db: fs.Client, uid: str) -> Optional["Job"]:
        """
        Get a job from the database.
        """
        ref = db.collection(
            configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value
        ).document(uid)
        doc = ref.get()
        if not doc.exists:
            return None
        return cls.from_dict(doc.to_dict())

    def get_metadata(self) -> types.JobMetadata:
        """
        Returns the metadata for the job.
        """
        return types.JobMetadata(**self.metadata)

    def _get_doc(self, db: fs.Client) -> fs.DocumentSnapshot | None:
        ref = db.collection(
            configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value
        ).document(self.uuid)
        doc = ref.get()
        if not doc.exists:
            return None
        return doc

    def get_request(self, db: fs.Client) -> Optional["Request"]:
        """
        Get the request for the job.
        """
        doc = self._get_doc(db)
        if doc is None:
            return None
        req_ref = doc.reference.collection(COLLECTION_REQUESTS).document("request")
        req_doc = req_ref.get()
        if not req_doc.exists:
            return None
        return Request.from_dict(req_doc.to_dict())

    def save_request(self, db: fs.Client, request: dict):
        """
        Save the request for the job.
        """
        doc = self._get_doc(db)
        if doc is None:
            raise ValueError(f"Job {self.uuid} not found.")
        req_ref = doc.reference.collection(COLLECTION_REQUESTS).document(
            DOCUMENT_REQUEST
        )
        # TODO: check size of request
        req_ref.set(
            Request(request=json.dumps(request, indent=2, ensure_ascii=False)).asdict()
        )

    def get_response(self, db: fs.Client) -> Optional["Response"]:
        """
        Get the response for the job.
        """
        doc = self._get_doc(db)
        if doc is None:
            return None
        req_ref = doc.reference.collection(COLLECTION_REQUESTS).document(
            DOCUMENT_RESPONSE
        )
        req_doc = req_ref.get()
        if not req_doc.exists:
            return None
        return Response.from_dict(req_doc.to_dict())

    def save_response(
        self, db: fs.Client, response: str | generative_models.GenerationResponse
    ):
        """
        Save the response for the job.
        """
        doc = self._get_doc(db)
        if doc is None:
            raise ValueError(f"Job {self.uuid} not found.")
        req_ref = doc.reference.collection(COLLECTION_REQUESTS).document(
            DOCUMENT_RESPONSE
        )
        if isinstance(response, generative_models.GenerationResponse):
            response = json.dumps(response.to_dict(), indent=2, ensure_ascii=False)
        req_ref.set(Response(response=response).asdict())


@dataclasses.dataclass
class Request(BaseDocument):
    """Represents a request for a gem batch job."""

    request: str
    blob: str | None = None
    ttl: DateTimeField = DateTimeField()

    def __post_init__(self):
        self.ttl = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)

    def load_as_dict(self) -> dict:
        """
        Load the request.
        """
        return json.loads(self.request)


@dataclasses.dataclass
class Response(BaseDocument):
    """Represents a response for a gem batch job."""

    response: str
    blob: str | None = None
    ttl: DateTimeField = DateTimeField()

    def __post_init__(self):
        self.ttl = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)

    def load_as_response(self) -> generative_models.GenerationResponse:
        """
        Load the response.
        """
        return generative_models.GenerationResponse.from_dict(json.loads(self.response))


@dataclasses.dataclass
class BatchJob(BaseDocument):
    """Represents a batch (prediction) job."""

    uuid: str
    model: str  # Gemini mode name
    bigquery_source: str
    bigquery_destination: str
    name: str = ""
    status: str = StatusEnum.NEW
    created_at: DateTimeField = DateTimeField()
    ttl: DateTimeField = DateTimeField()

    def __post_init__(self):
        self.ttl = self.created_at + dt.timedelta(days=5)

"""Module for Gemini generation batch processing."""

import dataclasses
import datetime as dt
import itertools
import json
import uuid
from typing import Any, Iterable, Sequence

import firebase_admin  # type: ignore
import requests
import vertexai  # type: ignore
from cloudevents.http import event as cloud_event
from firebase_admin import firestore, storage  # type: ignore
from google.cloud import bigquery  # type: ignore
from google.cloud import aiplatform
from google.cloud import firestore as fs  # type: ignore
from vertexai import generative_models

from gembatch import configs, models, types, utils

BATCH_DISPLAY_NAME = configs.GEMBATCH_BATCH_JOB_DISPLAY_NAME.value


@dataclasses.dataclass
class PredictionQuery:
    """A query for batch prediction."""

    request: dict
    metadata: types.JobMetadata
    params: dict

    def asdict(self) -> dict[str, Any]:
        """Convert the query to a dictionary."""
        return {
            "request": self.request,
            "metadata": dict(self.metadata),
            "params": self.params,
        }


class GeminiBatchJob:
    """A batch job for Gemini prediction."""

    @utils.simple_cached_property
    def source_table(self) -> str:
        """Create a source table for the batch job."""
        table_id = f"{BATCH_DISPLAY_NAME}-source-{self._uuid}"
        dataset_ref = self._client.dataset(self.dataset)
        table_ref = dataset_ref.table(table_id)
        table = bigquery.Table(table_ref, schema=self.schema)
        table = self._client.create_table(table, exists_ok=True)
        return table.full_table_id.replace(":", ".")

    @property
    def source_table_url(self) -> str:
        """Return the source table URL."""
        return f"bq://{self.source_table}"

    @property
    def destination_table(self) -> str:
        """Return a destination table for the batch job."""
        return f"{self.project}.{self.dataset}.{BATCH_DISPLAY_NAME}-destination-{self._uuid}"

    @property
    def destination_table_url(self) -> str:
        """Return the destination table URL."""
        return f"bq://{self.destination_table}"

    @property
    def project(self) -> str:
        """Return the project ID."""
        return self._project_id

    @property
    def dataset(self) -> str:
        """Return the BigQuery dataset ID."""
        return configs.GEMBATCH_PREDICTION_DATASET.value

    @property
    def schema(self) -> list[bigquery.SchemaField]:
        """Return the BigQuery schema."""
        return [
            bigquery.SchemaField("request", "JSON", mode="REQUIRED"),
            bigquery.SchemaField("metadata", "JSON", mode="REQUIRED"),
            bigquery.SchemaField("params", "JSON", mode="REQUIRED"),
        ]

    @property
    def model(self) -> str:
        """Return the Gemini model name."""
        return self._model

    @property
    def uuid(self) -> str:
        """Return the UUID of the batch job."""
        return self._uuid

    @property
    def bq_load_config(self) -> bigquery.LoadJobConfig:
        """Return the BigQuery load job configuration."""
        return bigquery.LoadJobConfig(
            schema=self.schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )

    @property
    def display_name(self) -> str:
        """Return the display name of the batch job."""
        return f"{BATCH_DISPLAY_NAME}-{self._uuid}"

    @property
    def prediction_job_name(self) -> str:
        return self._prediction_job_name

    @property
    def created_at(self) -> dt.datetime:
        """Return the creation time of the batch job."""
        return self._created_at

    def __init__(
        self,
        uid: str,
        model: str,
        created_at: dt.datetime | None = None,
        prediction_job_name: str = "",
    ):
        app: firebase_admin.App = firebase_admin.get_app()
        vertexai.init(project=app.project_id, location=configs.GEMBATCH_REGION.value)
        self._client = bigquery.Client(project=app.project_id)
        self._app = app
        self._project_id = app.project_id
        self._db = firestore.client()
        self._bucket = storage.bucket(configs.GEMBATCH_CLOUD_STORAGE_BUCKET.value)
        self._queries = 0
        self._uuid = uid
        self._model = model
        self._created_at = created_at or dt.datetime.now(tz=dt.timezone.utc)
        self._prediction_job_name = prediction_job_name

    @classmethod
    def from_bq_event(cls, event: cloud_event.CloudEvent) -> "GeminiBatchJob":
        """Create a new instance from a BigQuery event."""
        resource: str | None = event.get("resourcename")
        if not resource:
            raise ValueError(f"Need bigquery event, got {event}.")
        tokens = resource.strip("/").split("/")
        attributes = {k: v for k, v in zip(tokens[0::2], tokens[1::2])}
        project = attributes["projects"]
        dateset = attributes["datasets"]
        table = attributes["tables"]
        uri = f"bq://{project}.{dateset}.{table}"
        db = firestore.client()
        query = (
            db.collection(configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value)
            .where(filter=fs.FieldFilter("bigquery_destination", "==", uri))
            .limit(1)
        )
        results = query.get()
        if not results:
            raise ValueError(f"Can't find job write to {uri}")
        return cls.from_doc(results[0])

    @classmethod
    def from_doc(cls, doc: fs.DocumentSnapshot):
        """Create a new instance from a firestore document."""
        job = models.BatchJob.from_dict(doc.to_dict())
        return cls(job.uuid, job.model, job.created_at, prediction_job_name=job.name)

    def write_queries(self, queries: Sequence[PredictionQuery]):
        """Write queries to the source table."""
        self._queries += len(queries)
        rows_to_inserts = [q.asdict() for q in queries]
        if self.source_table is None:
            raise ValueError("Source table is not created.")
        for batch in itertools.batched(rows_to_inserts, 50):
            jsonl = "\n".join(json.dumps(r) for r in batch)
            uid = uuid.uuid4().hex
            blob = self._bucket.blob(f"predictions/{self._uuid}/{uid}")
            blob.upload_from_string(jsonl, timeout=600)
            del jsonl
            uri = f"gs://{self._bucket.name}/{blob.name}"
            load_job = self._client.load_table_from_uri(
                uri,
                self.source_table,
                location=configs.GEMBATCH_REGION.value,
                job_config=self.bq_load_config,
                timeout=600,
            )
            load_job.result(timeout=600)
        while rows_to_inserts:
            del rows_to_inserts[0]

    def submit(self, check=True) -> models.BatchJob:
        """Submit batch job
        Args:
            check: If True, check if the job has any queries to run.

        Returns:
            The BatchPredictionJob object.
        """
        if check and not self._queries:
            raise RuntimeError("No queries to run.")
        job = models.BatchJob(
            uuid=self._uuid,
            model=self._model,
            status=models.StatusEnum.NEW,
            bigquery_source=self.source_table_url,
            bigquery_destination=self.destination_table_url,
            created_at=dt.datetime.now(tz=dt.timezone.utc),
        )
        doc_ref = self._db.collection(
            configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value
        ).document(self._uuid)
        doc_ref.set(job.asdict(), merge=True)
        return job

    def run(self) -> models.BatchJob:
        """Run the batch job."""
        token = self._app.credential.get_access_token().access_token
        region = configs.GEMBATCH_REGION.value
        api = f"https://{region}-aiplatform.googleapis.com/v1"
        response = requests.post(
            f"{api}/projects/{self.project}/locations/{region}/batchPredictionJobs",
            json={
                "displayName": self.display_name,
                "model": self.model,
                "inputConfig": {
                    "instancesFormat": "bigquery",
                    "bigquerySource": {"inputUri": self.source_table_url},
                },
                "outputConfig": {
                    "predictionsFormat": "bigquery",
                    "bigqueryDestination": {"outputUri": self.destination_table_url},
                },
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        if not response.ok:
            raise RuntimeError(response.text)
        data: dict[str, Any] = response.json()
        name = data.get("name", None)
        if not name:
            raise RuntimeError("fail to create batch prediction job.")
        job = models.BatchJob(
            uuid=self._uuid,
            name=name,
            model=self.model,
            status=models.StatusEnum.RUNNING,
            bigquery_source=self.source_table_url,
            bigquery_destination=self.destination_table_url,
        )
        self._prediction_job_name = name
        doc_ref = self._db.collection(
            configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value
        ).document(self._uuid)
        doc_ref.set(dataclasses.asdict(job), merge=True)
        return job

    def mark_as_done(self, success=True):
        """Mark the job as done."""
        doc_ref = self._db.collection(
            configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value
        ).document(self._uuid)
        doc = doc_ref.get()
        if not doc.exists:
            raise RuntimeError(f"Job {self._uuid} doesn't exist.")
        job = models.BatchJob.from_dict(doc.to_dict())
        job.status = (
            models.StatusEnum.COMPLETED if success else models.StatusEnum.FAILED
        )
        doc_ref.set(dataclasses.asdict(job), merge=True)

    def list_results(
        self, skip_invalid_row: bool = True
    ) -> Iterable[types.PredictionResult | None]:
        """List the results of the batch job."""
        page_token = ""
        fields = [s for s in self.schema if s.name != "request"] + [
            bigquery.SchemaField("status", "STRING"),
            bigquery.SchemaField("response", "JSON"),
        ]
        while page_token is not None:
            row_iter = self._client.list_rows(
                self.destination_table,
                max_results=50,
                page_token=page_token,
                selected_fields=fields,
                timeout=300,
            )
            for row in row_iter:
                v = self._parse_row(row)
                if v is None and not skip_invalid_row:
                    raise ValueError(f"Invalid row {row}")
                elif v is not None:
                    yield self._parse_row(row)
            page_token = row_iter.next_page_token

    def poll_job_state(self) -> models.StatusEnum:
        token = self._app.credential.get_access_token().access_token
        res = requests.get(
            f"https://us-central1-aiplatform.googleapis.com/v1/{self.prediction_job_name}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        res.raise_for_status()
        data = res.json()
        state = data.get("state", None)
        if state in ["JOB_STATE_SUCCEEDED"]:
            return models.StatusEnum.COMPLETED
        elif state in [
            "JOB_STATE_QUEUED",
            "JOB_STATE_PENDING",
            "JOB_STATE_RUNNING",
            "JOB_STATE_CANCELLING",
            "JOB_STATE_UPDATING",
        ]:
            return models.StatusEnum.RUNNING
        else:
            return models.StatusEnum.FAILED

    def _parse_row(self, row: bigquery.Row) -> types.PredictionResult | None:
        response = row.get("response", None)
        metadata = row.get("metadata", None)
        params = row.get("params", None)
        if response is None or metadata is None or params is None:
            return None
        return types.PredictionResult(
            response=generative_models.GenerationResponse.from_dict(response),
            metadata=types.JobMetadata(**metadata),
            params=params,
        )


def count_active_prediction_jobs() -> int:
    """Count the number of active prediction jobs."""
    states = [
        "JOB_STATE_PENDING",
        "JOB_STATE_RUNNING",
        "JOB_STATE_QUEUED",
        "JOB_STATE_CANCELLING",
        "JOB_STATE_UPDATING",
    ]
    query = " OR ".join(f"state = {s}" for s in states)
    return len(aiplatform.BatchPredictionJob.list(filter=query))

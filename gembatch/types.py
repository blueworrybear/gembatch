"""Type definitions for the gembatch package."""

from typing import Callable, Concatenate, NamedTuple, ParamSpec, TypeAlias, TypedDict

from vertexai import generative_models  # type: ignore

P = ParamSpec("P")

ResponseHandler: TypeAlias = Callable[
    Concatenate[generative_models.GenerationResponse, P], None
]


class JobMetadata(TypedDict, total=False):
    """Metadata for a job."""

    uuid: str
    handler_module: str
    handler_name: str


class PredictionResult(NamedTuple):
    """The result of a prediction."""

    response: generative_models.GenerationResponse
    metadata: JobMetadata
    params: dict

"""Define common utilities."""

import functools
import os
import re
import time
from typing import Callable, Generic, TypeVar

import firebase_admin  # type: ignore
import google.auth  # type: ignore
import google.auth.transport.requests  # type: ignore
import requests  # type: ignore
from firebase_admin import functions  # type: ignore
from firebase_functions import logger  # type: ignore
from google.auth import credentials

from gembatch import configs

T = TypeVar("T")


def simple_retry(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        for _ in range(5):
            try:
                return func(*args, **kwargs)
            except Exception:  # pylint: disable=broad-except
                time.sleep(1)

    return wrapper


def camel_to_snake(name: str) -> str:
    """
    Converts a camel case string to snake case.
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def snake_to_camel(snake_str):
    """Converts a snake_case string to camelCase.

    Args:
        snake_str (str): The input string in snake_case format.

    Returns:
        str: The converted string in camelCase format.
    """
    components = snake_str.split("_")
    # Capitalize the first letter of each component except the first one
    # with the 'title' method and join them together.
    return components[0] + "".join(x.title() for x in components[1:])


def is_using_emulators():
    """Check if we're using firebase emulators."""
    host = os.environ.get("FIREBASE_EMULATOR_HUB")
    return host is not None and host != ""


def is_background_trigger_enabled():
    """Check if background triggers are enabled."""
    return os.environ.get("FIREBASE_BACKGROUND_TRIGGER_ENABLED", "").lower() in (
        "true",
        "1",
        "",
    )


@simple_retry
def get_function_url(name: str, location: str = configs.GEMBATCH_REGION.value) -> str:
    """Get the URL of a given v2 cloud function.

    Params:
        name: the function's name
        location: the function's location

    Returns: The URL of the function
    """
    if is_using_emulators():
        host = os.environ.get("FUNCTIONS_EMULATOR_HOST")
        project = os.environ.get("GCLOUD_PROJECT", "")
        return f"http://{host}/{project}/{location}/{name}"
    cred, project_id = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    authed_session = google.auth.transport.requests.AuthorizedSession(cred)
    url = (
        "https://cloudfunctions.googleapis.com/v2beta/"
        + f"projects/{project_id}/locations/{location}/functions/{name}"
    )
    response = authed_session.get(url)
    data = response.json()
    function_url = data["serviceConfig"]["uri"]
    return function_url


def refresh_credentials(func):
    """
    Refresh the credentials of the app.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        req = google.auth.transport.requests.Request()
        app: firebase_admin.App = firebase_admin.get_app()
        cred: credentials.Credentials = app.credential.get_credential()
        cred.refresh(req)
        return func(*args, **kwargs)

    return wrapper


class simple_cached_property(Generic[T]):
    """Decorator for class property to cache its value.
    Only not None value will be cached. The cached value will be kept in the instance.
    """

    def __init__(self, func: Callable[..., T]):
        self._func = func
        self._name: str | None = None

    def __set_name__(self, _, name: str):
        if self._name is None:
            self._name = name
        elif self._name != name:
            raise TypeError("Can't modify the property name after initialization")

    def __get__(self, instance, _) -> T | None:
        if instance is None:
            return None
        elif self._name is None:
            raise TypeError("Property not set")
        cached_value = getattr(instance, "_cached_" + self._name, None)
        if cached_value is not None:
            return cached_value
        value = self._func(instance)
        if value is not None:
            setattr(instance, "_cached_" + self._name, value)
        return value


class CloudRunQueue:
    """Cloud Run Queue"""

    def __init__(
        self,
        function_name: str,
        region: str = configs.GEMBATCH_REGION.value,
        delay_seconds: int = 0,
    ):
        self._function_name = function_name
        self._queue = functions.task_queue(
            f"locations/{region}/functions/{function_name}"
        )
        self._target = get_function_url(function_name, region)
        self._option = functions.TaskOptions(
            dispatch_deadline_seconds=1800,
            uri=self._target,
            schedule_delay_seconds=delay_seconds,
        )

    @classmethod
    def open(
        cls,
        function_name: str,
        region: str = configs.GEMBATCH_REGION.value,
        delay_seconds: int = 0,
    ):
        """Open a queue"""
        return cls(function_name, region=region, delay_seconds=delay_seconds)

    @refresh_credentials
    def run(self, **kwargs):
        """Run the task"""
        data = {snake_to_camel(k): v for k, v in kwargs.items()}
        if not is_using_emulators():
            task_id = self._queue.enqueue({"data": data}, self._option)
            logger.debug(f"task_id({self._target}): {task_id}")
            return
        if not is_background_trigger_enabled():
            logger.debug(f"{self._function_name} isn't forwarded.")
            return
        res = requests.post(
            self._target,
            json={"data": data},
            headers={"content-type": "application/json"},
            timeout=120,
        )
        res.raise_for_status()

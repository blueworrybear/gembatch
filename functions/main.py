# Welcome to Cloud Functions for Firebase for Python!
# To get started, simply uncomment the below code or create your own.
# Deploy with `firebase deploy`

from firebase_functions import https_fn, logger
from firebase_admin import initialize_app


from gembatch import *
import gembatch
from vertexai import generative_models

initialize_app()


def echo_action(response: generative_models.GenerationResponse):
    logger.debug(response.to_dict())
    print("Echo action.")


@https_fn.on_request()
def on_request_example(req: https_fn.Request) -> https_fn.Response:
    gembatch.submit(
        {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": "Hi! How are you?"}],
                }
            ],
        },
        "publishers/google/models/gemini-1.5-flash-002",
        echo_action,
    )
    return https_fn.Response("Hello world!")

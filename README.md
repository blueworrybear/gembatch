# gembatch

A Python library simplifies building language chain applications with Gemini, leveraging batch mode for cost-effective prompt processing.

## Introduction

Prompt chaining is a powerful technique for tackling complex tasks by linking multiple prompts together. Numerous libraries like Langchain offer convenient features for building applications with this approach. However, one crucial aspect often overlooked is cost efficiency.
Many AI service providers offer batch processing modes with significant discounts (often around 50%) in exchange for longer turnaround times. While enticing, leveraging these batch discounts within a prompt chaining workflow can be challenging. Instead of executing API calls sequentially, developers must manage intricate processes:

- Batching requests: Accumulating prompts into batches.
- Asynchronous handling: Polling and waiting for batch job completion.
- Result processing: Extracting and mapping results to the correct chain segment.

This complexity is compounded by considerations like rate limits, error handling, and potential retries. Implementing such a system often leads to convoluted code, hindering readability and maintainability.
This is where GemBatch shines. GemBatch is a framework designed to seamlessly integrate batch processing into prompt chaining workflows without sacrificing simplicity. It allows developers to define their prompt chains sequentially, just as they would with traditional approaches, while automatically optimizing execution using batch APIs behind the scenes. This abstraction simplifies development, improves code clarity, and unlocks significant cost savings.

## Requirements

To use the GemBatch library, ensure you have the following prerequisites:

- Python 3.12 installed.
- A Firebase project set up.
- Firebase Functions configured to use Python.
- Access to Gemini models.

Make sure your environment meets these requirements to leverage the full capabilities of GemBatch.

## Setup

firebase login
firebase init
- create a firestore database first
- .gitignore -> add venv/

Firestore
Functions
Storage
firestore.indexes.json
Python

gcloud auth
- gcloud config set project gembatch-test-v0-0-15
- gcloud auth login
- gcloud auth application-default login

- check requirements.txt has gembatch
- install in firebase functions's venv

- firebase deploy --only=functions
> first time may not success

- GEMBATCH_CLOUD_STORAGE_BUCKET needs to be unique

- firebase deploy --only=firestore
> https://console.firebase.google.com/project/${PROJECT_ID}/firestore/databases/-default-/indexes

## Setup Guide

Follow these steps to set up the GemBatch library in your environment:

### Step 1: Install Python 3.12
Ensure you have Python 3.12 installed on your system. You can download it from the [official Python website](https://www.python.org/downloads/).

### Step 2: Set Up Firebase

> Note: For detailed instructions, you can refer to the [official Firebase guide](https://firebase.google.com/docs/functions/get-started?gen=2nd#create-a-firebase-project).

1. Log in to Firebase:
    ```sh
    firebase login
    ```
2. Create a Firestore database first.
3. Initialize Firebase in your project directory:
    ```sh
    firebase init
    ```

    > Note: Make sure to initialize at least Firestore, Functions, and Storage in your Firebase project.
4. (Optional) Add `venv/` to your `.gitignore` file to make Google Cloud build more efficient by ignoring virtual environment files..

### Step 3: Authenticate with Google Cloud

1. Set your project:
    ```sh
    gcloud config set project $PROJECT_ID
    ```
2. Authenticate with Google Cloud:
    ```sh
    gcloud auth login
    ```
3. Authenticate application default credentials:
    ```sh
    gcloud auth application-default login
    ```

### Step 4: Install Dependencies
1. Ensure `gembatch` is listed in your `requirements.txt` file.
2. Install dependencies in Firebase Functions' virtual environment:
    ```sh
    pip install -r requirements.txt
    ```

### Step 5: Update and Deploy Firebase Functions

1. Update `firebase functions`'s `main.py` as shown below:
    ```python
    from firebase_admin import initialize_app
    from firebase_functions import https_fn, logger
    from vertexai import generative_models

    import gembatch
    from gembatch import *

    initialize_app()

    # omit
    ```

2. Deploy Firebase Functions:
    ```sh
    firebase deploy --only=functions
    ```
    > Note: The first deployment may not succeed. Retry if necessary.
    
    > Warning: Ensure the `GEMBATCH_CLOUD_STORAGE_BUCKET` environment variable is globally unique for creating a Google Cloud Storage bucket.

### Step 6: Initialize GemBatch

Run the following command to initialize GemBatch in your project:
```sh
gembatch init
```

The gembatch init command initializes the GemBatch environment by performing several tasks:

- Identifies the Firebase project and loads environment variables.
- Checks and enables necessary Google Cloud APIs like Vertex AI and BigQuery.
- Enables BigQuery audit logging.
- Creates a BigQuery dataset for storing prediction results.
- Creates a Google Cloud Storage bucket for batch processing.
- Updates Firestore indexes required for GemBatch.
- Deploys Eventarc triggers for handling events in the GemBatch environment.

### Step 7: Deploy Firestore
After running `gembatch init`, make sure the new indexes are deployed:
```sh
firebase deploy --only=firestore
```

You can view your Firestore indexes at:
[Firestore Indexes](https://console.firebase.google.com/project/${PROJECT_ID}/firestore/databases/-default-/indexes)

## Example
The core of gembatch is the `gembatch.submit(...)` function:

```python
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
        '123e4567-e89b-12d3-a456-426614174000'
    """
```

The following example demonstrates how to use the GemBatch library to submit a prompt to a Gemini model and handle the response. 


```python
from firebase_admin import initialize_app
from firebase_functions import https_fn, logger
from vertexai import generative_models

import gembatch
from gembatch import *

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
    return https_fn.Response("OK")
```

1. Import Necessary Modules:

    ```py
    from firebase_admin import initialize_app
    from firebase_functions import https_fn, logger
    from vertexai import generative_models

    import gembatch
    from gembatch import *
    ```

2. Initialize Firebase App:

    ```py
    initialize_app()
    ```

3. Define a Response Handler:

    ```py
    def echo_action(response: generative_models.GenerationResponse):
        logger.debug(response.to_dict())
        print("Echo action.")
    ```

    `echo_action` is a function that logs the response and prints a message. This function will be called when the Gemini model returns a response.

    > Note: The handler will be called within the `handleGemBatchRequestComplete` cloud function. You can check the log in the logs explorer with the following query:
    > ```
    > (resource.type = "cloud_function"
    > resource.labels.function_name = "handleGemBatchRequestComplete")
    > OR 
    > (resource.type = "cloud_run_revision"
    > resource.labels.service_name = "handlegembatchrequestcomplete")
    > ```

4. Define an HTTP Function:

    ```
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
    ```

    - on_request_example is an HTTP function that will be triggered by an HTTP request.
    - Inside this function, gembatch.submit is called to submit a prompt to the Gemini model. The prompt is a simple message "Hi! How are you?".
    - The echo_action function is passed as the handler to process the response from the Gemini model.
-    The function returns an HTTP response with the message "OK".



## Supported Models

GemBatch currently supports the following models:

- `publishers/google/models/gemini-1.5-flash-002`
- `publishers/google/models/gemini-1.5-flash-001`
- `publishers/google/models/gemini-1.5-pro-002`
- `publishers/google/models/gemini-1.5-pro-001`

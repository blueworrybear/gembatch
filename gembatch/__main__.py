"""GemBatch command-line interface."""

import argparse
import datetime as dt
import functools
import json
import pathlib
import string
import subprocess
from importlib import resources
from typing import Any

import dotenv
import firebase_admin  # type: ignore
import inquirer  # type: ignore
import prompt_toolkit as pt
import requests
from firebase_admin import storage  # type: ignore
from google.api_core import exceptions  # type: ignore

from gembatch import configs

# Initialize Firebase app
firebase_admin.initialize_app()
app: firebase_admin.App = firebase_admin.get_app()
project_id = app.project_id


class FirebaseProject:

    @functools.cached_property
    def project_root(self) -> pathlib.Path:
        cwd = pathlib.Path.cwd()
        while not (cwd / "firebase.json").exists():
            if cwd == cwd.parent:
                raise FileNotFoundError("firebase.json not found")
            cwd = cwd.parent
        return cwd

    def get_functions_folders(self) -> list[str]:
        with self.project_root.joinpath("firebase.json").open(
            "r", encoding="utf-8"
        ) as f:
            firebase_json = json.load(f)
        return [f.get("source", "") for f in firebase_json.get("functions", [])]

    def get_functions_dot_env(self, function_folder: str) -> pathlib.Path | None:
        env = self.project_root.joinpath(function_folder, f".env.{app.project_id}")
        if not env.exists():
            return None
        return env

    def load_firestore_indexes(self) -> dict[str, Any]:
        with self.project_root.joinpath("firestore.indexes.json").open(
            "r", encoding="utf-8"
        ) as f:
            return json.load(f)

    def update_firestore_indexes(self, indexes: dict[str, Any]):
        with self.project_root.joinpath("firestore.indexes.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(indexes, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="GemBatch command-line interface")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser(
        "init", help="Initialize the GemBatch environment"
    )
    init_parser.add_argument(
        "--firebase-functions-folder",
        type=str,
        default=None,
        help="Specify the Firebase functions folder to use",
    )
    init_parser.set_defaults(func=init)

    args = parser.parse_args()
    if args.command:
        args.func(args)
    else:
        parser.print_help()


def init(args):
    """Initialize the GemBatch environment."""
    project = FirebaseProject()
    if env := project.get_functions_dot_env("functions"):
        dotenv.load_dotenv(env)

    functions_folder: str = args.firebase_functions_folder  # type: ignore
    if functions_folder is None:
        folder_choices = project.get_functions_folders()
        if len(folder_choices) == 1:
            functions_folder = folder_choices[0]
            pt.print_formatted_text(
                pt.HTML(
                    f"Using the only Firebase functions folder found: <skyblue><b>{functions_folder}</b>,</skyblue>"
                )
            )
        else:
            functions_folder = inquirer.prompt(
                [
                    inquirer.List(
                        "functions_folder",
                        message="Select the Firebase functions folder to use",
                        choices=project.get_functions_folders(),
                    )
                ]
            )["functions_folder"]

    pt.print_formatted_text(
        pt.HTML(
            "<ansired>Warning: Please run <ansiwhite>firebase deploy --only=functions</ansiwhite> before moving on.</ansired>"
        )
    )
    continue_init = inquirer.prompt(
        [
            inquirer.Confirm(
                "continue",
                message=f"Initialization tasks will be run for the {project_id}. Do you want to continue?",
            )
        ]
    )["continue"]
    if not continue_init:
        pt.print_formatted_text(pt.HTML("<ansired>Aborted.</ansired>"))
        return
    initialize_environment(project=project, functions_folder=functions_folder)
    pt.print_formatted_text(
        pt.HTML(
            "<ansigreen>Initialization tasks for the GemBatch are completed.</ansigreen>"
        )
    )
    pt.print_formatted_text(
        pt.HTML(
            "<ansiyellow>Warning: Please run <ansiwhite>firebase deploy --only=firestore</ansiwhite> to deploy the firestore indexes.</ansiyellow>"
        )
    )


def initialize_environment(project: FirebaseProject, functions_folder: str):
    """Initialize the GemBatch environment."""
    pt.print_formatted_text(
        pt.HTML("<b>Running initialization tasks for the GemBatch environment...</b>")
    )
    init_apis()
    enable_audit_logging()
    create_dataset()
    create_bucket()
    update_firestore_indexes(project)
    deploy_eventarcs(project, functions_folder)


def init_apis():
    """Initialize Google Cloud APIs."""
    if is_api_enabled("aiplatform.googleapis.com"):
        pt.print_formatted_text(
            pt.HTML("<ansigreen>Vertex AI API is enabled.</ansigreen>")
        )
    else:
        pt.print_formatted_text(
            pt.HTML(
                "<ansired>Vertex AI API is not enabled., try to enable it...</ansired>"
            )
        )
        enable_api("aiplatform.googleapis.com")
    if is_api_enabled("bigquery.googleapis.com"):
        pt.print_formatted_text(
            pt.HTML("<ansigreen>BigQuery API is enabled.</ansigreen>")
        )
    else:
        pt.print_formatted_text(
            pt.HTML(
                "<ansired>BigQuery API is not enabled., try to enable it...</ansired>"
            )
        )
        enable_api("bigquery.googleapis.com")


def is_api_enabled(api_name):
    """Check if a Google Cloud API is enabled."""
    res = requests.get(
        f"https://serviceusage.googleapis.com/v1/projects/{project_id}/services/{api_name}",
        headers={
            "Authorization": f"Bearer {app.credential.get_access_token().access_token}"
        },
        timeout=60,
    )
    res.raise_for_status()
    service = res.json()
    return service["state"] == "ENABLED"


def enable_api(api_name):
    """Enable a Google Cloud API."""
    res = requests.post(
        f"https://serviceusage.googleapis.com/v1/projects/{project_id}/services/{api_name}:enable",
        headers={
            "Authorization": f"Bearer {app.credential.get_access_token().access_token}"
        },
        timeout=60,
    )
    res.raise_for_status()
    pt.print_formatted_text(
        pt.HTML(f"<ansigreen>{api_name} API is enabled.</ansigreen>")
    )


def enable_audit_logging():
    """Enable BigQuery audit logging."""
    pt.print_formatted_text(pt.HTML("<b>Enabling BigQuery audit logging...</b>"))
    res = requests.post(
        f"https://cloudresourcemanager.googleapis.com/v3/projects/{project_id}:getIamPolicy",
        headers={
            "Authorization": f"Bearer {app.credential.get_access_token().access_token}"
        },
        timeout=60,
    )
    res.raise_for_status()
    service_configs: dict = res.json()  # type: ignore
    audit_config: list = service_configs.get("auditConfigs", None)
    if audit_config is None:
        audit_config = []
        service_configs["auditConfigs"] = audit_config
    bigquery_audit_config = next(
        (
            config
            for config in audit_config
            if config["service"] == "bigquerydatapolicy.googleapis.com"
        ),
        None,
    )

    if bigquery_audit_config:
        log_types = {log["logType"] for log in bigquery_audit_config["auditLogConfigs"]}
        if "DATA_READ" in log_types and "DATA_WRITE" in log_types:
            # Already enabled
            pt.print_formatted_text(
                pt.HTML("<ansigreen>BigQuery audit logging is enabled.</ansigreen>")
            )
            return
    pt.print_formatted_text(
        pt.HTML(
            "<ansired>BigQuery audit logging is not enabled., try to enable it...</ansired>"
        )
    )
    if bigquery_audit_config is None:
        bigquery_audit_config = {
            "service": "bigquerydatapolicy.googleapis.com",
        }
        audit_config.append(bigquery_audit_config)
    bigquery_audit_config["auditLogConfigs"] = [
        {"logType": "DATA_READ"},
        {"logType": "DATA_WRITE"},
    ]
    res = requests.post(
        f"https://cloudresourcemanager.googleapis.com/v3/projects/{project_id}:setIamPolicy",
        headers={
            "Authorization": f"Bearer {app.credential.get_access_token().access_token}"
        },
        json={"policy": service_configs, "updateMask": "auditConfigs"},
        timeout=60,
    )
    res.raise_for_status()
    pt.print_formatted_text(
        pt.HTML("<ansigreen>BigQuery audit logging is enabled.</ansigreen>")
    )


def create_dataset(expiration: dt.timedelta = dt.timedelta(days=3)):
    """Create a BigQuery dataset for prediction results."""
    dataset = configs.GEMBATCH_PREDICTION_DATASET.value
    if is_dataset_exists(dataset):
        pt.print_formatted_text(
            pt.HTML(
                f"<ansiyellow>Dataset <b>{dataset}</b> already exists.</ansiyellow>"
            )
        )
        return
    pt.print_formatted_text(pt.HTML(f"Creating dataset <b>{dataset}</b>..."))
    res = requests.post(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/datasets",
        headers={
            "Authorization": f"Bearer {app.credential.get_access_token().access_token}"
        },
        json={
            "datasetReference": {
                "projectId": project_id,
                "datasetId": dataset,
            },
            "defaultTableExpirationMs": expiration.total_seconds() * 1000,
            "location": configs.GEMBATCH_REGION.value,
        },
        timeout=60,
    )
    res.raise_for_status()
    pt.print_formatted_text(
        pt.HTML(f"<ansigreen>Dataset <b>{dataset}</b> is created.</ansigreen>")
    )


def is_dataset_exists(dataset_id) -> bool:
    """Check if a BigQuery dataset exists."""
    res = requests.get(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{project_id}/datasets/{dataset_id}",
        headers={
            "Authorization": f"Bearer {app.credential.get_access_token().access_token}"
        },
        timeout=60,
    )
    return res.ok


def create_bucket():
    """Create a Cloud Storage bucket for batch processing."""
    pt.print_formatted_text(pt.HTML("<b>Creating Cloud Storage bucket...</b>"))
    bucket_name = configs.GEMBATCH_CLOUD_STORAGE_BUCKET.value
    bucket = storage.bucket(bucket_name)
    exists = False
    try:
        exists = bucket.exists()
    except (exceptions.NotFound, exceptions.Forbidden) as e:
        print(e.message)
    if exists:
        pt.print_formatted_text(
            pt.HTML(
                f"<ansiyellow>Bucket <b>{bucket_name}</b> already exists.</ansiyellow>"
            )
        )
        return
    pt.print_formatted_text(
        pt.HTML(f"<ansigreen>Creating bucket <b>{bucket_name}</b>...</ansigreen>")
    )
    bucket.create(location=configs.GEMBATCH_REGION.value)
    pt.print_formatted_text(
        pt.HTML(f"<ansigreen>Bucket <b>{bucket_name}</b> is created.</ansigreen>")
    )


def update_firestore_indexes(project: FirebaseProject):
    """Update Firestore indexes."""
    pt.print_formatted_text(
        pt.HTML("<b>Updating Firestore indexes for the GemBatch environment...</b>")
    )
    continue_update = inquirer.prompt(
        [
            inquirer.Confirm(
                "continue",
                message="firestore.indexes.json will be updated. Do you want to continue?",
            )
        ]
    )["continue"]
    if not continue_update:
        pt.print_formatted_text(pt.HTML("<ansired>Aborted.</ansired>"))
        return
    indexes_config = project.load_firestore_indexes()
    indexes = [
        i
        for i in indexes_config.get("indexes", [])
        if i.get("collectionGroup", None)
        not in [
            configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value,
            configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value,
            configs.GEMBATCH_FIRESTORE_REQUESTS_COLLECTION.value,
        ]
    ]
    fields_override = [
        i
        for i in indexes_config.get("fieldOverrides", [])
        if i.get("collectionGroup", None)
        not in [
            configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value,
            configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value,
            configs.GEMBATCH_FIRESTORE_REQUESTS_COLLECTION.value,
        ]
    ]

    template = string.Template(
        resources.open_text("gembatch", "firestore.indexes.json").read()
    )
    target_config = json.loads(
        template.substitute(
            batch_queue=configs.GEMBATCH_FIRESTORE_BATCH_QUEUE_COLLECTION.value,
            job_queue=configs.GEMBATCH_FIRESTORE_JOB_QUEUE_COLLECTION.value,
            request_queue=configs.GEMBATCH_FIRESTORE_REQUESTS_COLLECTION.value,
        )
    )

    indexes.extend(target_config.get("indexes", []))
    fields_override.extend(target_config.get("fieldOverrides", []))
    indexes_config["indexes"] = indexes
    indexes_config["fieldOverrides"] = fields_override
    project.update_firestore_indexes(indexes_config)

    pt.print_formatted_text(
        pt.HTML("<ansigreen>Firestore indexes are updated.</ansigreen>")
    )


def deploy_eventarcs(project: FirebaseProject, functions_folder: str):
    pt.print_formatted_text(
        pt.HTML("<b>Deploying Eventarc triggers for the GemBatch environment...</b>")
    )
    build_file = project.project_root.joinpath("gembatch.cloudbuild.yml")
    if build_file.exists():
        pt.print_formatted_text(
            pt.HTML(
                f"<ansiyellow>{build_file.as_posix()} file already exists...</ansiyellow>"
            )
        )
        continue_build = inquirer.prompt(
            [
                inquirer.Confirm(
                    "continue",
                    message="Do you want to continue and overwrite the existing file?",
                )
            ]
        )["continue"]
        if not continue_build:
            pt.print_formatted_text(pt.HTML("<ansired>Aborted.</ansired>"))
            return
    with open(build_file, "w", encoding="utf-8") as f:
        t = string.Template(resources.open_text("gembatch", "cloudbuild.yml").read())
        f.write(
            t.substitute(
                dataset=configs.GEMBATCH_PREDICTION_DATASET.value,
                display=configs.GEMBATCH_BATCH_JOB_DISPLAY_NAME.value,
                memory=str(configs.GEMBATCH_LARGE_JOB_MEMORY.value),
            )
        )
    # Run gcloud builds submit in the project root
    subprocess.run(
        [
            "gcloud",
            "builds",
            "submit",
            "--region=" + configs.GEMBATCH_REGION.value,
            "--config=" + build_file.name,
            f"./{functions_folder}",
        ],
        check=True,
        cwd=project.project_root.absolute().as_posix(),
    )


if __name__ == "__main__":
    main()

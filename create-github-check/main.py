import os
import ast
import base64
from github import Github
from google.cloud import secretmanager_v1


def create_github_check(event, context):
    build = ast.literal_eval(base64.b64decode(event["data"]).decode("utf-8"))
    try:
        if build["source"]["storageSource"]["bucket"] != "studio-pull-request":
            return "This is not for pull request demo server cloud build."
    except KeyError:
        return "This is not for pull request demo server cloud build."

    secret_manager_client = secretmanager_v1.SecretManagerServiceClient()
    secret_name = secret_manager_client.secret_version_path(
        os.environ["GCP_PROJECT"],
        os.environ["GITHUB_ACCESS_TOKEN_SECRET_NAME"],
        "latest",
    )
    github_access_token = secret_manager_client.access_secret_version(
        secret_name
    ).payload.data.decode("UTF-8")

    g = Github(github_access_token)
    repo = g.get_repo(os.environ["GITHUB_REPO"])
    commit_sha = build["substitutions"]["COMMIT_SHA"]
    success_description = "Success: {}.studio.cd.learningequality.org".format(
        build["substitutions"]["_RELEASE_NAME"]
    )

    status_map = {
        "QUEUED": ["pending", "Build is queued"],
        "WORKING": ["pending", "Build is being executed"],
        "FAILURE": ["error", "Build failed"],
        "INTERNAL_ERROR": ["failure", "Internal builder error"],
        "CANCELLED": ["failure", "Build cancelled by user"],
        "TIMEOUT": ["failure", "Build timed out"],
        "SUCCESS": ["success", success_description],
    }

    state, description = status_map[build["status"]]

    repo.get_commit(sha=commit_sha).create_status(
        state=state, target_url=build["logUrl"], description=description, context="Demo"
    )

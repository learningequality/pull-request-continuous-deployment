import os
import ast
import base64
from github import Github
from google.cloud import storage


# Constants
STATUS_MAP = {
    "QUEUED": ["pending", "Build is queued"],
    "WORKING": ["pending", "Build is being executed"],
    "FAILURE": ["error", "Build failed"],
    "INTERNAL_ERROR": ["failure", "Internal builder error"],
    "CANCELLED": ["failure", "Build cancelled by user"],
    "TIMEOUT": ["failure", "Build timed out"],
    "SUCCESS": ["success", ""],
}


def cloud_build_github_check(event, context):
    build = ast.literal_eval(base64.b64decode(event["data"]).decode("utf-8"))
    try:
        if build["source"]["storageSource"]["bucket"] != "studio-pull-request":
            return "This is not for pull request demo server cloud build."
    except KeyError:
        return "This is not for pull request demo server cloud build."

    github_access_token = (
        storage.Client()
        .get_bucket(os.environ["STORAGE_BUCKET"])
        .get_blob("github_access_token")
        .download_as_string()
        .decode("utf-8")
        .rstrip()
    )

    g = Github(github_access_token)
    repo = g.get_repo(os.environ["GITHUB_REPO"])
    commit_sha = build["substitutions"]["COMMIT_SHA"]
    success_description = "Build finished successfully. Check {}.studio.cd.learningequality.org".format(
        build["substitutions"]["_RELEASE_NAME"]
    )
    status_map["SUCCESS"][1] = success_description

    state, description = status_map[build["status"]]

    repo.get_commit(sha=commit_sha).create_status(
        state=state,
        target_url=build["logUrl"],
        description=description,
        context="Pull Request Demo",
    )

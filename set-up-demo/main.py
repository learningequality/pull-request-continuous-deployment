import os
import base64
import yaml
import requests
import zipfile
import tarfile
from googleapiclient import discovery
from google.cloud import storage


# Constants
MSG_SET_UP_SERVER = "Set up"


def unzip_file_preserve_permissions(zipname):
    """
    Unzip a zip file using zipfile module.
    Note that zipfile module's function `extractall()` does not
    preserve permissions. https://stackoverflow.com/a/46837272
    """
    with zipfile.ZipFile(zipname, "r") as zf:
        for info in zf.infolist():
            zf.extract(info.filename, path="/tmp")
            out_path = os.path.join("/tmp", info.filename)

            # Preserving file permissions in UNIX system after extracting the zip
            perm = info.external_attr >> 16
            if perm:
                os.chmod(out_path, perm)
        return zf.namelist()[0]


def upload_tarball_to_storage(user, repo, branch, bucket_name, destination_blob_name):
    """
    Get the zip of the code from github, convert it to a tarball and upload it
    to the bucket in Google Cloud Storage.
    """
    # Download zip file from github
    resp = requests.get(
        "https://github.com/{user}/{repo}/archive/{branch}.zip".format(
            user=user, repo=repo, branch=branch
        )
    )
    filename = "{user}-{repo}-{branch}".format(
        user=user, repo=repo, branch=branch).replace("/", "-")
    zipname = "/tmp/{}.zip".format(filename)
    with open(zipname, "wb") as f:
        f.write(resp.content)

    unzipped_folder = unzip_file_preserve_permissions(zipname)

    # Compress the unzipped folder to be tar.gz
    targz_name = os.path.join("/tmp", destination_blob_name)
    unzipped_folder = os.path.join("/tmp", unzipped_folder)
    with tarfile.open(targz_name, "w:gz") as tar:
        tar.add(unzipped_folder, arcname=os.path.sep)

    # Upload the tar.gz file to Google Cloud Storage
    storage_client = storage.Client()
    bucket = storage_client.get_bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)

    blob.upload_from_filename(targz_name, content_type="application/x-gzip")

    print("File uploaded to {}/{}.".format(bucket_name, destination_blob_name))


def set_up_demo(event, context):
    """
    Run the build on Cloud Build every time a pull request is created
    or a new commit is pushed to the pull request.
    """

    pubsub_message = base64.b64decode(event["data"]).decode("utf-8")
    if pubsub_message != MSG_SET_UP_SERVER:
        return "Not setting up the demo server."

    # Variables
    project = os.environ["GCP_PROJECT"]  # Google Cloud Project ID
    user = event["attributes"]["user"]  # User who creates the PR
    repo = event["attributes"]["repo"]  # Github repo that the PR is from
    branch = event["attributes"]["branch"]  # The head branch of the PR
    # The latest commit sha of the PR
    commit_sha = event["attributes"]["commit_sha"]
    bucket_name = "studio-pull-request"  # The GCS bucket to store the github tarball
    destination_blob_name = "{user}-{repo}-{branch}-{commit}.tar.gz".format(
        user=user, repo=repo, branch=branch, commit=commit_sha
    ).replace("/", "-")  # The name of the github tarball to store in GCS
    release_name = "-".join([user, branch]).replace(
        "_", "-").replace("/", "-").lower()

    # Upload the github code as a tarball to the bucket in Google Cloud Storage.
    upload_tarball_to_storage(
        user, repo, branch, bucket_name, destination_blob_name)

    service = discovery.build("cloudbuild", "v1", cache_discovery=False)
    resp = requests.get(
        "https://raw.github.com/{user}/{repo}/{branch}/cloudbuild-pr.yaml".format(
            user=user, repo=repo, branch=branch
        )
    )
    cloudbuild_yaml = yaml.load(resp.text, Loader=yaml.SafeLoader)

    # Configure the build
    build_body = {
        "source": {
            "storageSource": {"bucket": bucket_name, "object": destination_blob_name}
        },
        "substitutions": {
            "COMMIT_SHA": commit_sha,
            "_RELEASE_NAME": release_name,
            "_STORAGE_BUCKET": os.environ["STORAGE_BUCKET"],
            "_DATABASE_INSTANCE_NAME": os.environ["DATABASE_INSTANCE_NAME"],
            "_POSTGRES_USERNAME": os.environ["POSTGRES_USERNAME"],
            "_POSTGRES_PASSWORD": os.environ["POSTGRES_PASSWORD"],
            "_TARBALL_LOCATION": "gs://{}/{}".format(
                bucket_name, destination_blob_name
            ),
        },
    }
    build_body.update(cloudbuild_yaml)

    # Create the build
    print("Starting to create build for commit {}".format(commit_sha))
    service.projects().builds().create(projectId=project, body=build_body).execute()

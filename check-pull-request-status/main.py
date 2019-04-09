import os
import json
import requests
from github import Github
from google.cloud import pubsub_v1
from google.cloud import storage

# Constants
TOPIC_TURN_OFF_SERVER = "projects/{project_id}/topics/{topic}".format(
    project_id=os.environ["GCP_PROJECT"], topic="turn-off-demo-server"
)
TOPIC_SET_UP_SERVER = "projects/{project_id}/topics/{topic}".format(
    project_id=os.environ["GCP_PROJECT"], topic="set-up-demo-server"
)
MSG_TURN_OFF_SERVER = b"Turn off"
MSG_SET_UP_SERVER = b"Set up"


def publish_message_to_pubsub(publisher, topic, message, info):
    """Publish a 'set up' message to the topic 'set-up-demo-server'
    or a 'turn off' message to the topic 'turn-off-demo-server'
    in Cloud Pub/Sub to trigger the corresponding cloud functions.
    """
    publisher.publish(
        topic,
        message,
        user=info["user"]["login"],
        repo=info["repo"]["name"],
        branch=info["ref"],
        commit_sha=info["sha"],
    )


def _get_collaborators():
    """Get all the collaborators in this GitHub repository."""
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

    collaborators = []
    for user in repo.get_collaborators(affiliation="direct"):
        collaborators.append(user.login)

    return collaborators


def check_pull_request_status(request):
    if not request.json.get("pull_request"):
        print("This is not a pull request. Do not trigger any functions.")
        return "Do not trigger any functions."

    if (
        request.json["pull_request"]["state"] == "closed"
        and request.json["action"] != "closed"
    ):
        print("Operations on a closed pull request. Do not trigger any functions.")
        return "Do not trigger any functions."

    collaborators = _get_collaborators()
    if request.json["sender"]["login"] not in collaborators:
        return "The user is not authorized to trigger the function."

    demo_label = os.environ["LABEL_NAME"]
    current_labels = request.json["pull_request"]["labels"]
    changed_label = request.json.get("label")
    if (
        not current_labels
        or demo_label not in [label["name"] for label in current_labels]
    ) and (not changed_label or changed_label["name"] != demo_label):
        print(
            "Label {} is not attached to the pull request. Do not trigger any functions.".format(
                demo_label
            )
        )
        return "Do not trigger any functions."

    # Start from here, the label for demo server must exist, be added or be removed in the pull request.
    # the latter two come with the label or unlabel action
    action = request.json["action"]
    info = request.json["pull_request"]["head"]
    publisher = pubsub_v1.PublisherClient()

    if action == "closed":
        print("The pull request is closed. Turning off the demo server...")
        publish_message_to_pubsub(
            publisher, TOPIC_TURN_OFF_SERVER, MSG_TURN_OFF_SERVER, info
        )
        return "Turning off the demo server..."

    elif action == "unlabeled" and changed_label["name"] == demo_label:
        print(
            "Removing the label {} from the pull request. Turning off the demo server...".format(
                demo_label
            )
        )
        publish_message_to_pubsub(
            publisher, TOPIC_TURN_OFF_SERVER, MSG_TURN_OFF_SERVER, info
        )
        return "Turning off the demo server..."

    elif action in ["reopened", "synchronize"]:
        print("The pull request is {}. Setting up the demo server...".format(action))
        publish_message_to_pubsub(
            publisher, TOPIC_SET_UP_SERVER, MSG_SET_UP_SERVER, info
        )
        return "Setting up the demo server..."

    elif action == "labeled" and changed_label["name"] == demo_label:
        print(
            "Labeling the pull request with {}. Setting up the demo server...".format(
                demo_label
            )
        )
        publish_message_to_pubsub(
            publisher, TOPIC_SET_UP_SERVER, MSG_SET_UP_SERVER, info
        )
        return "Setting up the demo server..."

    else:
        print(
            "No need to set up or turn off demo server. Do not trigger any functions."
        )
        return "Do not trigger any functions."

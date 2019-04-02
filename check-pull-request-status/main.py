import os
import json
import requests
from github import Github
from google.cloud import pubsub_v1
from google.cloud import storage

# Constants
TOPIC_TURN_DOWN_SERVER = "projects/{project_id}/topics/{topic}".format(project_id=os.environ["GCP_PROJECT"], topic="turn-down-demo-server")
TOPIC_SET_UP_SERVER = "projects/{project_id}/topics/{topic}".format(project_id=os.environ["GCP_PROJECT"], topic="set-up-demo-server")
MSG_TURN_DOWN_SERVER = b"Turn down"
MSG_SET_UP_SERVER = b"Set up"


def publish_message_to_turn_down_server(info):
    publisher.publish(
        TOPIC_TURN_DOWN_SERVER,
        MSG_TURN_DOWN_SERVER,
        user=info["user"]["login"],
        branch=info["ref"],
        commit_sha=info["sha"],
    )

def publish_message_to_set_up_server(info):
    publisher.publish(
        TOPIC_SET_UP_SERVER,
        MSG_SET_UP_SERVER,
        user=info["user"]["login"],
        repo=info["repo"]["name"],
        branch=info["ref"],
        commit_sha=info["sha"],
    )

def get_collaborators():
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

    collaborators = get_collaborators()
    if request.json["sender"]["login"] not in collaborators:
        return "The user is not authorized to trigger the function."

    demo_label = os.environ["LABEL_NAME"]
    current_labels = request.json["pull_request"]["labels"]
    changed_label = request.json.get("label")
    if (
        not current_labels or demo_label not in [label["name"] for label in current_labels]
    ) and (not changed_label or changed_label["name"] != demo_label):
        print(
            "Label {} is not attached to the pull request. Do not trigger any functions.".format(demo_label)
        )
        return "Do not trigger any functions."

    # Start from here, the label for demo server must exist, be added or be removed in the pull request.
    # the latter two come with the label or unlabel action
    action = request.json["action"]

    publisher = pubsub_v1.PublisherClient()

    # Turn down #1
    if action == "closed":
        print("The pull request is closed. Turning down the demo server...")
        publish_message_to_set_up_server(publisher, request.json["pull_request"]["head"])
        return "Turning down the demo server..."

    elif action == "unlabeled" and changed_label["name"] == demo_label:
        print(
            "Removing the label {} from the pull request. Turning down the demo server...".format(demo_label)
        )
        publish_message_to_set_up_server(publisher, request.json["pull_request"]["head"])
        return "Turning down the demo server..."

    # Deploy #1
    elif action in ["reopened", "synchronize"]:
        print("The pull request is {}. Setting up the demo server...".format(action))
        publish_message_to_set_up_server(publisher, request.json["pull_request"]["head"])
        return "Setting up the demo server..."

    elif action == "labeled" and changed_label["name"] == demo_label:
        print("Labeling the pull request with {}. Setting up the demo server...".format(demo_label))
        publish_message_to_set_up_server(publisher, request.json["pull_request"]["head"])
        return "Setting up the demo server..."

    else:
        print(
            "No need to set up or turn down demo server. Do not trigger any functions."
        )
        return "Do not trigger any functions."

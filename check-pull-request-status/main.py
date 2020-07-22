import os
from github import Github
from google.cloud import pubsub_v1
from google.cloud import secretmanager_v1

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


def _get_le_code_reviewers():
    """Get all the Learning Equality code reviewers in this GitHub repository."""
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
    org = g.get_organization(os.environ["GITHUB_ORG"])
    for team in org.get_teams():
        if team.name == "Learning Equality code reviewers":
            team_id = team.id
            break

    reviewers = []
    for member in org.get_team(team_id).get_members():
        reviewers.append(member.login)

    return reviewers


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

    reviewers = _get_le_code_reviewers()
    if request.json["sender"]["login"] not in reviewers:
        return "The user is not authorized to trigger the function."

    demo_label = os.environ["LABEL_NAME"]
    current_labels = request.json["pull_request"]["labels"]
    changed_label = request.json.get("label")

    # Do not trigger the function if
    # * there is no label attached to the PR
    # * or there is/are labels attached to the PR but qa-ready is not one of them
    # * and we are not removing qa-ready label from the PR (as we would need to
    #   turn off the server if we are)
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

    # Starting from here, the label for demo server must be either added or
    # removed in the pull request.
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

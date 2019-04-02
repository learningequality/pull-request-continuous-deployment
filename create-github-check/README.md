# cloud-build-github-check
gcloud functions deploy cloud_build_github_check --runtime python37 --trigger-topic cloud-builds --service-account <service_account_email> --env-vars-file .env.yaml

code is based on https://cloud.google.com/community/tutorials/cloud-functions-github-container-builder

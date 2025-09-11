#!/bin/bash
# set the profile and login to aws
export AWS_PROFILE=byteloop
echo "Switched to BtyleLoop"

log_info() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] $1"
}
log_error() {
  echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] $1" >&2
}

log_info "Converting .env_ordelo_agent to env.json..."

jq -Rn '
  [inputs
    | select(. != "" and .[0:1] != "#")
    | capture("(?<key>[^=]+)=(?<value>.*)")
    | { (.key): (.value 
        | sub("^[\"'"'"']";"") 
        | sub("[\"'"'"'][,\n]*$";"")) }
  ] | add
' < .env_ordelo_agent > env.json

log_info "Updating secrets..."
aws secretsmanager update-secret \
  --region eu-west-2 \
  --secret-id ordelo-agent-env \
  --secret-string file://env.json

if [ $? -ne 0 ]; then
  log_error "Failed to upload secret to AWS Secrets Manager."
  exit 1
else
  log_info "Secret uploaded to AWS Secrets Manager successfully."
fi
"""
AWS settings configuration for S3, Secrets Manager, and Lambda compatibility.
  . Depends on: os, boto3, botocore.exceptions, pydantic_settings.BaseSettings, SettingsConfigDict, functools.lru_cache, json
  . Defines AwsSettings for managing AWS credentials and config
  . Provides secrets_client property for secretsmanager using boto3
  . Detects AWS Lambda environment and uses default credentials/session if running on Lambda
  . Loads ordelo_agent_env from secrets manager or environment depending on context
Functions/Classes
  . AwsSettings
    . secrets_client (property)
    . get_secret
  . is_running_on_lambda
  . get_secrets_client
  . ordelo_agent_env (dict)
"""

# %%

# %%
import os
import boto3
from botocore.exceptions import ClientError
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class AwsSettings(BaseSettings):
    key_id: str
    access_key: str
    region: str
    secret_name: str

    model_config = SettingsConfigDict(
        env_prefix="AWS_SETTINGS_", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def secrets_client(self):
        """Get a boto3 secretsmanager client using the configured credentials."""
        session = boto3.Session(
            aws_access_key_id=self.key_id,
            aws_secret_access_key=self.access_key,
            region_name=self.region,
        )
        return session.client("secretsmanager")

    def get_secret(self):
        try:
            response = self.secrets_client.get_secret_value(SecretId=self.secret_name)
            return response["SecretString"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"Secret {self.secret_name} not found.")
            else:
                print(f"Error retrieving secret {self.secret_name}: {e}")
            return None


def is_running_on_lambda():
    """Detect if running inside AWS Lambda environment."""
    return "AWS_LAMBDA_FUNCTION_NAME" in os.environ


def get_secrets_client():
    """Return a boto3 secretsmanager client appropriate for the environment."""
    if is_running_on_lambda():
        # Use default session/credentials from Lambda execution role
        region = os.environ.get("AWS_REGION", "eu-west-2")
        session = boto3.Session(region_name=region)
        return session.client("secretsmanager")
    else:
        aws_settings = AwsSettings()
        return aws_settings.secrets_client


def get_ordelo_agent_env(secret_name=None):
    """Fetch and parse the secret string for ordelo_agent_env."""
    client = get_secrets_client()
    # Use provided secret_name, or try to get from AwsSettings/environment
    if secret_name:
        use_secret_name = secret_name
    elif not is_running_on_lambda():
        use_secret_name = AwsSettings().secret_name
    else:
        use_secret_name = os.environ.get("ORDELO_AGENT_SECRET_NAME", "ordelo-agent-env")
    try:
        response = client.get_secret_value(SecretId=use_secret_name)
        return json.loads(response["SecretString"])
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            print(f"Secret {use_secret_name} not found.")
        else:
            print(f"Error retrieving secret {use_secret_name}: {e}")
        return None


ordelo_agent_env = get_ordelo_agent_env("ordelo-agent-env")
# %%
""" How to upload secrets to aws secrets manager
1. Create env.json file

jq -Rn '
  [inputs
    | select(. != "" and .[0:1] != "#")
    | capture("(?<key>[^=]+)=(?<value>.*)")
    | { (.key): (.value 
        | sub("^[\"'"'"']";"") 
        | sub("[\"'"'"'][,\n]*$";"")) }
  ] | add
' < .env_ordelo_agent > env.json

2. Create or update secrets

aws secretsmanager update-secret \
  --region eu-west-2 \
  --secret-id ordelo-agent-env \
  --secret-string file://env.json

aws secretsmanager create-secret \
  --region eu-west-2 \
  --name ordelo-agent-env \
  --secret-string file://env.json

3. Add policy to IAM role
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:****"
    }
  ]
}
"""
# %%
""" How to upload secrets to lambda function
1. Create env.json file

jq -Rn '
  [inputs
    | select(. != "" and .[0:1] != "#")
    | capture("(?<key>[^=]+)=(?<value>.*)")
    | { (.key): (.value 
        | sub("^[\"'"'"']";"") 
        | sub("[\"'"'"'][,\n]*$";"")) }
  ] | add
' < .env > env.json

2. Create or update secrets
aws lambda update-function-configuration \
  --function-name ordelo-agent \
  --environment file://env.json

"""
"""
filter logs
- "START RequestId" - "END RequestId" - "REPORT RequestId"
"""

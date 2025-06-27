"""
AWS settings configuration for S3 and related AWS operations.
  . Depends on: os, boto3, botocore.exceptions, pydantic_settings.BaseSettings, SettingsConfigDict, functools.lru_cache
  . Defines AwsSettings for managing AWS credentials and config
  . Provides a boto_client property for S3 operations using boto3
Functions/Classes
  . AwsSettings
    . boto_client (property)
  . aws_settings (instance)
"""

# %%

# %%
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


aws_settings = AwsSettings()
ordelo_agent_env = json.loads(aws_settings.get_secret())
# aws_settings.get_secret()
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

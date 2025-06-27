docker build -t ordelo-agent .

aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin 890742579621.dkr.ecr.eu-west-2.amazonaws.com

<!-- Setting up aws for ecr and container push -->
docker build -t ordelo-agent:latest .
docker tag ordelo-agent:latest 890742579621.dkr.ecr.eu-west-2.amazonaws.com/byteloop/ordelo-agent
docker push 890742579621.dkr.ecr.eu-west-2.amazonaws.com/byteloop/ordelo-agent:latest


<!-- Creating env.json, this is required for both lambda and for SMS -->
- convert .env to json
jq -Rn '
  [inputs
    | select(. != "" and .[0:1] != "#")
    | capture("(?<key>[^=]+)=(?<value>.*)")
    | { (.key): (.value 
        | sub("^[\"'"'"']";"") 
        | sub("[\"'"'"'][,\n]*$";"")) }
  ] | add
' < .env > env.json

<!-- - update the lambda environment variables - This was not possible because of the size of the env.json file -->
aws lambda update-function-configuration \
  --function-name ordelo-agent \
  --environment file://env.json


<!-- aws secrets manager -->
aws secretsmanager update-secret \
  --secret-id ordelo-agent-env \
  --secret-string file://env.json

aws secretsmanager create-secret \
  --name ordelo-agent-env \
  --secret-string file://env.json

<!-- Adding policy ot iam role on aws lambda -->
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "secretsmanager:GetSecretValue",
      "Resource": "arn:aws:secretsmanager:eu-west-2:89
    }
  ]
}


stat -c %s env.json

<!-- Adding custom domain -->
Get 
<!-- Assigning custom domain -->
https://chatgpt.com/c/68320c4a-0d00-800a-b1a7-1b0ebcbfb180
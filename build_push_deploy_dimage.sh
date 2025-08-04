#!/bin/bash
# set the profile and login to aws
export AWS_PROFILE=byteloop
echo "Switched to BtyleLoop"

aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin 890742579621.dkr.ecr.eu-west-2.amazonaws.com
echo "Logged in to AWS ECR"

docker build -t ordelo-agent:latest .
docker tag ordelo-agent:latest 890742579621.dkr.ecr.eu-west-2.amazonaws.com/byteloop/ordelo-agent
docker push 890742579621.dkr.ecr.eu-west-2.amazonaws.com/byteloop/ordelo-agent:latest

# Wait for 10 seconds to ensure ECR image is available
echo "Waiting 10 seconds for ECR image to be available..."
sleep 10


: '
docker build -t ordelo-local .

docker run --env-file .env -p 80:80 ordelo-local

docker run -it --entrypoint /bin/bash ordelo-local
'
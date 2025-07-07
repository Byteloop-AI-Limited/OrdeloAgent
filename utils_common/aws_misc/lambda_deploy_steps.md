docker build -t ordelo-agent .

aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin 890742579621.dkr.ecr.eu-west-2.amazonaws.com

<!-- Setting up aws for ecr and container push -->
docker build -t ordelo-agent:latest .
docker tag ordelo-agent:latest 890742579621.dkr.ecr.eu-west-2.amazonaws.com/byteloop/ordelo-agent
docker push 890742579621.dkr.ecr.eu-west-2.amazonaws.com/byteloop/ordelo-agent:latest


<!-- Adding custom domain -->
Get 
<!-- Assigning custom domain -->
https://chatgpt.com/c/68320c4a-0d00-800a-b1a7-1b0ebcbfb180
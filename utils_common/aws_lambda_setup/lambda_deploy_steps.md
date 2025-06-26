docker build -t ordelo .
<!-- How to pass the .env file? -->
docker run -p 3444:3444 --env-file .env ordelo
docker run -p 3444:3444 ordelo

<!-- Setting up aws for ecr and container push -->
docker build -t ordelo:latest .
docker tag ordelo:latest 890742579621.dkr.ecr.eu-west-2.amazonaws.com/byteloop/ordelo
docker push 890742579621.dkr.ecr.eu-west-2.amazonaws.com/byteloop/ordelo


aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin 890742579621.dkr.ecr.eu-west-2.amazonaws.com


<!-- Creating AWS Lambda - on console, note the region being used -->
- convert .env to json
jq -Rn '
  [inputs
    | select(. != "" and .[0:1] != "#")
    | capture("(?<key>[^=]+)=(?<value>.*)")
    | { (.key): .value }
  ] | add | {Variables: .}
' < .env > env.json

- update the lambda environment variables
aws lambda update-function-configuration \
  --function-name ordelo \
  --environment file://env.json

<!-- Adding custom domain -->
Get 
<!-- Assigning custom domain -->
https://chatgpt.com/c/68320c4a-0d00-800a-b1a7-1b0ebcbfb180
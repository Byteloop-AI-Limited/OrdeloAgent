#!/bin/bash
# set the profile and login to aws
export AWS_PROFILE=byteloop
echo "Switched to BtyleLoop"



aws apprunner pause-service \
  --service-arn arn:aws:apprunner:eu-west-2:890742579621:service/OrdeloAgentRunner/623a4467a103486390040f64d6ca9574 \
  --region eu-west-2
  

aws apprunner resume-service \
  --service-arn arn:aws:apprunner:eu-west-2:890742579621:service/OrdeloAgentRunner/623a4467a103486390040f64d6ca9574 \
  --region eu-west-2
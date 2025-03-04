kubectl create secret generic lambda-trigger-config \
  --namespace argocd \
  --from-literal=ARGOCD_TOKEN=$ARGOCD_TOKEN \
  --from-literal=AWS_REGION=us-west-2 \
  --from-literal=LOG_LEVEL=INFO
  --from-literal=LAMBDA_ARN="arn:aws:lambda:us-west-2:590184059249:function:lambda-argocd-trigger"
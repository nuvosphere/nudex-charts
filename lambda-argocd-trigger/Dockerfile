FROM public.ecr.aws/lambda/python:3.9

RUN pip install boto3 requests kubernetes

COPY app.py /var/task/

CMD ["app.handler"]
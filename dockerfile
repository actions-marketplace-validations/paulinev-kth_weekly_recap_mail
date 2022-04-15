FROM python:3.9-alpine

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt


CMD [ "python3", "-m" , "main"]
FROM python:3.10-slim

COPY requirements.txt .

RUN pip3 install keyrings.google-artifactregistry-auth==1.0.0
RUN pip3 install -r requirements.txt

COPY main.py .

ENTRYPOINT ["python", "main.py"]

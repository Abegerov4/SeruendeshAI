FROM python:3.13-slim
WORKDIR /tools
COPY infra/photos/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY infra/photos/manage.py ./
ENTRYPOINT ["python", "manage.py"]

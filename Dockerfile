FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 JOBHUNT_HOSTED=1 JOBHUNT_DATA=/data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
RUN rm -rf data config.yaml credentials.json .venv
VOLUME ["/data"]
EXPOSE 8080
CMD ["gunicorn", "-c", "gunicorn.conf.py", "wsgi:app"]

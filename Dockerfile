FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY requirements.lock ./
COPY peerlink ./peerlink
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
USER app
ENV PEERLINK_DB=/data/hub.db
EXPOSE 8000
CMD ["peerlink", "hub", "--host", "0.0.0.0"]

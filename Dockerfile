FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml ./
COPY psb_assistant ./psb_assistant
RUN pip install --no-cache-dir . && useradd --create-home app && mkdir -p data && chown app:app data
USER app
EXPOSE 8000
CMD ["python", "-m", "psb_assistant", "serve", "--host", "0.0.0.0"]

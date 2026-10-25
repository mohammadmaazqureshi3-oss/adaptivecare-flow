FROM python:3.12-slim
WORKDIR /app
COPY services/gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/gateway/gateway ./gateway
USER nobody
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "gateway.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

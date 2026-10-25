FROM python:3.12-slim
WORKDIR /app
COPY services/worklist/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/care-events /tmp/care-events
RUN pip install --no-cache-dir /tmp/care-events
COPY services/worklist/worklist ./worklist
USER nobody
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "worklist.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

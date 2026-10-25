FROM python:3.12-slim
WORKDIR /app
COPY services/designer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/pathway-core /tmp/pathway-core
RUN pip install --no-cache-dir /tmp/pathway-core
COPY services/designer/designer ./designer
USER nobody
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "designer.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim

WORKDIR /app

# Copy project files
COPY . .

# Install non-editable (regular wheel install) with sqlite extras for ONNX embedding fallback
RUN pip install --no-cache-dir ".[sqlite]"

# Cloud platforms set PORT; run_server.py reads MCP_HTTP_PORT
ENV MCP_HTTP_PORT=8000

EXPOSE 8000

CMD ["python", "run_server.py"]

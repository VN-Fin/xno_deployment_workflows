# Use the official Python image
FROM python:3.10-slim

# Build args — baked into the image at build time
ARG EXAMPLE_ARG_01=default_01
ARG EXAMPLE_ARG_02=default_02

# Persist build args as env vars so the app can read them at runtime
ENV EXAMPLE_ARG_01=${EXAMPLE_ARG_01}
ENV EXAMPLE_ARG_02=${EXAMPLE_ARG_02}

# Set the working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY . .

# Generate gRPC stubs from proto
RUN python -m grpc_tools.protoc \
    -I protos \
    --python_out=. \
    --grpc_python_out=. \
    protos/hello.proto

# Expose ports: 8000 (HTTP), 50051 (gRPC)
EXPOSE 8000 50051

# Default: run the HTTP API (override via entrypoint in docker-compose)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

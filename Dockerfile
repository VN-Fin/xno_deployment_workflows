# Use the official Python image
FROM python:3.10-slim

# --- NEW: Install networking diagnostic tools ---
# We combine these to keep the layer count down and clean up the cache to save space
RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    telnet \
    && rm -rf /var/lib/apt/lists/*

# Build args
ARG EXAMPLE_ARG_01=default_01
ARG EXAMPLE_ARG_02=default_02

# Persist build args
ENV EXAMPLE_ARG_01=${EXAMPLE_ARG_01}
ENV EXAMPLE_ARG_02=${EXAMPLE_ARG_02}

WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY . .

# Generate gRPC stubs
RUN python -m grpc_tools.protoc \
    -I protos \
    --python_out=. \
    --grpc_python_out=. \
    protos/hello01.proto \
    protos/hello02.proto

EXPOSE 8000 50051

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
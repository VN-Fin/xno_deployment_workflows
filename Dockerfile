# Use the official Python image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY . .

# Expose port
EXPOSE 8000

# Run the app
CMD ["uvicorn", "main.py"]

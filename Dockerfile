FROM python:3.10-slim

# Create working directory
WORKDIR /app

# Copy files
COPY . /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Start the bot
CMD ["python", "tel.py"]

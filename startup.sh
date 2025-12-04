#!/bin/bash
# Azure App Service startup script for FastAPI application

# Azure provides the PORT environment variable
# Default to 8000 if not set (for local testing)
PORT=${PORT:-8000}

# Start the application using uvicorn
# Use --host 0.0.0.0 to bind to all interfaces (required for Azure)
exec uvicorn app:app --host 0.0.0.0 --port $PORT --workers 2


FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pizzavision.py ./
COPY pizzavision/ pizzavision/

EXPOSE 8080
ENV PORT=8080

# Run Flask-SocketIO's built-in eventlet server (the documented prod path when
# not using gunicorn). pizzavision.py reads $PORT and calls socketio.run(),
# which detects eventlet and uses its wsgi.server -- production-grade.
CMD ["python", "pizzavision.py"]

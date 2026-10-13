FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8080
ENV ALLOW_DEMO_ATTESTATION=1
ENV PYTHONUNBUFFERED=1
ENV API_SIGNING_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "wsgi:application"]

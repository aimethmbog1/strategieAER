# Image de l'application pour un hébergement sur le Data Center de l'AER
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m aer && mkdir -p /app/data && chown -R aer /app
USER aer
EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "Home.py", "--server.port=8501", "--server.address=0.0.0.0", \
     "--server.enableXsrfProtection=true", "--browser.gatherUsageStats=false"]

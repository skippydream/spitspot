FROM python:3.11-slim

# Imposta variabili ambiente
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Installa dipendenze di sistema (Nginx, GDAL per GIS, ecc + librerie per numcodecs)
RUN apt-get update && apt-get install -y \
    nginx \
    binutils \
    libproj-dev \
    gdal-bin \
    libgdal-dev \
    python3-gdal \
    build-essential \
    libblosc-dev \
    libzstd-dev \
    liblz4-dev \
    libsnappy-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia i file dei requisiti e installa le dipendenze Python
COPY python/requirements.txt /app/python/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel cython

# Installazione di numcodecs forzando la compilazione e disabilitando estensioni CPU problematiche
# Usiamo --no-binary solo per numcodecs per velocizzare il build di numpy
RUN DISABLE_NUMCODECS_AVX2=1 DISABLE_NUMCODECS_SSE2=1 \
    pip install --no-cache-dir --no-binary numcodecs numcodecs==0.12.1

# Installa il resto dei requisiti
RUN pip install --no-cache-dir -r /app/python/requirements.txt
RUN pip install --no-cache-dir uwsgi

# Copia tutto il resto del codice
COPY . /app/

# Configura Nginx
RUN rm /etc/nginx/sites-enabled/default
COPY nginx_conf/default.conf /etc/nginx/sites-enabled/spitspot.conf

# Crea le cartelle per i file statici e media, e raccogli gli statici
RUN mkdir -p /app/static /app/media
# Nota: python manage.py collectstatic richiede che PRODUCTION=1 o simili siano settati se necessario
RUN cd python && python manage.py collectstatic --noinput --clear

# Espone la porta 80 (Koyeb mapperà questa porta all'esterno)
EXPOSE 80

# Script di avvio per far girare Nginx e uWSGI insieme
CMD service nginx start && uwsgi --ini uwsgi/uwsgi.ini

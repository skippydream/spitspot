FROM python:3.11-bullseye

# Imposta variabili ambiente
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Installa dipendenze di sistema (Nginx + GIS)
RUN apt-get update && apt-get install -y \
    nginx \
    binutils \
    libproj-dev \
    gdal-bin \
    libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia i file dei requisiti e installa le dipendenze Python
COPY python/requirements.txt /app/python/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Installazione di numcodecs: su Bullseye proviamo la versione standard prima
# Se fallisce con AVX2, lo disabilitiamo a runtime tramite variabile d'ambiente
RUN pip install --no-cache-dir -r /app/python/requirements.txt
RUN pip install --no-cache-dir uwsgi

# Copia tutto il resto del codice
COPY . /app/

# Configura Nginx
RUN rm /etc/nginx/sites-enabled/default
COPY nginx_conf/default.conf /etc/nginx/sites-enabled/spitspot.conf

# Crea le cartelle per i file statici e media, e raccogli gli statici
RUN mkdir -p /app/static /app/media
RUN cd python && python manage.py collectstatic --noinput --clear

# Espone la porta 80
EXPOSE 80

# Variabile d'ambiente per forzare numcodecs a non usare AVX2 se l'hardware non lo supporta
ENV DISABLE_NUMCODECS_AVX2=1
ENV DISABLE_NUMCODECS_SSE2=1

# Script di avvio: 1. Migrazioni 2. Nginx 3. uWSGI
CMD cd python && python manage.py migrate --noinput && service nginx start && uwsgi --ini /app/uwsgi/uwsgi.ini

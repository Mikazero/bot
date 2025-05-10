FROM python:3.11-slim

# Instalar Java y curl
RUN apt-get update && apt-get install -y \
    openjdk-17-jdk \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar los archivos del bot
COPY . .

# Instalar dependencias del bot
RUN pip install -r requirements.txt

# Crear directorio para Lavalink
WORKDIR /opt/Lavalink

# Descargar Lavalink
RUN curl -L https://github.com/lavalink-devs/Lavalink/releases/download/4.0.0/Lavalink.jar -o Lavalink.jar

# Crear el archivo de configuración
COPY application.yml .

# Exponer el puerto
EXPOSE 2333

# Volver al directorio del bot
WORKDIR /app

# Script de inicio
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Comando por defecto (será sobrescrito por Railway)
CMD ["/start.sh"]
FROM eclipse-temurin:17-jdk-alpine

WORKDIR /opt/Lavalink

RUN apk add --no-cache curl

# Descargar Lavalink
RUN curl -L https://github.com/freyacodes/Lavalink/releases/download/4.0.0/Lavalink.jar -o Lavalink.jar

# Crear el archivo de configuración
COPY application.yml .

# Exponer el puerto
EXPOSE 2333

# Comando para ejecutar Lavalink
CMD ["java", "-jar", "Lavalink.jar"] 
#!/bin/bash

# Iniciar Lavalink en segundo plano
cd /opt/Lavalink
java -jar Lavalink.jar &
LAVALINK_PID=$!

# Esperar a que Lavalink inicie
echo "Esperando a que Lavalink inicie..."
sleep 15

# Verificar que Lavalink está corriendo y escuchando en el puerto
if ! ps -p $LAVALINK_PID > /dev/null; then
    echo "Error: Lavalink no pudo iniciar"
    exit 1
fi

# Verificar que el puerto está abierto
if ! netstat -tuln | grep -q ":2333"; then
    echo "Error: Lavalink no está escuchando en el puerto 2333"
    exit 1
fi

echo "Lavalink iniciado correctamente y escuchando en el puerto 2333"

# Iniciar el bot
cd /app
echo "Iniciando el bot..."
exec python3 main.py 
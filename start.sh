#!/bin/bash

# Iniciar Lavalink en segundo plano
cd /opt/Lavalink
java -jar Lavalink.jar &
LAVALINK_PID=$!

# Esperar a que Lavalink inicie
echo "Esperando a que Lavalink inicie..."
sleep 15

# Verificar que Lavalink está corriendo
if ! ps -p $LAVALINK_PID > /dev/null; then
    echo "Error: Lavalink no pudo iniciar"
    exit 1
fi

echo "Lavalink iniciado correctamente"

# Iniciar el bot
cd /app
echo "Iniciando el bot..."
exec python3 main.py 
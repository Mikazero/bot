#!/bin/bash

# Iniciar Lavalink en segundo plano, forzando IPv4 para Java y limitando memoria
cd /opt/Lavalink
java -Xms128m -Xmx256m -Djava.net.preferIPv4Stack=true -jar Lavalink.jar &
LAVALINK_PID=$!

# Esperar a que Lavalink inicie
echo "Esperando a que Lavalink inicie..."
sleep 30

# Verificar que Lavalink está corriendo
if ! ps -p $LAVALINK_PID > /dev/null; then
    echo "Error: Lavalink no pudo iniciar"
    exit 1
fi

# Verificar que el puerto está abierto
if ! netstat -tuln | grep -q ":2333"; then
    echo "Error: Lavalink no está escuchando en el puerto 2333"
    exit 1
fi

# Verificar que Lavalink está respondiendo
if ! curl -s http://localhost:2333/version > /dev/null; then
    echo "Error: Lavalink no está respondiendo en el puerto 2333"
    exit 1
fi

echo "Lavalink iniciado correctamente y escuchando en el puerto 2333"

# Iniciar el bot
cd /app
echo "Iniciando el bot..."
exec python3 main.py 
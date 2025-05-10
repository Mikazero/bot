#!/bin/bash

# Iniciar Lavalink en segundo plano
cd /opt/Lavalink
java -jar Lavalink.jar &

# Esperar a que Lavalink inicie
sleep 10

# Iniciar el bot
cd /app
python3 main.py 
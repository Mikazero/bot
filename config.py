import os
from dotenv import load_dotenv

load_dotenv()  # Cargar variables del archivo .env

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
MAL_TOKEN = os.getenv('MAL_TOKEN')
CUSTOM_SEARCH_API_KEY = os.getenv('CUSTOM_SEARCH_API_KEY')
CX = os.getenv('CX')

BOT_TOKEN = DISCORD_TOKEN
PREFIX = "g."

# Lavalink settings
LAVALINK_HOST = "localhost"
LAVALINK_PORT = 2333
LAVALINK_PASSWORD = "youshallnotpass"  # Contraseña por defecto de Lavalink
LAVALINK_URI = f"http://{LAVALINK_HOST}:{LAVALINK_PORT}"

EMBED_COLOR = 0x57F287

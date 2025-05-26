import os
from dotenv import load_dotenv

load_dotenv()  # Cargar variables del archivo .env (solo para desarrollo local)

# Variables principales del bot
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
MAL_TOKEN = os.getenv('MAL_TOKEN')
CUSTOM_SEARCH_API_KEY = os.getenv('CUSTOM_SEARCH_API_KEY')
CX = os.getenv('CX')

BOT_TOKEN = DISCORD_TOKEN
PREFIX = "g."

# Lavalink settings - ahora desde variables de entorno
LAVALINK_HOST = os.getenv('LAVALINK_HOST', 'localhost')
LAVALINK_PORT = int(os.getenv('LAVALINK_PORT', '2333'))
LAVALINK_PASSWORD = os.getenv('LAVALINK_PASSWORD', 'youshallnotpass')
LAVALINK_URI = f"http://{LAVALINK_HOST}:{LAVALINK_PORT}"

# Fixie Socks Proxy para IP estática en Heroku
FIXIE_SOCKS_HOST = os.getenv('FIXIE_SOCKS_HOST')

EMBED_COLOR = 0x57F287

import discord
from discord.ext import commands
from discord import app_commands
import wavelink
import os
import threading
from flask import Flask

# Configuración del servidor Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot de música funcionando!"

def run_flask_app():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='g.', intents=intents)

# ---------- EVENTOS GLOBALES ----------
@bot.event
async def on_ready():
    print(f'Bot de Música conectado como {bot.user}')

@bot.event
async def on_error(event, *args, **kwargs):
    with open('error.log', 'a') as f:
        f.write(f'Ocurrió un error en el evento {event}: {args}\n')

# Puedes agregar aquí otros eventos globales si quieres (on_disconnect, etc.)

# --------- SETUP PARA COMANDOS SLASH ----------
@bot.event
async def setup_hook():
    # Cargar cogs del bot de música
    await bot.load_extension('cogs.search')
    await bot.load_extension('cogs.music')
    await bot.load_extension('cogs.moderation')
    await bot.load_extension('cogs.buckshot')
    # NO cargar cogs.minecraft aquí

    try:
        synced = await bot.tree.sync()
        print(f"Sincronizados {len(synced)} comandos de aplicación (Música).")
    except Exception as e:
        print(f"Error al sincronizar comandos de aplicación (Música): {e}")

# --------- ARRANQUE DEL BOT ----------
if __name__ == '__main__':
    # Iniciar Flask en un hilo separado
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()
    
    bot.run(os.environ.get("DISCORD_TOKEN"))
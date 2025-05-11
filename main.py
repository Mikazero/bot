import discord
from discord.ext import commands
from discord import app_commands
import wavelink
import config


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='g.', intents=intents)

# ---------- EVENTOS GLOBALES ----------
@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user}')

@bot.event
async def on_error(event, *args, **kwargs):
    with open('error.log', 'a') as f:
        f.write(f'Ocurrió un error en el evento {event}: {args}\n')

# Puedes agregar aquí otros eventos globales si quieres (on_disconnect, etc.)

# --------- SETUP PARA COMANDOS SLASH ----------
@bot.event
async def setup_hook():
    # Carga tu cog de búsquedas (agrega más cogs aquí según los vayas creando)
    await bot.load_extension('cogs.search')
    await bot.load_extension('cogs.music')
    await bot.load_extension('cogs.moderation')
    # Recuerda: el nombre es el "path" relativo: carpeta + nombre archivo (sin .py)

    # Sincroniza los comandos de la aplicación (slash commands)
    try:
        synced = await bot.tree.sync()
        print(f"Sincronizados {len(synced)} comandos de aplicación.")
    except Exception as e:
        print(f"Error al sincronizar comandos de aplicación: {e}")

# --------- ARRANQUE DEL BOT ----------
if __name__ == '__main__':
    bot.run(config.DISCORD_TOKEN)
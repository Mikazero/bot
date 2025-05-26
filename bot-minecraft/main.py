import discord
from discord.ext import commands
from discord import app_commands
import os


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='g.', intents=intents)

# ---------- EVENTOS GLOBALES ----------
@bot.event
async def on_ready():
    print(f'Bot de Minecraft conectado como {bot.user}')

@bot.event
async def on_error(event, *args, **kwargs):
    with open('error_minecraft.log', 'a') as f:
        f.write(f'[MinecraftBot] Error en evento {event}: {args}\n')

# Puedes agregar aquí otros eventos globales si quieres (on_disconnect, etc.)

# --------- SETUP PARA COMANDOS SLASH ----------
@bot.event
async def setup_hook():
    # Cargar solo el cog de Minecraft
    await bot.load_extension('cogs.minecraft')

    try:
        synced = await bot.tree.sync()
        print(f"Sincronizados {len(synced)} comandos de aplicación (Minecraft).")
    except Exception as e:
        print(f"Error al sincronizar comandos de aplicación (Minecraft): {e}")

# --------- ARRANQUE DEL BOT ----------
if __name__ == '__main__':
    bot.run(os.environ.get("DISCORD_TOKEN_MINECRAFT", os.environ.get("DISCORD_TOKEN")))
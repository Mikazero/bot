import discord
from discord.ext import commands
from discord import app_commands
import os


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='m.', intents=intents)

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
    print("[MinecraftBot] Iniciando setup_hook...")
    try:
        print("[MinecraftBot] Intentando cargar cogs.minecraft...")
        await bot.load_extension('cogs.minecraft')
        print("[MinecraftBot] cogs.minecraft cargado exitosamente.")
    except Exception as e:
        print(f"[MinecraftBot] Error al cargar cogs.minecraft: {e}")
        # Aquí podrías querer propagar el error o manejarlo de otra forma si es crítico
        # return # Descomentar si quieres detener la sincronización en caso de error de carga de cog

    try:
        print("[MinecraftBot] Intentando sincronizar comandos de aplicación...")
        synced = await bot.tree.sync()
        print(f"[MinecraftBot] Sincronizados {len(synced)} comandos de aplicación (Minecraft).")
        if not synced:
            print("[MinecraftBot] ADVERTENCIA: No se sincronizó ningún comando. Revisa el cog y los comandos definidos.")
    except Exception as e:
        print(f"[MinecraftBot] Error al sincronizar comandos de aplicación (Minecraft): {e}")

# --------- ARRANQUE DEL BOT ----------
if __name__ == '__main__':
    minecraft_token = os.environ.get("DISCORD_TOKEN_MINECRAFT")
    if not minecraft_token:
        print("[MinecraftBot] ERROR CRÍTICO: La variable de entorno DISCORD_TOKEN_MINECRAFT no está definida.")
        # Considera salir del script si el token no está para evitar que intente correr sin identidad
        exit()
    print(f"[MinecraftBot] Iniciando con el token de Minecraft...")
    bot.run(minecraft_token)

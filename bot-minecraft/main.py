import discord
from discord.ext import commands
from discord import app_commands
import os
import logging


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
    logging.info("Intentando cargar la extensión 'cogs.minecraft'...")
    try:
        await bot.load_extension('cogs.minecraft')
        logging.info("Extensión 'cogs.minecraft' cargada exitosamente.")
    except Exception as e:
        logging.error(f"Error al cargar la extensión 'cogs.minecraft': {e}", exc_info=True)

    logging.info("Sincronizando comandos...")
    try:
        # Sincronizar comandos globales
        synced_commands = await bot.tree.sync()
        if synced_commands:
            logging.info(f"{len(synced_commands)} comandos globales sincronizados: {[command.name for command in synced_commands]}")
        else:
            logging.warning("No se sincronizaron comandos globales.")

        # Sincronizar comandos para guilds específicos si es necesario (ejemplo)
        # for guild_id in self.guild_ids: # Asegúrate de tener self.guild_ids definido si usas esto
        #     guild = discord.Object(id=guild_id)
        #     guild_synced_commands = await self.tree.sync(guild=guild)
        #     if guild_synced_commands:
        #         logging.info(f"{len(guild_synced_commands)} comandos sincronizados para guild {guild_id}: {[command.name for command in guild_synced_commands]}")
        #     else:
        #         logging.warning(f"No se sincronizaron comandos para guild {guild_id}.")

    except Exception as e:
        logging.error(f"Error al sincronizar comandos: {e}", exc_info=True)

# --------- ARRANQUE DEL BOT ----------
if __name__ == '__main__':
    minecraft_token = os.environ.get("DISCORD_TOKEN_MINECRAFT")
    if not minecraft_token:
        print("[MinecraftBot] ERROR CRÍTICO: La variable de entorno DISCORD_TOKEN_MINECRAFT no está definida.")
        # Considera salir del script si el token no está para evitar que intente correr sin identidad
        exit()
    print(f"[MinecraftBot] Iniciando con el token de Minecraft...")
    bot.run(minecraft_token)
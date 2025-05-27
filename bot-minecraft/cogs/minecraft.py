import discord
from discord.ext import commands, tasks
from discord import app_commands
from discord import Interaction
import asyncio
import os
from mcstatus import JavaServer
from mcrcon import MCRcon
import json
from datetime import datetime
import aiohttp
import re
import socks
import socket
import logging # Añadir logging
from typing import Union # <--- AÑADIR ESTA LÍNEA

logger = logging.getLogger(__name__) # Configurar un logger para el cog

class MinecraftCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.server_ip = os.environ.get("MC_SERVER_IP", "localhost")
        self.server_port = int(os.environ.get("MC_SERVER_PORT", "25565"))
        self.rcon_port = int(os.environ.get("MC_RCON_PORT", "25575"))
        self.rcon_password = os.environ.get("MC_RCON_PASSWORD", "")
        
        # MC_CHAT_CHANNEL_ID debe estar configurado en Heroku
        self.chat_channel_id = int(os.environ.get("MC_CHAT_CHANNEL_ID", "0"))
        if not self.chat_channel_id:
            logger.warning("MC_CHAT_CHANNEL_ID no está configurado. El puente de chat no funcionará correctamente hasta que se configure un canal.")
        
        # Configuración del proxy Fixie Socks
        self.fixie_socks_host = os.environ.get("FIXIE_SOCKS_HOST")
        self.proxy_config = self._parse_fixie_socks_url()
        
        # IDs para restricciones de acceso
        raw_guild_id = os.environ.get("MC_ALLOWED_GUILD_ID")
        raw_channel_id = os.environ.get("MC_ALLOWED_CHANNEL_ID")
        raw_user_id = os.environ.get("MC_ALLOWED_USER_ID")

        self.allowed_guild_id = int(raw_guild_id) if raw_guild_id else None
        self.allowed_channel_id = int(raw_channel_id) if raw_channel_id else None
        self.allowed_user_id = int(raw_user_id) if raw_user_id else None

        logger.info(f"[MinecraftCog] Restricciones de acceso cargadas:")
        logger.info(f"  - Servidor permitido: {self.allowed_guild_id if self.allowed_guild_id else 'Cualquiera'}")
        logger.info(f"  - Canal permitido: {self.allowed_channel_id if self.allowed_channel_id else 'Cualquiera'}")
        logger.info(f"  - Usuario permitido: {self.allowed_user_id if self.allowed_user_id else 'Cualquiera'}")

        # Patrones regex para el chat (ajustados para unificar)
        self.log_patterns = [
            re.compile(r'\\[\\d{2}:\\d{2}:\\d{2}\\] \\[Server thread/INFO\\]: <(\\w+)> (.+)'),  # Chat
            re.compile(r'\\[\\d{2}:\\d{2}:\\d{2}\\] \\[Server thread/INFO\\]: (\\w+) joined the game'),  # Join
            re.compile(r'\\[\\d{2}:\\d{2}:\\d{2}\\] \\[Server thread/INFO\\]: (\\w+) left the game'),  # Leave
            # Podrías añadir más patrones aquí (muertes, logros, etc.)
            # Ejemplo de patrón de muerte (genérico, puede necesitar ajustes)
            re.compile(r'\\[\\d{2}:\\d{2}:\\d{2}\\] \\[Server thread/INFO\\]: (\\w+ (?:was slain by|drowned|fell|etc\\.).*)') # Muerte
        ]
        
        # Nuevas variables para el API de logs remotos
        self.mc_log_api_url = os.environ.get("MC_LOG_API_URL")
        self.mc_log_api_token = os.environ.get("MC_LOG_API_TOKEN")
        
        if not self.mc_log_api_url or not self.mc_log_api_token:
            logger.warning("MC_LOG_API_URL o MC_LOG_API_TOKEN no están configurados. El polling de logs remotos (puente de chat) no funcionará.")
        else:
            logger.info(f"🔗 Configuración del API de logs: URL={self.mc_log_api_url}, Token={'*' * len(self.mc_log_api_token) if self.mc_log_api_token else 'No establecido'}")

        self.aiohttp_session = None # Se inicializará en cog_load o before_loop
        self.processed_log_timestamps = set() # Para evitar procesar la misma línea múltiples veces en la misma sesión del bot
        self.chat_bridge_active = False # Estado del chat bridge
        
        # La tarea self._remote_log_polling_loop será definida por el decorador @tasks.loop
        # No es necesario definirla explícitamente aquí si el cog carga correctamente.

    def _parse_fixie_socks_url(self):
        """Parsea la URL de Fixie Socks para extraer las credenciales del proxy"""
        if not self.fixie_socks_host:
            return None
        
        try:
            # Formato: user:password@host:port
            match = re.match(r'([^:]+):([^@]+)@([^:]+):(\d+)', self.fixie_socks_host)
            if match:
                return {
                    'username': match.group(1),
                    'password': match.group(2),
                    'host': match.group(3),
                    'port': int(match.group(4))
                }
            else:
                logger.error(f"❌ Formato de Fixie Socks URL no reconocido: {self.fixie_socks_host}")
                return None
        except Exception as e:
            logger.error(f"❌ Error parseando Fixie Socks URL: {e}")
            return None
    
    def _setup_proxy(self):
        """Configura el proxy SOCKSv5 para las conexiones"""
        if self.proxy_config:
            socks.set_default_proxy(
                socks.SOCKS5,
                self.proxy_config['host'],
                self.proxy_config['port'],
                username=self.proxy_config['username'],
                password=self.proxy_config['password']
            )
            socket.socket = socks.socksocket
            logger.info(f"🌐 Proxy SOCKSv5 configurado: {self.proxy_config['host']}:{self.proxy_config['port']}")
            return True
        return False
    
    def _reset_proxy(self):
        """Resetea la configuración del proxy"""
        if self.proxy_config:
            socket.socket = socket._realsocket if hasattr(socket, '_realsocket') else socket.socket
            
    async def process_log_line(self, line: str, timestamp_str: str = None):
        """Procesa una línea individual del log.
        El timestamp_str es opcional, si el API lo provee por separado.
        """
        # Usar self.chat_channel_id en lugar de self.chat_channel_id_config
        channel = self.bot.get_channel(self.chat_channel_id)
        if not channel:
            logger.error(f"Error: Canal de chat con ID {self.chat_channel_id} no encontrado.")
            return

        # Para evitar duplicados dentro de una misma ejecución del bot si el API enviara la misma línea varias veces
        # (aunque el API actual no debería hacerlo si funciona como se espera)
        log_identifier = f"{timestamp_str}-{line}" if timestamp_str else line
        if log_identifier in self.processed_log_timestamps:
            return # Ya procesada en esta sesión
        
        # Añadir a procesados (podríamos limitar el tamaño de este set si es necesario)
        self.processed_log_timestamps.add(log_identifier)
        if len(self.processed_log_timestamps) > 1000: # Limpiar el set periódicamente para evitar uso excesivo de memoria
            self.processed_log_timestamps.pop()


        # Normalizar tiempo si no viene en la línea (ej. si el API lo da por separado)
        current_time_for_embed = datetime.now()

        # Chat de jugador
        # Ajuste: El patrón original ya captura el tiempo del log de Minecraft.
        # r'\\[(\\d{2}:\\d{2}:\\d{2})\\] \\[Server thread/INFO\\]: <(\\w+)> (.+)'
        match = self.log_patterns[0].match(line)
        if match:
            # log_time, player, message = match.groups() # log_time ya está en el formato HH:MM:SS
            player, message = match.groups()[1], match.groups()[2] # El primer grupo es el timestamp
            embed = discord.Embed(
                description=f"💬 **{player}**: {message}",
                color=discord.Color.blue(),
                timestamp=current_time_for_embed # Usar tiempo actual para el embed
            )
            await channel.send(embed=embed)
            return

        # Jugador se une
        # r'\\[(\\d{2}:\\d{2}:\\d{2})\\] \\[Server thread/INFO\\]: (\\w+) joined the game'
        match = self.log_patterns[1].match(line)
        if match:
            # log_time, player = match.groups()
            player = match.groups()[1]
            embed = discord.Embed(
                description=f"✅ **{player}** se unió al servidor.",
                color=discord.Color.green(),
                timestamp=current_time_for_embed
            )
            await channel.send(embed=embed)
            return

        # Jugador se va
        # r'\\[(\\d{2}:\\d{2}:\\d{2})\\] \\[Server thread/INFO\\]: (\\w+) left the game'
        match = self.log_patterns[2].match(line)
        if match:
            # log_time, player = match.groups()
            player = match.groups()[1]
            embed = discord.Embed(
                description=f"❌ **{player}** salió del servidor.",
                color=discord.Color.red(),
                timestamp=current_time_for_embed
            )
            await channel.send(embed=embed)
            return
        
        # Mensajes de muerte (ejemplo básico)
        # r'\\[(\\d{2}:\\d{2}:\\d{2})\\] \\[Server thread/INFO\\]: (\\w+ .*)\'
        # Este patrón de muerte es muy genérico y puede necesitar ser más específico
        # o tener varios patrones de muerte.
        match = self.log_patterns[3].match(line)
        if match:
            # log_time, death_message = match.groups()
            death_message = match.groups()[1]
            embed = discord.Embed(
                description=f"💀 {death_message}",
                color=discord.Color.dark_grey(),
                timestamp=current_time_for_embed
            )
            await channel.send(embed=embed)
            return

        # Si no coincide con nada conocido, no lo enviamos para evitar spam.
        # logger.info(f"Línea no procesada: {line}")

    async def get_server_status(self):
        """Obtiene el estado del servidor de Minecraft"""
        proxy_used = False
        try:
            # Configurar proxy si está disponible
            proxy_used = self._setup_proxy()
            
            server = JavaServer.lookup(f"{self.server_ip}:{self.server_port}")
            status = await asyncio.to_thread(server.status)
            return status
        except Exception as e:
            print(f"Error al obtener estado del servidor: {e}")
            return None
        finally:
            # Resetear proxy
            if proxy_used:
                self._reset_proxy()
    
    async def execute_rcon_command(self, command):
        """Ejecuta un comando RCON en el servidor"""
        if not self.rcon_password:
            return "❌ RCON no configurado (falta contraseña)"
        
        proxy_used = False
        try:
            # Configurar proxy si está disponible
            proxy_used = self._setup_proxy()
            
            # Función bloqueante para ejecutar en un hilo separado
            def rcon_blocking_call():
                # MCRcon necesita ser instanciado dentro de la función que corre en el hilo
                with MCRcon(self.server_ip, self.rcon_password, port=self.rcon_port) as mcr:
                    return mcr.command(command)
            
            response = await asyncio.to_thread(rcon_blocking_call)
            return response
        except Exception as e:
            # Imprimir el traceback completo para mejor depuración en el servidor
            import traceback
            print(f"❌ Error detallado ejecutando comando RCON '{command}':")
            traceback.print_exc()
            return f"❌ Error ejecutando comando: {str(e)}"
        finally:
            # Resetear proxy
            if proxy_used:
                self._reset_proxy()

    @app_commands.command(name="mcstatus", description="Muestra el estado del servidor de Minecraft")
    async def minecraft_status(self, interaction: Interaction):
        """Comando para ver el estado del servidor"""
        await interaction.response.defer()
        
        status = await self.get_server_status()
        
        if status is None:
            embed = discord.Embed(
                title="🔴 Servidor Offline",
                description=f"No se pudo conectar al servidor `{self.server_ip}:{self.server_port}`",
                color=discord.Color.red()
            )
        else:
            # Crear embed con información del servidor
            embed = discord.Embed(
                title="🟢 Servidor Online",
                description=f"**{self.server_ip}:{self.server_port}**",
                color=discord.Color.green()
            )
            
            embed.add_field(
                name="👥 Jugadores",
                value=f"{status.players.online}/{status.players.max}",
                inline=True
            )
            
            embed.add_field(
                name="📊 Latencia",
                value=f"{status.latency:.1f}ms",
                inline=True
            )
            
            embed.add_field(
                name="🎮 Versión",
                value=status.version.name,
                inline=True
            )
            
            # Lista de jugadores online
            if status.players.online > 0 and status.players.sample:
                players_list = [player.name for player in status.players.sample]
                if len(players_list) > 10:
                    players_text = ", ".join(players_list[:10]) + f" y {len(players_list) - 10} más..."
                else:
                    players_text = ", ".join(players_list)
                
                embed.add_field(
                    name="🎯 Jugadores Online",
                    value=f"```{players_text}```",
                    inline=False
                )
            
            # Agregar información del proxy si está configurado
            if self.proxy_config:
                embed.add_field(
                    name="🌐 Conexión",
                    value="✅ A través de IP estática (Fixie Socks)",
                    inline=True
                )
            
            embed.timestamp = datetime.now()
        
        await interaction.followup.send(embed=embed)

    @commands.command(name="mcstatus", help="Muestra el estado del servidor de Minecraft. Uso: m.mcstatus")
    async def text_minecraft_status(self, ctx: commands.Context):
        """Comando de texto para ver el estado del servidor"""
        # Podrías enviar un mensaje de "cargando" aquí si lo deseas
        # await ctx.send("Consultando estado del servidor...")
        
        status = await self.get_server_status() # get_server_status ya usa to_thread
        
        if status is None:
            embed = discord.Embed(
                title="🔴 Servidor Offline",
                description=f"No se pudo conectar al servidor `{self.server_ip}:{self.server_port}`",
                color=discord.Color.red()
            )
        else:
            embed = discord.Embed(
                title="🟢 Servidor Online",
                description=f"**{self.server_ip}:{self.server_port}**",
                color=discord.Color.green()
            )
            embed.add_field(name="👥 Jugadores", value=f"{status.players.online}/{status.players.max}", inline=True)
            embed.add_field(name="📊 Latencia", value=f"{status.latency:.1f}ms", inline=True)
            embed.add_field(name="🎮 Versión", value=status.version.name, inline=True)
            if status.players.online > 0 and status.players.sample:
                players_list = [player.name for player in status.players.sample]
                if len(players_list) > 10:
                    players_text = ", ".join(players_list[:10]) + f" y {len(players_list) - 10} más..."
                else:
                    players_text = ", ".join(players_list)
                embed.add_field(name="🎯 Jugadores Online", value=f"```{players_text}```", inline=False)
            if self.proxy_config:
                embed.add_field(name="🌐 Conexión", value="✅ A través de IP estática (Fixie Socks)", inline=True)
            embed.timestamp = datetime.now()
        
        await ctx.send(embed=embed)

    @app_commands.command(name="mccommand", description="Ejecuta un comando en el servidor de Minecraft")
    @app_commands.describe(command="El comando a ejecutar (sin el /)")
    async def minecraft_command(self, interaction: Interaction, command: str):
        """Ejecuta un comando RCON en el servidor"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden ejecutar comandos del servidor.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # Ejecutar comando directamente con await
        result = await self.execute_rcon_command(command)
        
        embed = discord.Embed(
            title="🎮 Comando Ejecutado",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="📝 Comando",
            value=f"```/{command}```",
            inline=False
        )
        
        embed.add_field(
            name="📤 Resultado",
            value=f"```{result[:1000]}```",  # Limitar a 1000 caracteres
            inline=False
        )
        
        if self.proxy_config:
            embed.add_field(
                name="🌐 Conexión",
                value="✅ A través de IP estática",
                inline=True
            )
        
        embed.timestamp = datetime.now()
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="mcplayers", description="Lista todos los jugadores online")
    async def minecraft_players(self, interaction: Interaction):
        """Muestra una lista detallada de jugadores online"""
        await interaction.response.defer()
        
        status = await self.get_server_status()
        
        if status is None:
            embed = discord.Embed(
                title="❌ Error",
                description="No se pudo conectar al servidor",
                color=discord.Color.red()
            )
        elif status.players.online == 0:
            embed = discord.Embed(
                title="😴 Servidor Vacío",
                description="No hay jugadores online en este momento",
                color=discord.Color.orange()
            )
        else:
            embed = discord.Embed(
                title=f"👥 Jugadores Online ({status.players.online}/{status.players.max})",
                color=discord.Color.green()
            )
            
            if status.players.sample:
                players_text = "\n".join([f"• {player.name}" for player in status.players.sample])
                embed.description = f"```\n{players_text}\n```"
            else:
                embed.description = "Lista de jugadores no disponible"
        
        await interaction.followup.send(embed=embed)

    @commands.command(name="mcplayers", help="Lista todos los jugadores online. Uso: m.mcplayers")
    async def text_minecraft_players(self, ctx: commands.Context):
        """Muestra una lista detallada de jugadores online (versión texto)"""
        status = await self.get_server_status()
        if status is None:
            embed = discord.Embed(title="❌ Error", description="No se pudo conectar al servidor", color=discord.Color.red())
        elif status.players.online == 0:
            embed = discord.Embed(title="😴 Servidor Vacío", description="No hay jugadores online en este momento", color=discord.Color.orange())
        else:
            embed = discord.Embed(title=f"👥 Jugadores Online ({status.players.online}/{status.players.max})", color=discord.Color.green())
            if status.players.sample:
                players_text = "\n".join([f"• {player.name}" for player in status.players.sample])
                embed.description = f"```\n{players_text}\n```"
            else:
                embed.description = "Lista de jugadores no disponible"
        await ctx.send(embed=embed)

    @app_commands.command(name="mcwhitelist", description="Gestiona la whitelist del servidor")
    @app_commands.describe(
        action="Acción a realizar",
        player="Nombre del jugador"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Agregar", value="add"),
        app_commands.Choice(name="Remover", value="remove"),
        app_commands.Choice(name="Listar", value="list"),
        app_commands.Choice(name="Activar", value="on"),
        app_commands.Choice(name="Desactivar", value="off")
    ])
    async def minecraft_whitelist(self, interaction: Interaction, action: str, player: str = None):
        """Gestiona la whitelist del servidor"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden gestionar la whitelist.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        if action in ["add", "remove"] and not player:
            await interaction.followup.send("❌ Debes especificar un nombre de jugador para esta acción.")
            return
        
        # Construir comando
        if action == "list":
            command = "whitelist list"
        elif action in ["on", "off"]:
            command = f"whitelist {action}"
        else:
            command = f"whitelist {action} {player}"
        
        # Ejecutar comando directamente con await
        result = await self.execute_rcon_command(command)
        
        embed = discord.Embed(
            title="📋 Gestión de Whitelist",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="🔧 Acción",
            value=f"```{command}```",
            inline=False
        )
        
        embed.add_field(
            name="📤 Resultado",
            value=f"```{result}```",
            inline=False
        )
        
        await interaction.followup.send(embed=embed)

    @commands.command(name="mcwhitelist", help="Gestiona la whitelist. Uso: m.mcwhitelist <add|remove|list|on|off> [jugador]")
    async def text_minecraft_whitelist(self, ctx: commands.Context, action: str, *, player: str = None):
        """Gestiona la whitelist del servidor (versión texto)"""
        action = action.lower()
        valid_actions = ["add", "remove", "list", "on", "off"]
        if action not in valid_actions:
            await ctx.send(f"❌ Acción inválida. Acciones válidas: {', '.join(valid_actions)}")
            return

        if action in ["add", "remove"] and not player:
            await ctx.send("❌ Debes especificar un nombre de jugador para esta acción (`add` o `remove`).")
            return
        
        if action == "list":
            command = "whitelist list"
        elif action in ["on", "off"]:
            command = f"whitelist {action}"
        else: # add o remove
            command = f"whitelist {action} {player}"
        
        result = await self.execute_rcon_command(command)
        embed = discord.Embed(title="📋 Gestión de Whitelist", color=discord.Color.blue())
        embed.add_field(name="🔧 Acción", value=f"```{command}```", inline=False)
        embed.add_field(name="📤 Resultado", value=f"```{result}```", inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name="mckick", description="Expulsa a un jugador del servidor")
    @app_commands.describe(
        player="Nombre del jugador a expulsar",
        reason="Razón de la expulsión (opcional)"
    )
    async def minecraft_kick(self, interaction: Interaction, player: str, reason: str = "Expulsado por un administrador"):
        """Expulsa a un jugador del servidor"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden expulsar jugadores.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        command = f"kick {player} {reason}"
        # Ejecutar comando directamente con await
        result = await self.execute_rcon_command(command)
        
        embed = discord.Embed(
            title="👢 Jugador Expulsado",
            color=discord.Color.orange()
        )
        
        embed.add_field(name="👤 Jugador", value=player, inline=True)
        embed.add_field(name="📝 Razón", value=reason, inline=True)
        embed.add_field(name="📤 Resultado", value=f"```{result}```", inline=False)
        
        await interaction.followup.send(embed=embed)

    @commands.command(name="mckick", help="Expulsa a un jugador. Uso: m.mckick <jugador> [razón]")
    async def text_minecraft_kick(self, ctx: commands.Context, player: str, *, reason: str = "Expulsado por un administrador"):
        """Expulsa a un jugador del servidor (versión texto)"""
        if not player:
            await ctx.send("❌ Debes especificar el nombre del jugador a expulsar.")
            return

        command = f"kick {player} {reason}"
        result = await self.execute_rcon_command(command)
        embed = discord.Embed(title="👢 Jugador Expulsado", color=discord.Color.orange())
        embed.add_field(name="👤 Jugador", value=player, inline=True)
        embed.add_field(name="📝 Razón", value=reason, inline=True)
        embed.add_field(name="📤 Resultado", value=f"```{result}```", inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name="mcchat", description="Configura el puente de chat entre Minecraft y Discord")
    @app_commands.describe(
        action="Acción a realizar",
        channel="Canal de Discord para el chat (opcional, para set_channel)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Activar", value="enable"),
        app_commands.Choice(name="Desactivar", value="disable"),
        app_commands.Choice(name="Estado", value="status"),
        app_commands.Choice(name="Configurar Canal", value="set_channel")
    ])
    async def minecraft_chat_bridge(self, interaction: Interaction, action: str, channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)

        if action == "enable":
            if not self.chat_channel_id:
                await interaction.followup.send("❌ El canal de chat no está configurado. Usa la acción `set_channel` o define `MC_CHAT_CHANNEL_ID` en las variables de entorno y reinicia el bot.", ephemeral=True)
                return
            if not self.mc_log_api_url or not self.mc_log_api_token:
                await interaction.followup.send("❌ La URL o el token del API de logs no están configurados en las variables de entorno. No se puede activar el puente de chat.", ephemeral=True)
                return
            
            target_channel = self.bot.get_channel(self.chat_channel_id)
            if not target_channel:
                await interaction.followup.send(f"❌ No se pudo encontrar el canal de chat configurado (ID: {self.chat_channel_id}). Verifica el ID y los permisos del bot.", ephemeral=True)
                return

            if not self._remote_log_polling_loop.is_running():
                try:
                    self.chat_bridge_active = True
                    self._remote_log_polling_loop.start()
                    logger.info(f"Tarea _remote_log_polling_loop iniciada por comando /mcchat enable.")
                    await interaction.followup.send(f"✅ Puente de chat activado. Mensajes del juego se enviarán a {target_channel.mention}.")
                except RuntimeError as e:
                    logger.error(f"Error al intentar iniciar _remote_log_polling_loop: {e}")
                    await interaction.followup.send(f"⚠️ No se pudo iniciar la tarea de polling de logs en este momento: {e}. Intenta de nuevo en unos segundos.")
            else:
                self.chat_bridge_active = True 
                await interaction.followup.send(f"ℹ️ El puente de chat ya está activo y enviando mensajes a {target_channel.mention}.")

        elif action == "disable":
            self.chat_bridge_active = False 
            if self._remote_log_polling_loop.is_running():
                self._remote_log_polling_loop.cancel()
                logger.info(f"Tarea _remote_log_polling_loop detenida por comando /mcchat disable.")
                await interaction.followup.send("✅ Puente de chat desactivado. El sondeo de logs se ha detenido.")
            else:
                await interaction.followup.send("ℹ️ El puente de chat ya estaba inactivo.")

        elif action == "status":
            status_msg = "ℹ️ **Estado del Puente de Chat Minecraft**:\n"
            target_channel = self.bot.get_channel(self.chat_channel_id) if self.chat_channel_id else None
            
            api_configured = bool(self.mc_log_api_url and self.mc_log_api_token)
            status_msg += f"- Estado General: {'Activado ✅' if self.chat_bridge_active else 'Desactivado ❌'}\n"
            if api_configured:
                status_msg += f"- Tarea de polling: {'Activa ✅' if self._remote_log_polling_loop.is_running() and self.chat_bridge_active else 'Inactiva ❌'}\n"
            else:
                status_msg += "- Tarea de polling: Inactiva ❌ (API no configurada)\n"
            status_msg += f"- Canal de Discord: {target_channel.mention if target_channel else 'No configurado'}\n"
            status_msg += f"  (ID: {self.chat_channel_id if self.chat_channel_id else 'N/A'})\n"
            status_msg += f"- API de Logs Remotos: {'Configurada ✅' if api_configured else 'No configurada ❌ (revisa `MC_LOG_API_URL` y `MC_LOG_API_TOKEN`)'}"
            await interaction.followup.send(status_msg, ephemeral=True)

        elif action == "set_channel":
            if channel:
                self.chat_channel_id = channel.id
                # Nota: Este cambio es solo en tiempo de ejecución.
                # Para persistencia, se debe actualizar la variable de entorno MC_CHAT_CHANNEL_ID y reiniciar,
                # o implementar un sistema de configuración persistente.
                logger.info(f"Canal de chat para Minecraft bridge configurado a {channel.name} (ID: {channel.id}) mediante comando.")
                await interaction.followup.send(f"✅ Canal para el puente de chat configurado a {channel.mention}. Este cambio es temporal (solo para esta sesión del bot).", ephemeral=True)
            else:
                await interaction.followup.send("❌ Debes especificar un canal para esta acción.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Acción desconocida.", ephemeral=True)

    @commands.command(name="mcchat", help="Configura el chat bridge. Uso: m.mcchat <enable|disable|status|set_channel> [#canal]")
    async def text_minecraft_chat_bridge(self, ctx: commands.Context, action: str, channel: discord.TextChannel = None):
        action = action.lower()

        if action == "enable":
            if not self.chat_channel_id:
                await ctx.send("❌ El canal de chat no está configurado. Usa `set_channel` o define `MC_CHAT_CHANNEL_ID` en las variables de entorno y reinicia el bot.")
                return
            if not self.mc_log_api_url or not self.mc_log_api_token:
                await ctx.send("❌ La URL o el token del API de logs no están configurados en las variables de entorno. No se puede activar el puente de chat.")
                return

            target_channel = self.bot.get_channel(self.chat_channel_id)
            if not target_channel:
                await ctx.send(f"❌ No se pudo encontrar el canal de chat configurado (ID: {self.chat_channel_id}). Verifica el ID y los permisos del bot.")
                return

            if not self._remote_log_polling_loop.is_running():
                try:
                    if not self.aiohttp_session or self.aiohttp_session.closed:
                        self.aiohttp_session = aiohttp.ClientSession()
                    self.chat_bridge_active = True
                    self._remote_log_polling_loop.start()
                    logger.info(f"Tarea _remote_log_polling_loop iniciada por comando m.mcchat enable.")
                    await ctx.send(f"✅ Puente de chat activado. Mensajes a {target_channel.mention}.")
                except RuntimeError as e:
                    logger.error(f"Error al iniciar _remote_log_polling_loop (texto): {e}")
                    await ctx.send(f"⚠️ No se pudo iniciar la tarea: {e}.")
            else:
                self.chat_bridge_active = True
                await ctx.send(f"ℹ️ El puente de chat ya está activo ({target_channel.mention}).")

        elif action == "disable":
            self.chat_bridge_active = False
            if self._remote_log_polling_loop.is_running():
                self._remote_log_polling_loop.cancel()
                logger.info(f"Tarea _remote_log_polling_loop detenida por comando m.mcchat disable.")
                await ctx.send("✅ Puente de chat desactivado.")
            else:
                await ctx.send("ℹ️ El puente de chat ya está inactivo.")

        elif action == "status":
            status_msg = "ℹ️ **Estado del Puente de Chat Minecraft (Texto)**:\n"
            target_channel = self.bot.get_channel(self.chat_channel_id) if self.chat_channel_id else None
            api_configured = bool(self.mc_log_api_url and self.mc_log_api_token)
            status_msg += f"- Estado General: {'Activado ✅' if self.chat_bridge_active else 'Desactivado ❌'}\n"
            if api_configured:
                status_msg += f"- Tarea de polling: {'Activa ✅' if self._remote_log_polling_loop.is_running() and self.chat_bridge_active else 'Inactiva ❌'}\n"
            else:
                status_msg += "- Tarea de polling: Inactiva ❌ (API no configurada)\n"
            status_msg += f"- Canal Discord: {target_channel.mention if target_channel else 'No configurado'}\n"
            status_msg += f"- API Logs: {'Configurada ✅' if api_configured else 'No configurada ❌'}"
            await ctx.send(status_msg)

        elif action == "set_channel":
            if channel:
                self.chat_channel_id = channel.id
                logger.info(f"Canal de chat para Minecraft bridge configurado a {channel.name} (ID: {channel.id}) mediante comando m.mcchat.")
                await ctx.send(f"✅ Canal para el puente de chat configurado a {channel.mention}. Este cambio es temporal (solo para esta sesión del bot).")
            else:
                await ctx.send("❌ Debes especificar un canal para esta acción. Uso: `m.mcchat set_channel #nombre-canal`")
        else:
            await ctx.send(f"❌ Acción desconocida: `{action}`. Acciones válidas: enable, disable, status, set_channel.")

    @app_commands.command(name="mcsay", description="Envía un mensaje al chat del servidor de Minecraft")
    @app_commands.describe(message="Mensaje a enviar al servidor")
    async def minecraft_say(self, interaction: Interaction, message: str):
        await interaction.response.defer(ephemeral=True)
        if not self.rcon_password:
            await interaction.followup.send("❌ RCON no está configurado (falta contraseña). No se puede enviar el mensaje.", ephemeral=True)
            return

        response = await self.execute_rcon_command(f"say {message}")
        
        # MCRcon `say` command often returns empty on success or the message itself.
        # If execute_rcon_command returns its specific error string, we show that.
        if response is not None and response.startswith("❌ Error ejecutando comando:"):
            logger.warning(f"Error de RCON al intentar enviar '/say {message}': {response}")
            await interaction.followup.send(f"⚠️ Error al enviar mensaje al servidor: ```{response}```", ephemeral=True)
        elif response is None or response == "" or message in response: # Check for common success indicators
            logger.info(f"Mensaje '/say {message}' enviado a Minecraft vía RCON. Respuesta: '{response}'")
            await interaction.followup.send(f"✅ Mensaje enviado al servidor: `{message}`")
        else:
            # Unexpected response, show it for diagnostics
            logger.info(f"Respuesta inesperada de RCON para '/say {message}': '{response}'")
            await interaction.followup.send(f"ℹ️ Respuesta del servidor: ```{response}```", ephemeral=True)

    @commands.command(name="mcsay", help="Envía un mensaje al chat del servidor de Minecraft. Uso: m.mcsay <mensaje>")
    async def text_minecraft_say(self, ctx: commands.Context, *, message: str):
        if not self.rcon_password:
            await ctx.send("❌ RCON no está configurado (falta contraseña). No se puede enviar el mensaje.")
            return

        response = await self.execute_rcon_command(f"say {message}")

        if response is not None and response.startswith("❌ Error ejecutando comando:"):
            logger.warning(f"Error de RCON al intentar enviar '/say {message}' (comando de texto): {response}")
            await ctx.send(f"⚠️ Error al enviar mensaje al servidor: ```{response}```")
        elif response is None or response == "" or message in response: # Check for common success indicators
            logger.info(f"Mensaje '/say {message}' enviado a Minecraft vía RCON (comando de texto). Respuesta: '{response}'")
            await ctx.send(f"✅ Mensaje enviado al servidor: `{message}`")
        else:
            logger.info(f"Respuesta inesperada de RCON para '/say {message}' (comando de texto): '{response}'")
            await ctx.send(f"ℹ️ Respuesta del servidor: ```{response}```")
            
    def cog_unload(self):
        logger.info("Descargando MinecraftCog...")
        # Es importante verificar si el atributo existe antes de intentar usarlo,
        # especialmente si la carga del cog pudo haber fallado.
        if hasattr(self, '_remote_log_polling_loop') and self._remote_log_polling_loop.is_running():
            self._remote_log_polling_loop.cancel()
            logger.info("Tarea de polling de logs remotos cancelada.")
        
        if hasattr(self, 'aiohttp_session') and self.aiohttp_session and not self.aiohttp_session.closed:
            try:
                # En un cog_unload síncrono, no podemos hacer 'await'.
                # Creamos una tarea para que se ejecute en el loop.
                asyncio.create_task(self.aiohttp_session.close())
                logger.info("Cierre de sesión aiohttp programado.")
            except Exception as e:
                logger.error(f"Error al programar cierre de sesión aiohttp: {e}")
        else:
            logger.info("No se encontró sesión aiohttp activa para cerrar o ya estaba cerrada.")
        logger.info("MinecraftCog descargado.")

    # --- Funciones de Check Personalizadas ---
    def is_allowed_guild(self, ctx_or_interaction) -> bool:
        if not self.allowed_guild_id: return True # Si no está configurado, permitir todos
        guild_id = ctx_or_interaction.guild_id if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.guild.id
        return guild_id == self.allowed_guild_id

    def is_allowed_channel(self, ctx_or_interaction) -> bool:
        if not self.allowed_channel_id: return True
        channel_id = ctx_or_interaction.channel_id if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.channel.id
        return channel_id == self.allowed_channel_id

    def is_allowed_user(self, ctx_or_interaction) -> bool:
        if not self.allowed_user_id: return True
        user_id = ctx_or_interaction.user.id if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.id
        return user_id == self.allowed_user_id

    # --- Check Combinado para aplicar a comandos ---
    async def combined_access_check(self, ctx_or_interaction) -> bool:
        if not self.is_allowed_guild(ctx_or_interaction):
            # print(f"[DEBUG] Bloqueado: Guild ID {ctx_or_interaction.guild_id if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.guild.id} no permitido.")
            raise commands.CheckFailure("Este comando no está permitido en este servidor.")
        if not self.is_allowed_channel(ctx_or_interaction):
            # print(f"[DEBUG] Bloqueado: Channel ID {ctx_or_interaction.channel_id if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.channel.id} no permitido.")
            raise commands.CheckFailure("Este comando no está permitido en este canal.")
        if not self.is_allowed_user(ctx_or_interaction):
            # print(f"[DEBUG] Bloqueado: User ID {ctx_or_interaction.user.id if isinstance(ctx_or_interaction, discord.Interaction) else ctx_or_interaction.author.id} no permitido.")
            raise commands.CheckFailure("No tienes permiso para usar este comando.")
        return True

    async def cog_check(self, ctx_or_interaction: Union[Interaction, commands.Context]):
        # El argumento puede ser commands.Context o discord.Interaction
        # Necesitamos manejar ambos casos para obtener los IDs relevantes
        if isinstance(ctx_or_interaction, commands.Context): # Para comandos de texto
            return await self.combined_access_check(ctx_or_interaction)
        # Para interacciones (app_commands), discord.py maneja los checks de forma nativa
        # si se usa @app_commands.check decorator.
        # Este cog_check unificado es un poco más complejo para app_commands.
        # Si es una Interaction, el check ya se aplicó o es manejado por el decorador del comando.
        # Para mantener la lógica de combined_access_check para interacciones desde aquí:
        elif isinstance(ctx_or_interaction, Interaction): # Para comandos de aplicación
             return await self.combined_access_check(ctx_or_interaction)
        return False

    async def cog_command_error(self, ctx_or_interaction: Union[Interaction, commands.Context], error):
        # ctx_or_interaction puede ser Context o Interaction
        if isinstance(error, commands.CheckFailure):
            message = str(error) if str(error) else "No cumples con los requisitos para usar este comando aquí."
            if isinstance(ctx_or_interaction, Interaction): # <--- CAMBIAR AQUÍ
                # Si la interacción ya fue respondida (defer), usar followup
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(message, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(message, ephemeral=True)
            else:
                await ctx_or_interaction.send(message, ephemeral=True)

    @tasks.loop(seconds=5)
    async def _remote_log_polling_loop(self):
        if not self.chat_bridge_active:
            return

        if not self.mc_log_api_url or not self.mc_log_api_token:
            return

        if not self.aiohttp_session or self.aiohttp_session.closed:
            logger.warning("_remote_log_polling_loop: Sesión aiohttp no disponible o cerrada. Recreando...")
            try:
                self.aiohttp_session = aiohttp.ClientSession()
                logger.info("Sesión aiohttp recreada en polling task.")
            except Exception as e:
                logger.error(f"No se pudo recrear la sesión aiohttp en polling task: {e}. Saltando ciclo.")
                return
        
        # Volver a la cabecera de autenticación y endpoint originales esperados por el API modificado
        headers = {
            "Authorization": f"Bearer {self.mc_log_api_token}", 
            "User-Agent": "DiscordBot-MinecraftCog/1.0"
        }
        full_url = f"{self.mc_log_api_url.rstrip('/')}/get_new_logs" # REVERTIDO AQUÍ

        try:
            async with self.aiohttp_session.get(full_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    # El API (después de modificarlo) devolverá {"new_lines": [...]} 
                    new_lines = data.get("new_lines", []) # REVERTIDO AQUÍ de "lines" a "new_lines"
                    if new_lines:
                        for item in new_lines: 
                            # Asumimos que el API ahora envía solo la línea como string, 
                            # o si envía un dict, ajustamos process_log_line o el API
                            if isinstance(item, str):
                                await self.process_log_line(item)
                            elif isinstance(item, dict): # Si el API aún manda dicts
                                await self.process_log_line(item.get("line"), item.get("timestamp"))
                elif response.status == 401:
                    logger.error(f"Error 401 (No Autorizado) con el API de logs ({full_url}). Verifica MC_LOG_API_TOKEN. Desactivando bridge.")
                    self.chat_bridge_active = False
                elif response.status == 403:
                    logger.error(f"Error 403 (Prohibido) con el API de logs ({full_url}). Token inválido o sin permisos. Desactivando bridge.")
                    self.chat_bridge_active = False
                elif response.status == 404:
                    logger.error(f"Error 404 (No Encontrado) con el API de logs: {full_url}. Verifica el endpoint en el API y en el bot.")
                else:
                    error_text = await response.text()
                    logger.error(f"Error al contactar el API de logs ({full_url}): {response.status} - {error_text[:200]}")
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Error de conexión al API de logs: {e}. URL: {full_url}")
        except asyncio.TimeoutError:
            logger.warning(f"Timeout al conectar con el API de logs en {full_url}.")
        except json.JSONDecodeError:
            raw_text = await response.text()
            logger.error(f"Error al decodificar JSON del API de logs ({full_url}). Respuesta: {raw_text[:200]}")
        except Exception as e:
            logger.error(f"Excepción inesperada en _remote_log_polling_loop: {e.__class__.__name__} - {e}", exc_info=True)

    @_remote_log_polling_loop.before_loop
    async def before_remote_log_polling(self):
        await self.bot.wait_until_ready()
        if not self.aiohttp_session or self.aiohttp_session.closed:
            self.aiohttp_session = aiohttp.ClientSession()
        print("⛏️ Tarea de polling de logs lista. Se ejecutará si el puente de chat está activo.")

    def cog_unload(self):
        """Limpieza al descargar el cog"""
        # Detener la tarea de polling si está corriendo
        if self._remote_log_polling_loop.is_running():
            self._remote_log_polling_loop.cancel()
        self._reset_proxy()

    # ... existing code ...

async def setup(bot):
    cog = MinecraftCog(bot)
    await bot.add_cog(cog)
    # Ya no se llama a cog_load aquí, discord.py se encarga de ello.
    logger.info("MinecraftCog añadido al bot y setup completado. cog_load será llamado por discord.py.")
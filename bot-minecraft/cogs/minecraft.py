import discord
from discord.ext import commands, tasks
from discord import app_commands
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
        
        # La tarea de polling se inicia/detiene con comandos ahora, o automáticamente si se desea
        # self.remote_log_polling_task.start()

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
    async def minecraft_status(self, interaction: discord.Interaction):
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
    async def minecraft_command(self, interaction: discord.Interaction, command: str):
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
    async def minecraft_players(self, interaction: discord.Interaction):
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
    async def minecraft_whitelist(self, interaction: discord.Interaction, action: str, player: str = None):
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
    async def minecraft_kick(self, interaction: discord.Interaction, player: str, reason: str = "Expulsado por un administrador"):
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
        app_commands.Choice(name="Configurar Canal (runtime)", value="set_channel") # Nota: el canal configurado por env var tiene precedencia al reiniciar.
    ])
    async def minecraft_chat_bridge(self, interaction: discord.Interaction, action: str, channel: discord.TextChannel = None):
        await interaction.response.defer()

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

            if not self.remote_log_polling_task.is_running():
                try:
                    self.remote_log_polling_task.start()
                    logger.info(f"Tarea remote_log_polling_task iniciada por comando /mcchat enable.")
                    await interaction.followup.send(f"✅ Puente de chat activado. Mensajes del juego se enviarán a {target_channel.mention}.")
                except RuntimeError as e:
                    logger.error(f"Error al intentar iniciar remote_log_polling_task: {e}")
                    await interaction.followup.send(f"⚠️ No se pudo iniciar la tarea de polling de logs: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"ℹ️ El puente de chat ya está activo y enviando mensajes a {target_channel.mention}.", ephemeral=True)

        elif action == "disable":
            if self.remote_log_polling_task.is_running():
                self.remote_log_polling_task.cancel()
                logger.info(f"Tarea remote_log_polling_task detenida por comando /mcchat disable.")
                await interaction.followup.send("✅ Puente de chat desactivado.")
            else:
                await interaction.followup.send("ℹ️ El puente de chat ya está inactivo.", ephemeral=True)

        elif action == "status":
            status_msg = "ℹ️ **Estado del Puente de Chat Minecraft**:\n"
            target_channel = self.bot.get_channel(self.chat_channel_id) if self.chat_channel_id else None
            
            if self.mc_log_api_url and self.mc_log_api_token:
                status_msg += f"- Tarea de polling de logs: {'Activa ✅' if self.remote_log_polling_task.is_running() else 'Inactiva ❌'}\n"
            else:
                status_msg += "- Tarea de polling de logs: Inactiva ❌ (API no configurada)\n"
                
            status_msg += f"- Canal de Discord: {target_channel.mention if target_channel else 'No configurado o no encontrado'}\n"
            status_msg += f"  (ID: {self.chat_channel_id if self.chat_channel_id else 'N/A'})\n"
            status_msg += f"- API de Logs Remotos: {'Configurada ✅' if self.mc_log_api_url and self.mc_log_api_token else 'No configurada ❌ (revisa `MC_LOG_API_URL` y `MC_LOG_API_TOKEN`)'}"
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

            if not self.remote_log_polling_task.is_running():
                try:
                    self.remote_log_polling_task.start()
                    logger.info(f"Tarea remote_log_polling_task iniciada por comando m.mcchat enable.")
                    await ctx.send(f"✅ Puente de chat activado. Mensajes del juego se enviarán a {target_channel.mention}.")
                except RuntimeError as e:
                    logger.error(f"Error al intentar iniciar remote_log_polling_task: {e}")
                    await ctx.send(f"⚠️ No se pudo iniciar la tarea de polling de logs: {e}")
            else:
                await ctx.send(f"ℹ️ El puente de chat ya está activo y enviando mensajes a {target_channel.mention}.")

        elif action == "disable":
            if self.remote_log_polling_task.is_running():
                self.remote_log_polling_task.cancel()
                logger.info(f"Tarea remote_log_polling_task detenida por comando m.mcchat disable.")
                await ctx.send("✅ Puente de chat desactivado.")
            else:
                await ctx.send("ℹ️ El puente de chat ya está inactivo.")

        elif action == "status":
            status_msg = "ℹ️ **Estado del Puente de Chat Minecraft**:\n"
            target_channel = self.bot.get_channel(self.chat_channel_id) if self.chat_channel_id else None
            
            if self.mc_log_api_url and self.mc_log_api_token:
                status_msg += f"- Tarea de polling de logs: {'Activa ✅' if self.remote_log_polling_task.is_running() else 'Inactiva ❌'}\n"
            else:
                status_msg += "- Tarea de polling de logs: Inactiva ❌ (API no configurada)\n"

            status_msg += f"- Canal de Discord: {target_channel.mention if target_channel else 'No configurado o no encontrado'}\n"
            status_msg += f"  (ID: {self.chat_channel_id if self.chat_channel_id else 'N/A'})\n"
            status_msg += f"- API de Logs Remotos: {'Configurada ✅' if self.mc_log_api_url and self.mc_log_api_token else 'No configurada ❌ (revisa `MC_LOG_API_URL` y `MC_LOG_API_TOKEN`)'}"
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
    async def minecraft_say(self, interaction: discord.Interaction, message: str):
        await interaction.response.defer()
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
        if self.remote_log_polling_task.is_running():
            self.remote_log_polling_task.cancel()
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

async def setup(bot):
    await bot.add_cog(MinecraftCog(bot))
    async def minecraft_chat_bridge(self, interaction: discord.Interaction, action: str, channel: discord.TextChannel = None):
        """Configura el puente de chat entre Minecraft y Discord"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden configurar el chat bridge.", ephemeral=True)
            return
        
        embed = discord.Embed(title="🌉 Puente de Chat Minecraft-Discord", color=discord.Color.blue())
        
        if action == "enable":
            if not self.mc_log_api_url or not self.mc_log_api_token:
                embed.description = "❌ No se puede activar: MC_LOG_API_URL o MC_LOG_API_TOKEN no configurados en el bot."
            elif not self.chat_channel_id:
                embed.description = "❌ No se puede activar: canal de chat no configurado en Discord."
                embed.add_field(name="🔧 Solución", value="Usa `/mcchat set_channel` para configurar el canal", inline=False)
            else:
                self.chat_bridge_active = True
                if not self.remote_log_polling_task.is_running():
                    try:
                        self.remote_log_polling_task.start()
                        embed.description = "✅ Puente de chat activado. Iniciando sondeo de logs remotos."
                    except RuntimeError:
                        embed.description = "✅ Puente de chat ya estaba intentando activarse o ya está activo."
                else:
                    embed.description = "✅ Puente de chat activado. El sondeo de logs remotos ya está en curso."
                embed.color = discord.Color.green()
        
        elif action == "disable":
            self.chat_bridge_active = False
            embed.description = "❌ Puente de chat desactivado. El sondeo de logs remotos se detendrá en la próxima iteración o ya está inactivo."
            embed.color = discord.Color.red()
        
        elif action == "set_channel":
            if channel:
                self.chat_channel_id = channel.id
                embed.description = f"✅ Canal configurado para el chat bridge: {channel.mention}"
                embed.color = discord.Color.green()
            else:
                embed.description = "❌ Debes especificar un canal"
        
        elif action == "status":
            status_emoji = "✅" if self.chat_bridge_active else "❌"
            task_status = "Activa y sondeando" if self.remote_log_polling_task.is_running() and self.chat_bridge_active else "Inactiva"
            if self.chat_bridge_active and (not self.mc_log_api_url or not self.mc_log_api_token):
                task_status = "Configuración API incompleta"
            
            embed.description = f"{status_emoji} Estado General: {'Activado' if self.chat_bridge_active else 'Desactivado'}\n📡 Tarea de Sondeo: {task_status}"
            
            embed.add_field(
                name="🌐 URL del API de Logs",
                value=f"```{self.mc_log_api_url if self.mc_log_api_url else 'No configurado'}```",
                inline=False
            )
            embed.add_field(
                name="🔑 Token API",
                value=f"{'Configurado' if self.mc_log_api_token else 'No configurado'}",
                inline=False
            )
            
            if self.chat_channel_id:
                chat_channel_for_bridge = self.bot.get_channel(self.chat_channel_id)
                embed.add_field(
                    name="💬 Canal de chat (bridge)",
                    value=chat_channel_for_bridge.mention if chat_channel_for_bridge else "Canal no encontrado",
                    inline=False
                )
            else:
                embed.add_field(
                    name="💬 Canal de chat (bridge)",
                    value="No configurado",
                    inline=False
                )
        
        await interaction.response.send_message(embed=embed)

    @commands.command(name="mcchat", help="Configura el chat bridge. Uso: m.mcchat <enable|disable|status|set_channel> [canal]")
    async def text_minecraft_chat_bridge(self, ctx: commands.Context, action: str, channel: discord.TextChannel = None):
        """Configura el puente de chat (versión texto)"""
        action = action.lower()
        valid_actions = ["enable", "disable", "status", "set_channel"]
        if action not in valid_actions:
            await ctx.send(f"❌ Acción inválida. Acciones válidas: {', '.join(valid_actions)}")
            return

        embed = discord.Embed(title="🌉 Puente de Chat Minecraft-Discord", color=discord.Color.blue())
        if action == "enable":
            if not self.mc_log_api_url or not self.mc_log_api_token:
                embed.description = "❌ No se puede activar: MC_LOG_API_URL o MC_LOG_API_TOKEN no configurados."
            elif not self.chat_channel_id:
                embed.description = "❌ No se puede activar: canal de chat no configurado."
                embed.add_field(name="🔧 Solución", value="Usa `m.mcchat set_channel #canal`", inline=False)
            else:
                self.chat_bridge_active = True
                if not self.remote_log_polling_task.is_running():
                    try:
                        self.remote_log_polling_task.start()
                        embed.description = "✅ Puente de chat activado. Iniciando sondeo de logs remotos."
                    except RuntimeError:
                        embed.description = "✅ Puente de chat ya estaba intentando activarse o ya está activo."
                else:
                    embed.description = "✅ Puente de chat activado. El sondeo de logs remotos ya está en curso."
                embed.color = discord.Color.green()
        elif action == "disable":
            self.chat_bridge_active = False
            embed.description = "❌ Puente de chat desactivado. El sondeo de logs remotos se detendrá."
            embed.color = discord.Color.red()
        elif action == "set_channel":
            if channel:
                self.chat_channel_id = channel.id
                embed.description = f"✅ Canal configurado para el chat bridge: {channel.mention}"
                embed.color = discord.Color.green()
            else:
                embed.description = "❌ Debes especificar un canal (mención, ID o nombre)."
        elif action == "status":
            status_emoji = "✅" if self.chat_bridge_active else "❌"
            task_status = "Activa y sondeando" if self.remote_log_polling_task.is_running() and self.chat_bridge_active else "Inactiva"
            if self.chat_bridge_active and (not self.mc_log_api_url or not self.mc_log_api_token):
                task_status = "Configuración API incompleta"

            embed.description = f"{status_emoji} Estado General: {'Activado' if self.chat_bridge_active else 'Desactivado'}\n📡 Tarea de Sondeo: {task_status}"
            embed.add_field(name="🌐 URL API Logs", value=f"```{self.mc_log_api_url if self.mc_log_api_url else 'No configurado'}```", inline=False)
            embed.add_field(name="🔑 Token API", value=f"{'Configurado' if self.mc_log_api_token else 'No configurado'}", inline=False)
            if self.chat_channel_id:
                chat_channel_for_bridge = self.bot.get_channel(self.chat_channel_id)
                embed.add_field(name="💬 Canal de chat (bridge)", value=chat_channel_for_bridge.mention if chat_channel_for_bridge else "Canal no encontrado", inline=False)
            else:
                embed.add_field(name="💬 Canal de chat (bridge)", value="No configurado", inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name="mcsay", description="Envía un mensaje al chat del servidor de Minecraft")
    @app_commands.describe(message="Mensaje a enviar al servidor")
    async def minecraft_say(self, interaction: discord.Interaction, message: str):
        """Envía un mensaje al chat del servidor desde Discord"""
        await interaction.response.defer()
        
        formatted_message = f"[Discord] {interaction.user.display_name}: {message}"
        rcon_command_to_send = f"say {formatted_message}"
        result_from_rcon = await self.execute_rcon_command(rcon_command_to_send)
        
        embed = discord.Embed(
            title="💬 Mensaje Enviado",
            color=discord.Color.green()
        )
        
        embed.add_field(
            name="👤 Usuario",
            value=interaction.user.display_name,
            inline=True
        )
        
        embed.add_field(
            name="💬 Mensaje",
            value=message,
            inline=False
        )
        
        embed.add_field(
            name="📤 Estado",
            value="✅ Enviado al servidor" if "Unknown command" not in result_from_rcon and "Error" not in result_from_rcon else "❌ Error enviando mensaje",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.command(name="mcsay", help="Envía un mensaje al chat del servidor de Minecraft. Uso: m.mcsay <mensaje>")
    async def text_minecraft_say(self, ctx: commands.Context, *, message: str):
        """Comando de texto para enviar un mensaje al servidor de Minecraft"""
        if not message:
            await ctx.send("❌ Debes escribir un mensaje para enviar.")
            return

        formatted_message = f"[Discord] {ctx.author.display_name}: {message}"
        rcon_command_to_send = f"say {formatted_message}"
        result_from_rcon = await self.execute_rcon_command(rcon_command_to_send)

        embed = discord.Embed(
            title="💬 Mensaje Enviado (vía comando de texto)",
            color=discord.Color.green()
        )
        embed.add_field(name="👤 Usuario", value=ctx.author.display_name, inline=True)
        embed.add_field(name="💬 Mensaje", value=message, inline=False)
        embed.add_field(
            name="📤 Estado",
            value="✅ Enviado al servidor" if "Unknown command" not in result_from_rcon and "Error" not in result_from_rcon else "❌ Error enviando mensaje",
            inline=False
        )
        await ctx.send(embed=embed)

    @app_commands.command(name="mcconfig", description="Muestra la configuración actual del servidor de Minecraft")
    async def minecraft_config(self, interaction: discord.Interaction):
        """Muestra la configuración del bot para Minecraft"""
        embed = discord.Embed(
            title="⚙️ Configuración de Minecraft",
            color=discord.Color.blue()
        )
        
        embed.add_field(
            name="🌐 Servidor",
            value=f"`{self.server_ip}:{self.server_port}`",
            inline=True
        )
        
        embed.add_field(
            name="🔧 RCON",
            value=f"Puerto: `{self.rcon_port}`\nConfigurado: {'✅' if self.rcon_password else '❌'}",
            inline=True
        )
        
        embed.add_field(
            name="🌉 Chat Bridge",
            value=f"Estado: {'✅ Activo' if self.chat_bridge_active else '❌ Inactivo'}\nCanal: {'✅ Configurado' if self.chat_channel_id else '❌ No configurado'}",
            inline=True
        )
        
        # Información del proxy
        if self.proxy_config:
            embed.add_field(
                name="🌐 IP Estática",
                value=f"✅ Fixie Socks configurado\nHost: `{self.proxy_config['host']}`",
                inline=True
            )
        else:
            embed.add_field(
                name="🌐 IP Estática",
                value="❌ No configurado",
                inline=True
            )
        
        embed.add_field(
            name="📋 Variables de Entorno",
            value="```\nMC_SERVER_IP\nMC_SERVER_PORT\nMC_RCON_PORT\nMC_RCON_PASSWORD\nMC_CHAT_CHANNEL_ID\nMC_LOG_PATH\nFIXIE_SOCKS_HOST\n```",
            inline=False
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="mcconfig", help="Muestra la configuración actual de Minecraft. Uso: m.mcconfig")
    async def text_minecraft_config(self, ctx: commands.Context):
        """Muestra la configuración del bot para Minecraft (versión texto)"""
        embed = discord.Embed(title="⚙️ Configuración de Minecraft", color=discord.Color.blue())
        embed.add_field(name="🌐 Servidor", value=f"`{self.server_ip}:{self.server_port}`", inline=True)
        embed.add_field(name="🔧 RCON", value=f"Puerto: `{self.rcon_port}`\nConfigurado: {'✅' if self.rcon_password else '❌'}", inline=True)
        embed.add_field(name="🌉 Chat Bridge", value=f"Estado: {'✅ Activo' if self.chat_bridge_active else '❌ Inactivo'}\nCanal: {'✅ Configurado' if self.chat_channel_id else '❌ No configurado'}", inline=True)
        if self.proxy_config:
            embed.add_field(name="🌐 IP Estática", value=f"✅ Fixie Socks configurado\nHost: `{self.proxy_config['host']}`", inline=True)
        else:
            embed.add_field(name="🌐 IP Estática", value="❌ No configurado", inline=True)
        embed.add_field(name="📋 Variables de Entorno", value="```\nMC_SERVER_IP\nMC_SERVER_PORT\nMC_RCON_PORT\nMC_RCON_PASSWORD\nMC_CHAT_CHANNEL_ID\nMC_LOG_PATH\nFIXIE_SOCKS_HOST\nMC_ALLOWED_GUILD_ID\nMC_ALLOWED_CHANNEL_ID\nMC_ALLOWED_USER_ID\n```", inline=False)
        await ctx.send(embed=embed)

    @app_commands.command(name="mcchat_restart", description="Reinicia manualmente el monitor del chat bridge de Minecraft")
    async def minecraft_chat_restart(self, interaction: discord.Interaction):
        """Permite reiniciar manualmente el monitor del chat bridge"""
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden reiniciar el chat bridge.", ephemeral=True)
            return
        self.remote_log_polling_task.cancel()
        await asyncio.sleep(1)
        self.remote_log_polling_task.start()
        await interaction.response.send_message("🔄 Chat bridge reiniciado correctamente.", ephemeral=True)

    @commands.command(name="mcchat_restart", help="Reinicia el monitor del chat bridge. Uso: m.mcchat_restart")
    async def text_minecraft_chat_restart(self, ctx: commands.Context):
        """Reinicia manualmente el monitor del chat bridge (versión texto)"""
        # Aquí podrías añadir una comprobación de ctx.author.guild_permissions.administrator si quisieras
        # pero como solo tu usuario puede usarlo, el cog_check es suficiente por ahora.
        self.remote_log_polling_task.cancel()
        await asyncio.sleep(1) # Dar tiempo para que se detenga completamente
        self.remote_log_polling_task.start()
        await ctx.send("🔄 Chat bridge reiniciado correctamente.")

    @tasks.loop(seconds=5)
    async def remote_log_polling_task(self):
        if not self.chat_bridge_active:
            return # No hacer nada si el bridge no está activo

        if not self.mc_log_api_url or not self.mc_log_api_token:
            # print("Polling de logs no configurado (URL o Token faltan).")
            # Podríamos detener la tarea si falta configuración crítica y notificar.
            # self.chat_bridge_active = False
            # self.remote_log_polling_task.stop()
            # print("🚫 Polling de logs detenido por falta de configuración.")
            # channel = self.bot.get_channel(self.chat_channel_id)
            # if channel:
            #     await channel.send("🚫 El bridge de chat no está configurado correctamente (URL o Token del API de logs faltan). La tarea de polling ha sido detenida.")
            return

        if not self.aiohttp_session or self.aiohttp_session.closed:
            print("⚠️ Sesión aiohttp no disponible o cerrada. Recreando...")
            self.aiohttp_session = aiohttp.ClientSession()
            if not self.aiohttp_session: # Aún no se pudo crear
                print("❌ No se pudo recrear la sesión aiohttp. Saltando este ciclo de polling.")
                return


        headers = {"Authorization": f"Bearer {self.mc_log_api_token}"}
        full_url = f"{self.mc_log_api_url.rstrip('/')}/get_new_logs" # Asegurar que la URL esté bien formada

        try:
            # print(f"DEBUG: Polling a {full_url} con token {self.mc_log_api_token[:5]}...")
            async with self.aiohttp_session.get(full_url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json() # Esperamos que el API devuelva JSON como {"new_lines": [...]}
                    new_lines = data.get("new_lines", [])
                    if new_lines:
                        print(f"📰 Recibidas {len(new_lines)} nuevas líneas del API de logs.")
                        for line in new_lines:
                            await self.process_log_line(line) # Asumimos que 'line' es una cadena
                    # else:
                        # print("DEBUG: No hay nuevas líneas.")
                elif response.status == 401:
                    print("❌ Error de autorización (401) con el API de logs. Verifica el MC_LOG_API_TOKEN.")
                    # Considera detener el bridge o notificar
                    self.chat_bridge_active = False 
                    channel = self.bot.get_channel(self.chat_channel_id)
                    if channel:
                        await channel.send("🚫 Error de autorización con el API de logs. El token podría ser incorrecto. El bridge de chat ha sido desactivado.")
                elif response.status == 403: # El API devuelve 403 si el token está presente pero es inválido
                    print("❌ Error de autorización (403 - Token inválido) con el API de logs. Verifica el MC_LOG_API_TOKEN.")
                    self.chat_bridge_active = False
                    channel = self.bot.get_channel(self.chat_channel_id)
                    if channel:
                        await channel.send("🚫 Token del API de logs inválido. El bridge de chat ha sido desactivado.")
                else:
                    error_text = await response.text()
                    print(f"❌ Error al contactar el API de logs: {response.status} - {error_text}")
        except aiohttp.ClientConnectorError as e:
            print(f"❌ Error de conexión al API de logs: {e}. ¿Está el servidor API ({self.mc_log_api_url}) en línea y accesible?")
        except aiohttp.ClientResponseError as e: # Errores HTTP que no sean 200
            print(f"❌ Error de respuesta del API de logs: {e.status} - {e.message}")
        except asyncio.TimeoutError:
            print(f"⌛ Timeout al conectar con el API de logs en {full_url}.")
        except json.JSONDecodeError:
            raw_text = await response.text()
            print(f"❌ Error al decodificar JSON del API de logs. Respuesta recibida: {raw_text[:200]}")
        except Exception as e:
            print(f"🚨 Excepción inesperada en remote_log_polling_task: {e}")
            import traceback
            traceback.print_exc()

    @remote_log_polling_task.before_loop
    async def before_remote_log_polling(self):
        await self.bot.wait_until_ready()
        if not self.aiohttp_session or self.aiohttp_session.closed:
            self.aiohttp_session = aiohttp.ClientSession()
        print("⛏️ Tarea de polling de logs lista y esperando activación (o si ya está activa).")

    def cog_unload(self):
        """Limpieza al descargar el cog"""
        # Detener la tarea de polling si está corriendo
        if self.remote_log_polling_task.is_running():
            self.remote_log_polling_task.cancel()
        self._reset_proxy()

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

    # ... existing code ...
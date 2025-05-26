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
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading
import socks
import socket

class MinecraftLogHandler(FileSystemEventHandler):
    def __init__(self, minecraft_cog):
        self.minecraft_cog = minecraft_cog
        self.last_position = 0
        
    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith('latest.log'):
            asyncio.create_task(self.minecraft_cog.process_log_update())

class MinecraftCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Configuración del servidor (puedes cambiar estos valores)
        self.server_ip = os.environ.get("MC_SERVER_IP", "localhost")
        self.server_port = int(os.environ.get("MC_SERVER_PORT", "25565"))
        self.rcon_port = int(os.environ.get("MC_RCON_PORT", "25575"))
        self.rcon_password = os.environ.get("MC_RCON_PASSWORD", "")
        
        # Configuración del chat bridge
        self.chat_channel_id = int(os.environ.get("MC_CHAT_CHANNEL_ID", "0"))
        self.log_file_path = os.environ.get("MC_LOG_PATH", "")
        self.chat_bridge_enabled = False
        self.last_log_position = 0
        self.observer = None
        
        # Configuración del proxy Fixie Socks
        self.fixie_socks_host = os.environ.get("FIXIE_SOCKS_HOST")
        self.proxy_config = self._parse_fixie_socks_url()
        
        # Patrones regex para el chat
        self.chat_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2})\] \[Server thread/INFO\]: <(\w+)> (.+)')
        self.join_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2})\] \[Server thread/INFO\]: (\w+) joined the game')
        self.leave_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2})\] \[Server thread/INFO\]: (\w+) left the game')
        self.death_pattern = re.compile(r'\[(\d{2}:\d{2}:\d{2})\] \[Server thread/INFO\]: (\w+) (.+)')
        
        # Iniciar el monitor de logs si está configurado
        if self.log_file_path and os.path.exists(self.log_file_path):
            self.start_log_monitoring()
    
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
                print(f"❌ Formato de Fixie Socks URL no reconocido: {self.fixie_socks_host}")
                return None
        except Exception as e:
            print(f"❌ Error parseando Fixie Socks URL: {e}")
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
            print(f"🌐 Proxy SOCKSv5 configurado: {self.proxy_config['host']}:{self.proxy_config['port']}")
            return True
        return False
    
    def _reset_proxy(self):
        """Resetea la configuración del proxy"""
        if self.proxy_config:
            socket.socket = socket._realsocket if hasattr(socket, '_realsocket') else socket.socket
            
    def start_log_monitoring(self):
        """Inicia el monitoreo del archivo de logs"""
        try:
            self.observer = Observer()
            handler = MinecraftLogHandler(self)
            log_dir = os.path.dirname(self.log_file_path)
            self.observer.schedule(handler, log_dir, recursive=False)
            self.observer.start()
            print(f"📝 Monitoreo de logs iniciado: {self.log_file_path}")
        except Exception as e:
            print(f"❌ Error iniciando monitoreo de logs: {e}")
    
    def stop_log_monitoring(self):
        """Detiene el monitoreo del archivo de logs"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            print("📝 Monitoreo de logs detenido")
    
    async def process_log_update(self):
        """Procesa las nuevas líneas del log"""
        if not self.chat_bridge_enabled or not self.chat_channel_id:
            return
            
        try:
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                f.seek(self.last_log_position)
                new_lines = f.readlines()
                self.last_log_position = f.tell()
                
            for line in new_lines:
                await self.process_log_line(line.strip())
                
        except Exception as e:
            print(f"❌ Error procesando log: {e}")
    
    async def process_log_line(self, line):
        """Procesa una línea individual del log"""
        channel = self.bot.get_channel(self.chat_channel_id)
        if not channel:
            return
            
        # Chat de jugador
        chat_match = self.chat_pattern.match(line)
        if chat_match:
            time, player, message = chat_match.groups()
            embed = discord.Embed(
                description=f"💬 **{player}**: {message}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            await channel.send(embed=embed)
            return
        
        # Jugador se une
        join_match = self.join_pattern.match(line)
        if join_match:
            time, player = join_match.groups()
            embed = discord.Embed(
                description=f"✅ **{player}** se unió al servidor",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            await channel.send(embed=embed)
            return
        
        # Jugador se va
        leave_match = self.leave_pattern.match(line)
        if leave_match:
            time, player = leave_match.groups()
            embed = discord.Embed(
                description=f"❌ **{player}** salió del servidor",
                color=discord.Color.red(),
                timestamp=datetime.now()
            )
            await channel.send(embed=embed)
            return

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
            
            with MCRcon(self.server_ip, self.rcon_password, port=self.rcon_port) as mcr:
                response = mcr.command(command)
                return response
        except Exception as e:
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

    @app_commands.command(name="mccommand", description="Ejecuta un comando en el servidor de Minecraft")
    @app_commands.describe(command="El comando a ejecutar (sin el /)")
    async def minecraft_command(self, interaction: discord.Interaction, command: str):
        """Ejecuta un comando RCON en el servidor"""
        # Verificar permisos (solo administradores)
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden ejecutar comandos del servidor.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        # Ejecutar comando
        result = await asyncio.to_thread(self.execute_rcon_command, command)
        
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
        # Verificar permisos
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
        
        result = await asyncio.to_thread(self.execute_rcon_command, command)
        
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

    @app_commands.command(name="mckick", description="Expulsa a un jugador del servidor")
    @app_commands.describe(
        player="Nombre del jugador a expulsar",
        reason="Razón de la expulsión (opcional)"
    )
    async def minecraft_kick(self, interaction: discord.Interaction, player: str, reason: str = "Expulsado por un administrador"):
        """Expulsa a un jugador del servidor"""
        # Verificar permisos
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden expulsar jugadores.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        command = f"kick {player} {reason}"
        result = await asyncio.to_thread(self.execute_rcon_command, command)
        
        embed = discord.Embed(
            title="👢 Jugador Expulsado",
            color=discord.Color.orange()
        )
        
        embed.add_field(name="👤 Jugador", value=player, inline=True)
        embed.add_field(name="📝 Razón", value=reason, inline=True)
        embed.add_field(name="📤 Resultado", value=f"```{result}```", inline=False)
        
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="mcchat", description="Configura el puente de chat entre Minecraft y Discord")
    @app_commands.describe(
        action="Acción a realizar",
        channel="Canal de Discord para el chat (opcional)"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Activar", value="enable"),
        app_commands.Choice(name="Desactivar", value="disable"),
        app_commands.Choice(name="Estado", value="status"),
        app_commands.Choice(name="Configurar Canal", value="set_channel")
    ])
    async def minecraft_chat_bridge(self, interaction: discord.Interaction, action: str, channel: discord.TextChannel = None):
        """Configura el puente de chat entre Minecraft y Discord"""
        # Verificar permisos
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden configurar el chat bridge.", ephemeral=True)
            return
        
        embed = discord.Embed(title="🌉 Puente de Chat Minecraft-Discord", color=discord.Color.blue())
        
        if action == "enable":
            if not self.log_file_path or not os.path.exists(self.log_file_path):
                embed.description = "❌ No se puede activar: archivo de logs no configurado o no existe"
                embed.add_field(
                    name="📝 Configuración necesaria",
                    value="Configura la variable `MC_LOG_PATH` con la ruta al archivo `latest.log`",
                    inline=False
                )
            elif not self.chat_channel_id:
                embed.description = "❌ No se puede activar: canal de chat no configurado"
                embed.add_field(
                    name="🔧 Solución",
                    value="Usa `/mcchat set_channel` para configurar el canal",
                    inline=False
                )
            else:
                self.chat_bridge_enabled = True
                embed.description = "✅ Puente de chat activado"
                embed.color = discord.Color.green()
        
        elif action == "disable":
            self.chat_bridge_enabled = False
            embed.description = "❌ Puente de chat desactivado"
            embed.color = discord.Color.red()
        
        elif action == "set_channel":
            if channel:
                self.chat_channel_id = channel.id
                embed.description = f"✅ Canal configurado: {channel.mention}"
                embed.color = discord.Color.green()
            else:
                embed.description = "❌ Debes especificar un canal"
        
        elif action == "status":
            status_emoji = "✅" if self.chat_bridge_enabled else "❌"
            embed.description = f"{status_emoji} Estado: {'Activado' if self.chat_bridge_enabled else 'Desactivado'}"
            
            embed.add_field(
                name="📁 Archivo de logs",
                value=f"```{self.log_file_path if self.log_file_path else 'No configurado'}```",
                inline=False
            )
            
            if self.chat_channel_id:
                chat_channel = self.bot.get_channel(self.chat_channel_id)
                embed.add_field(
                    name="💬 Canal de chat",
                    value=chat_channel.mention if chat_channel else "Canal no encontrado",
                    inline=False
                )
            else:
                embed.add_field(
                    name="💬 Canal de chat",
                    value="No configurado",
                    inline=False
                )
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mcsay", description="Envía un mensaje al chat del servidor de Minecraft")
    @app_commands.describe(message="Mensaje a enviar al servidor")
    async def minecraft_say(self, interaction: discord.Interaction, message: str):
        """Envía un mensaje al chat del servidor desde Discord"""
        await interaction.response.defer()
        
        # Formatear el mensaje con el nombre del usuario de Discord
        formatted_message = f"[Discord] {interaction.user.display_name}: {message}"
        command = f"say {formatted_message}"
        
        result = await asyncio.to_thread(self.execute_rcon_command, command)
        
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
            value="✅ Enviado al servidor" if "Unknown command" not in result else "❌ Error enviando mensaje",
            inline=False
        )
        
        await interaction.followup.send(embed=embed, ephemeral=True)

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
            value=f"Estado: {'✅ Activo' if self.chat_bridge_enabled else '❌ Inactivo'}\nCanal: {'✅ Configurado' if self.chat_channel_id else '❌ No configurado'}",
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

    def cog_unload(self):
        """Limpieza al descargar el cog"""
        self.stop_log_monitoring()
        # Resetear proxy al descargar el cog
        self._reset_proxy()

async def setup(bot):
    await bot.add_cog(MinecraftCog(bot)) 
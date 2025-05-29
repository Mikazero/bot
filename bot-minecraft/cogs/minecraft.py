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
import logging
from typing import Union

logger = logging.getLogger(__name__)

class MinecraftCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.server_ip = os.environ.get("MC_SERVER_IP", "localhost")
        self.server_port = int(os.environ.get("MC_SERVER_PORT", "25565"))
        self.rcon_port = int(os.environ.get("MC_RCON_PORT", "25575"))
        self.rcon_password = os.environ.get("MC_RCON_PASSWORD", "")
        
        self.chat_channel_id = int(os.environ.get("MC_CHAT_CHANNEL_ID", "0"))
        if not self.chat_channel_id:
            logger.warning("MC_CHAT_CHANNEL_ID no está configurado...")
        
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

        # Frases clave que indican una muerte, después de "PlayerName "
        self.death_core_phrases = [
            "was slain", "was shot", "was killed", "was fireballed", "was pummeled",
            "was pricked", "was impaled", "was struck", "was burnt", "was squashed",
            "hit the ground", "fell", # "fell" es genérico y cubrirá "fell from", "fell off", etc.
            "drowned", "suffocated", "died", "perished", "went up in flames",
            "burned", "froze to death", "starved to death", "tried to swim in lava",
            "experienced kinetic energy", "withered", "blew up", "blown up"
        ]
        death_regex_clauses = "|".join([re.escape(phrase) for phrase in self.death_core_phrases])
        death_pattern_str = rf"\[\d{{2}}:\d{{2}}:\d{{2}}\] \[Server thread/INFO\]: ([^\s]+\s+(?:{death_regex_clauses}).*)"

        self.log_patterns = [
            re.compile(r'\[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]: (?:\[Not Secure\] )?<([^>]+)> (.+)'),
            re.compile(r'\[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]: ([^\s]+) joined the game'),
            re.compile(r'\[\d{2}:\d{2}:\d{2}\] \[Server thread/INFO\]: ([^\s]+) left the game'),
            re.compile(death_pattern_str) # Patrón de muerte actualizado y más específico
        ]
        
        self.mc_log_api_url = os.environ.get("MC_LOG_API_URL")
        self.mc_log_api_token = os.environ.get("MC_LOG_API_TOKEN")
        
        if not self.mc_log_api_url or not self.mc_log_api_token:
            logger.warning("MC_LOG_API_URL o MC_LOG_API_TOKEN no están configurados. El polling de logs remotos (puente de chat) no funcionará.")
        else:
            logger.info(f"🔗 Configuración del API de logs: URL={self.mc_log_api_url}, Token={'*' * len(self.mc_log_api_token) if self.mc_log_api_token else 'No establecido'}")

        self.aiohttp_session = None
        
        # Sistema de persistencia para logs procesados
        self.processed_logs_file = "processed_logs.json"
        self.processed_log_timestamps = self.load_processed_logs()
        
        self.chat_bridge_active = False
        
        logger.info("[MinecraftCog] __init__ completado.")

    def load_processed_logs(self):
        """Carga los logs procesados desde el archivo de persistencia"""
        try:
            if os.path.exists(self.processed_logs_file):
                with open(self.processed_logs_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Convertir la lista de vuelta a set para mejor rendimiento
                    loaded_logs = set(data.get('processed_logs', []))
                    logger.info(f"[PERSISTENCE] Cargados {len(loaded_logs)} logs procesados desde {self.processed_logs_file}")
                    
                    # Limpiar logs antiguos (más de 7 días) para evitar que el archivo crezca demasiado
                    current_time = datetime.now()
                    cleaned_logs = set()
                    cleaned_count = 0
                    
                    for log_id in loaded_logs:
                        # Intentar extraer timestamp del log_id
                        try:
                            if '-[' in log_id:  # Formato: "timestamp-[HH:MM:SS] log content"
                                timestamp_part = log_id.split('-')[0]
                                if timestamp_part.isdigit() and len(timestamp_part) >= 10:
                                    log_time = datetime.fromtimestamp(int(timestamp_part))
                                    age_days = (current_time - log_time).days
                                    if age_days <= 7:  # Mantener logs de los últimos 7 días
                                        cleaned_logs.add(log_id)
                                    else:
                                        cleaned_count += 1
                                else:
                                    # Si no podemos parsear el timestamp, mantener el log por seguridad
                                    cleaned_logs.add(log_id)
                            else:
                                # Formato sin timestamp, mantener por seguridad
                                cleaned_logs.add(log_id)
                        except:
                            # Si hay cualquier error parseando, mantener el log
                            cleaned_logs.add(log_id)
                    
                    if cleaned_count > 0:
                        logger.info(f"[PERSISTENCE] Limpiados {cleaned_count} logs antiguos (>7 días)")
                        # Guardar la versión limpia inmediatamente
                        self._save_processed_logs_sync(cleaned_logs)
                    
                    return cleaned_logs
            else:
                logger.info(f"[PERSISTENCE] Archivo {self.processed_logs_file} no existe, iniciando con set vacío")
                return set()
        except Exception as e:
            logger.error(f"[PERSISTENCE] Error al cargar logs procesados: {e}", exc_info=True)
            logger.warning("[PERSISTENCE] Iniciando con set vacío de logs procesados")
            return set()

    def _save_processed_logs_sync(self, logs_set):
        """Versión síncrona para guardar logs procesados"""
        try:
            # Convertir set a lista para JSON y limitar a los últimos 10000 para evitar archivos muy grandes
            logs_list = list(logs_set)
            if len(logs_list) > 10000:
                # Mantener solo los últimos 10000 logs
                logs_list = logs_list[-10000:]
                logger.warning(f"[PERSISTENCE] Limitando a 10000 logs más recientes (había {len(logs_set)})")
            
            data = {
                'processed_logs': logs_list,
                'last_updated': datetime.now().isoformat(),
                'total_count': len(logs_list)
            }
            
            # Escribir a un archivo temporal primero y luego renombrar para atomicidad
            temp_file = f"{self.processed_logs_file}.tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # Renombrar el archivo temporal al archivo final
            if os.path.exists(self.processed_logs_file):
                os.remove(self.processed_logs_file)
            os.rename(temp_file, self.processed_logs_file)
            
            logger.debug(f"[PERSISTENCE] Guardados {len(logs_list)} logs procesados en {self.processed_logs_file}")
        except Exception as e:
            logger.error(f"[PERSISTENCE] Error al guardar logs procesados: {e}", exc_info=True)

    async def save_processed_logs(self):
        """Guarda los logs procesados al archivo de persistencia de forma asíncrona"""
        try:
            # Ejecutar la operación de guardado en un thread separado para no bloquear
            await asyncio.get_event_loop().run_in_executor(None, self._save_processed_logs_sync, self.processed_log_timestamps.copy())
        except Exception as e:
            logger.error(f"[PERSISTENCE] Error en guardado asíncrono: {e}", exc_info=True)

    async def process_log_line(self, line: str, timestamp_str: str = None):
        logger.info(f"[PLP_TRACE] Entrando a process_log_line. Línea: '{line[:100]}...', Timestamp_str: {timestamp_str}")

        channel = self.bot.get_channel(self.chat_channel_id)
        if not channel:
            logger.error(f"[PLP_ERROR] Canal de chat con ID {self.chat_channel_id} no encontrado. Línea: '{line[:100]}...'")
            return

        log_identifier = f"{timestamp_str}-{line}" if timestamp_str else line
        if log_identifier in self.processed_log_timestamps:
            logger.info(f"[PLP_SKIP] Línea ya procesada (ID: '{log_identifier[:100]}...'). Saltando: '{line[:100]}...'")
            return
            
        # Intentaremos procesar. Si ningún patrón útil coincide, la marcaremos como procesada al final.

        current_time_for_embed = datetime.now()

        # --- Intento de Patrón de Chat ---
        logger.debug(f"[PLP_REGEX_ATTEMPT] Intentando patrón CHAT en línea: '{line[:100]}...'")
        chat_match = self.log_patterns[0].search(line)
        if chat_match:
            try:
                player = chat_match.group(1)
                message = chat_match.group(2)
                logger.info(f"[PLP_MATCH_CHAT] J: '{player}', M: '{message}' (L: '{line[:100]}...')")
                embed = discord.Embed(description=f"💬 **{player.strip()}**: {message.strip()}", color=discord.Color.blue(), timestamp=current_time_for_embed)
                await channel.send(embed=embed)
                logger.info(f"[PLP_SENT_CHAT] Embed CHAT para '{player}' enviado.")
                self.processed_log_timestamps.add(log_identifier) # Marcada como procesada con éxito
                # Guardar de forma asíncrona
                asyncio.create_task(self.save_processed_logs())
                return
            except IndexError:
                logger.error(f"[PLP_ERROR_CHAT_INDEX] Grupos: {chat_match.groups()}. L: {line[:100]}...", exc_info=True)
            except Exception as e:
                logger.error(f"[PLP_ERROR_CHAT_SEND] Excepción: {e}. L: {line[:100]}...", exc_info=True)
            self.processed_log_timestamps.add(log_identifier) # Marcada como procesada incluso si hubo error después del match
            asyncio.create_task(self.save_processed_logs())
            return
        
        # --- Intento de Patrón de Unirse ---
        logger.debug(f"[PLP_REGEX_ATTEMPT] Intentando patrón JOIN en línea: '{line[:100]}...'")
        join_match = self.log_patterns[1].search(line)
        if join_match:
            try:
                player = join_match.group(1)
                logger.info(f"[PLP_MATCH_JOIN] J: '{player}' (L: '{line[:100]}...')")
                embed = discord.Embed(description=f"✅ **{player.strip()}** se unió.", color=discord.Color.green(), timestamp=current_time_for_embed)
                await channel.send(embed=embed)
                logger.info(f"[PLP_SENT_JOIN] Embed JOIN para '{player}' enviado.")
                self.processed_log_timestamps.add(log_identifier)
                asyncio.create_task(self.save_processed_logs())
                return
            except IndexError:
                logger.error(f"[PLP_ERROR_JOIN_INDEX] Grupos: {join_match.groups()}. L: {line[:100]}...", exc_info=True)
            except Exception as e:
                logger.error(f"[PLP_ERROR_JOIN_SEND] Excepción: {e}. L: {line[:100]}...", exc_info=True)
            self.processed_log_timestamps.add(log_identifier)
            asyncio.create_task(self.save_processed_logs())
            return
        
        # --- Intento de Patrón de Salir ---
        logger.debug(f"[PLP_REGEX_ATTEMPT] Intentando patrón LEAVE en línea: '{line[:100]}...'")
        leave_match = self.log_patterns[2].search(line)
        if leave_match:
            try:
                player = leave_match.group(1)
                logger.info(f"[PLP_MATCH_LEAVE] J: '{player}' (L: '{line[:100]}...')")
                embed = discord.Embed(description=f"❌ **{player.strip()}** salió.", color=discord.Color.red(), timestamp=current_time_for_embed)
                await channel.send(embed=embed)
                logger.info(f"[PLP_SENT_LEAVE] Embed LEAVE para '{player}' enviado.")
                self.processed_log_timestamps.add(log_identifier)
                asyncio.create_task(self.save_processed_logs())
                return
            except IndexError:
                logger.error(f"[PLP_ERROR_LEAVE_INDEX] Grupos: {leave_match.groups()}. L: {line[:100]}...", exc_info=True)
            except Exception as e:
                logger.error(f"[PLP_ERROR_LEAVE_SEND] Excepción: {e}. L: {line[:100]}...", exc_info=True)
            self.processed_log_timestamps.add(log_identifier)
            asyncio.create_task(self.save_processed_logs())
            return

        # --- Intento de Patrón de Muerte ---
        # Logs de depuración adicionales para el patrón de muerte
        logger.critical(f"[PLP_DEATH_DEBUG] Para línea: {repr(line)}")
        try:
            logger.critical(f"[PLP_DEATH_DEBUG]   Patrón DEATH compilado: {self.log_patterns[3].pattern}")
            logger.critical(f"[PLP_DEATH_DEBUG]   Lista de core phrases en uso: {self.death_core_phrases}")
            
            # Prueba específica para líneas que contienen palabras clave de muerte
            for phrase in self.death_core_phrases:
                if phrase in line:
                    logger.critical(f"[PLP_DEATH_DEBUG]   ¡Línea contiene frase clave '{phrase}'!")
                    break
            else:
                logger.critical(f"[PLP_DEATH_DEBUG]   Línea NO contiene ninguna frase clave de muerte.")
                
        except IndexError:
            logger.critical("[PLP_DEATH_DEBUG]   Error: self.log_patterns[3] no existe (IndexError).")
        except AttributeError:
            logger.critical("[PLP_DEATH_DEBUG]   Error: self.log_patterns[3] no es un objeto regex compilado (AttributeError).")
            
        logger.debug(f"[PLP_REGEX_ATTEMPT] Intentando patrón DEATH en línea: '{line[:100]}...'")
        death_match = self.log_patterns[3].search(line)
        logger.critical(f"[PLP_DEATH_DEBUG]   Resultado de search(): {death_match}")
        if death_match:
            logger.critical(f"[PLP_DEATH_DEBUG]   Grupos encontrados: {death_match.groups()}")
        if death_match:
            try:
                death_message = death_match.group(1)
                logger.info(f"[PLP_MATCH_DEATH] M: '{death_message}' (L: '{line[:100]}...')")
                embed = discord.Embed(description=f"💀 {death_message.strip()}", color=discord.Color.dark_grey(), timestamp=current_time_for_embed)
                await channel.send(embed=embed)
                logger.info(f"[PLP_SENT_DEATH] Embed DEATH para '{death_message}' enviado.")
                self.processed_log_timestamps.add(log_identifier)
                asyncio.create_task(self.save_processed_logs())
                return
            except IndexError:
                logger.error(f"[PLP_ERROR_DEATH_INDEX] Grupos: {death_match.groups()}. L: {line[:100]}...", exc_info=True)
            except Exception as e:
                logger.error(f"[PLP_ERROR_DEATH_SEND] Excepción: {e}. L: {line[:100]}...", exc_info=True)
            self.processed_log_timestamps.add(log_identifier)
            asyncio.create_task(self.save_processed_logs())
            return

        logger.info(f"[PLP_NO_MATCH_ALL] Línea no coincidió con NINGÚN patrón: '{line[:200]}...'")
        self.processed_log_timestamps.add(log_identifier) # Marcar como procesada para no reintentar logs que no coinciden
        # Para logs que no coinciden, guardamos pero con menos frecuencia para no saturar el disco
        if len(self.processed_log_timestamps) % 10 == 0:  # Guardar cada 10 logs no coincidentes
            asyncio.create_task(self.save_processed_logs())

    async def get_server_status(self):
        logger.debug(f"[MinecraftCog] get_server_status: Intentando obtener estado para {self.server_ip}:{self.server_port}")
        try:
            server = JavaServer.lookup(f"{self.server_ip}:{self.server_port}")
            status = await asyncio.to_thread(server.status)
            logger.debug(f"[MinecraftCog] get_server_status: Estado obtenido: {status.players.online if status else 'N/A'} jugadores.")
            return status
        except Exception as e:
            logger.error(f"[MinecraftCog] get_server_status: Error al obtener estado del servidor: {e}", exc_info=True)
            return None
    
    async def execute_rcon_command(self, command):
        logger.debug(f"[MinecraftCog] execute_rcon_command: Intentando ejecutar '{command}'")
        if not self.rcon_password:
            logger.warning("[MinecraftCog] execute_rcon_command: RCON no configurado (falta contraseña).")
            return "❌ RCON no configurado (falta contraseña)"
        
        try:
            def rcon_blocking_call():
                logger.debug(f"[MinecraftCog] rcon_blocking_call: Conectando a {self.server_ip}:{self.rcon_port} para comando '{command}'")
                try:
                    with MCRcon(self.server_ip, self.rcon_password, port=self.rcon_port) as mcr:
                        response = mcr.command(command)
                        logger.debug(f"[MinecraftCog] rcon_blocking_call: Comando '{command}' ejecutado, respuesta: '{response[:100]}...'")
                        return response
                except Exception as e:
                    logger.error(f"[MinecraftCog] rcon_blocking_call: Error en thread RCON: {e}")
                    raise e
            
            # Usar ThreadPoolExecutor en lugar de asyncio.to_thread para evitar problemas de señales
            import concurrent.futures
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                response = await loop.run_in_executor(executor, rcon_blocking_call)
            return response
        except Exception as e:
            logger.error(f"[MinecraftCog] execute_rcon_command: Error detallado ejecutando comando RCON '{command}':", exc_info=True)
            return f"❌ Error ejecutando comando: {str(e)}"

    @app_commands.command(name="mcstatus", description="Muestra el estado del servidor de Minecraft")
    async def minecraft_status(self, interaction: Interaction):
        await interaction.response.defer()
        logger.debug("[MinecraftCog] /mcstatus: Comando recibido.")
        status = await self.get_server_status()
        
        if status is None:
            embed = discord.Embed(title="🔴 Servidor Offline", description=f"No se pudo conectar a `{self.server_ip}:{self.server_port}`", color=discord.Color.red())
        else:
            embed = discord.Embed(title="🟢 Servidor Online", description=f"**{self.server_ip}:{self.server_port}**", color=discord.Color.green())
            embed.add_field(name="👥 Jugadores", value=f"{status.players.online}/{status.players.max}", inline=True)
            embed.add_field(name="📊 Latencia", value=f"{status.latency:.1f}ms", inline=True)
            embed.add_field(name="🎮 Versión", value=status.version.name, inline=True)
            if status.players.online > 0 and status.players.sample:
                players_list = [player.name for player in status.players.sample]
                players_text = ", ".join(players_list[:10]) + (f" y {len(players_list) - 10} más..." if len(players_list) > 10 else "")
                embed.add_field(name="🎯 Jugadores Online", value=f"```{players_text}```", inline=False)
            
            embed.timestamp = datetime.now()
        
        logger.debug("[MinecraftCog] /mcstatus: Enviando respuesta.")
        await interaction.followup.send(embed=embed)

    @commands.command(name="mcstatus", help="Muestra el estado del servidor de Minecraft. Uso: m.mcstatus")
    async def text_minecraft_status(self, ctx: commands.Context):
        logger.debug("[MinecraftCog] m.mcstatus: Comando recibido.")
        status = await self.get_server_status()
        if status is None:
            embed = discord.Embed(title="🔴 Servidor Offline", description=f"No se pudo conectar a `{self.server_ip}:{self.server_port}`",color=discord.Color.red())
        else:
            embed = discord.Embed(title="🟢 Servidor Online",description=f"**{self.server_ip}:{self.server_port}**",color=discord.Color.green())
            embed.add_field(name="👥 Jugadores", value=f"{status.players.online}/{status.players.max}", inline=True)
            embed.add_field(name="📊 Latencia", value=f"{status.latency:.1f}ms", inline=True)
            embed.add_field(name="🎮 Versión", value=status.version.name, inline=True)
            if status.players.online > 0 and status.players.sample:
                players_list = [player.name for player in status.players.sample]
                players_text = ", ".join(players_list[:10]) + (f" y {len(players_list) - 10} más..." if len(players_list) > 10 else "")
                embed.add_field(name="🎯 Jugadores Online", value=f"```{players_text}```", inline=False)
            embed.timestamp = datetime.now()
        logger.debug("[MinecraftCog] m.mcstatus: Enviando respuesta.")
        await ctx.send(embed=embed)

    @app_commands.command(name="mccommand", description="Ejecuta un comando en el servidor de Minecraft")
    @app_commands.describe(command="El comando a ejecutar (sin el /)")
    async def minecraft_command(self, interaction: Interaction, command: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden ejecutar comandos del servidor.", ephemeral=True)
            return
        
        await interaction.response.defer()
        logger.debug(f"[MinecraftCog] /mccommand: Comando '{command}' recibido.")
        result = await self.execute_rcon_command(command)
        embed = discord.Embed(title="🎮 Comando Ejecutado", color=discord.Color.blue())
        embed.add_field(name="📝 Comando", value=f"```/{command}```", inline=False)
        embed.add_field(name="📤 Resultado", value=f"```{result[:1000]}```", inline=False)
        embed.timestamp = datetime.now()
        logger.debug(f"[MinecraftCog] /mccommand: Enviando respuesta para '{command}'.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="mcplayers", description="Lista todos los jugadores online")
    async def minecraft_players(self, interaction: Interaction):
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
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden gestionar la whitelist.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        if action in ["add", "remove"] and not player:
            await interaction.followup.send("❌ Debes especificar un nombre de jugador para esta acción.")
            return
        
        command = "whitelist list" if action == "list" else f"whitelist {action}"
        if action in ["on", "off"]:
            command = f"whitelist {action}"
        else:
            command = f"whitelist {action} {player}"
        
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
        action = action.lower()
        valid_actions = ["add", "remove", "list", "on", "off"]
        if action not in valid_actions:
            await ctx.send(f"❌ Acción inválida. Acciones válidas: {', '.join(valid_actions)}")
            return

        if action in ["add", "remove"] and not player:
            await ctx.send("❌ Debes especificar un nombre de jugador para esta acción (`add` o `remove`).")
            return
        
        command = "whitelist list" if action == "list" else f"whitelist {action}"
        if action in ["on", "off"]:
            command = f"whitelist {action}"
        else:
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
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo los administradores pueden expulsar jugadores.", ephemeral=True)
            return
        
        await interaction.response.defer()
        
        command = f"kick {player} {reason}"
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
        logger.debug(f"[MinecraftCog] Comando /mcchat recibido. Acción: {action}, Canal: {channel}")
        
        if action == "enable":
            if not self.chat_channel_id:
                logger.warning("[MinecraftCog] /mcchat enable: chat_channel_id no configurado.")
                await interaction.followup.send("❌ El canal de chat no está configurado...", ephemeral=True)
                return
            if not self.mc_log_api_url or not self.mc_log_api_token:
                logger.warning("[MinecraftCog] /mcchat enable: MC_LOG_API_URL o MC_LOG_API_TOKEN no configurados.")
                await interaction.followup.send("❌ La URL o el token del API de logs no están configurados...", ephemeral=True)
                return
            
            target_channel = self.bot.get_channel(self.chat_channel_id)
            if not target_channel:
                logger.warning(f"[MinecraftCog] /mcchat enable: No se pudo encontrar el target_channel con ID {self.chat_channel_id}")
                await interaction.followup.send(f"❌ No se pudo encontrar el canal de chat configurado (ID: {self.chat_channel_id})...", ephemeral=True)
                return

            logger.info(f"[MinecraftCog] /mcchat enable: Intentando activar puente. Tarea corriendo actualmente: {self._remote_log_polling_loop.is_running()}")
            if not self._remote_log_polling_loop.is_running():
                try:
                    self.chat_bridge_active = True
                    logger.info("[MinecraftCog] /mcchat enable: Estableciendo chat_bridge_active=True. Llamando a _remote_log_polling_loop.start().")
                    self._remote_log_polling_loop.start()
                    logger.info(f"[MinecraftCog] /mcchat enable: _remote_log_polling_loop.start() llamado. Tarea corriendo ahora: {self._remote_log_polling_loop.is_running()}")
                    await interaction.followup.send(f"✅ Puente de chat activado. Mensajes del juego se enviarán a {target_channel.mention}.")
                except RuntimeError as e:
                    logger.error(f"[MinecraftCog] /mcchat enable: Error al intentar iniciar _remote_log_polling_loop: {e}", exc_info=True)
                    await interaction.followup.send(f"⚠️ No se pudo iniciar la tarea de polling de logs: {e}. Intenta de nuevo.", ephemeral=True)
            else:
                self.chat_bridge_active = True
                logger.info(f"[MinecraftCog] /mcchat enable: Puente de chat ya estaba activo o tarea ya corría. chat_bridge_active={self.chat_bridge_active}")
                await interaction.followup.send(f"ℹ️ El puente de chat ya está activo y enviando mensajes a {target_channel.mention}.")
        
        elif action == "disable":
            logger.info(f"[MinecraftCog] /mcchat disable: Intentando desactivar puente. Tarea corriendo: {self._remote_log_polling_loop.is_running()}, chat_bridge_active: {self.chat_bridge_active}")
            self.chat_bridge_active = False 
            if self._remote_log_polling_loop.is_running():
                self._remote_log_polling_loop.cancel()
                logger.info("[MinecraftCog] /mcchat disable: Tarea _remote_log_polling_loop cancelada.")
                await interaction.followup.send("✅ Puente de chat desactivado. El sondeo de logs se ha detenido.")
            else:
                logger.info("[MinecraftCog] /mcchat disable: Puente de chat ya estaba inactivo o tarea no corría.")
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
            logger.debug(f"[MinecraftCog] /mcchat status: bridge_active={self.chat_bridge_active}, task_running={self._remote_log_polling_loop.is_running()}, api_url_set={bool(self.mc_log_api_url)}, api_token_set={bool(self.mc_log_api_token)}, channel_id={self.chat_channel_id}")
            await interaction.followup.send(status_msg, ephemeral=True)
        
        elif action == "set_channel":
            if channel:
                self.chat_channel_id = channel.id
                logger.info(f"Canal de chat para Minecraft bridge configurado a {channel.name} (ID: {channel.id}) mediante comando.")
                await interaction.followup.send(f"✅ Canal para el puente de chat configurado a {channel.mention}. Este cambio es temporal (solo para esta sesión del bot).", ephemeral=True)
            else:
                await interaction.followup.send("❌ Debes especificar un canal para esta acción.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Acción desconocida.", ephemeral=True)

    @commands.command(name="mcchat", help="Configura el chat bridge. Uso: m.mcchat <enable|disable|status|set_channel> [#canal]")
    async def text_minecraft_chat_bridge(self, ctx: commands.Context, action: str, channel: discord.TextChannel = None):
        action = action.lower()
        logger.debug(f"[MinecraftCog] Comando m.mcchat recibido. Acción: {action}, Canal: {channel}")

        if action == "enable":
            if not self.chat_channel_id:
                logger.warning("[MinecraftCog] m.mcchat enable: chat_channel_id no configurado.")
                await ctx.send("❌ El canal de chat no está configurado...")
                return
            if not self.mc_log_api_url or not self.mc_log_api_token:
                logger.warning("[MinecraftCog] m.mcchat enable: MC_LOG_API_URL o MC_LOG_API_TOKEN no configurados.")
                await ctx.send("❌ La URL o el token del API de logs no están configurados...")
                return

            target_channel = self.bot.get_channel(self.chat_channel_id)
            if not target_channel:
                logger.warning(f"[MinecraftCog] m.mcchat enable: No se pudo encontrar el target_channel con ID {self.chat_channel_id}")
                await ctx.send(f"❌ No se pudo encontrar el canal de chat configurado (ID: {self.chat_channel_id})...")
                return
            
            logger.info(f"[MinecraftCog] m.mcchat enable: Intentando activar puente. Tarea corriendo actualmente: {self._remote_log_polling_loop.is_running()}")
            if not self._remote_log_polling_loop.is_running():
                try:
                    if not self.aiohttp_session or self.aiohttp_session.closed:
                        logger.info("[MinecraftCog] m.mcchat enable: Creando nueva sesión aiohttp para la tarea.")
                        self.aiohttp_session = aiohttp.ClientSession()
                    self.chat_bridge_active = True
                    logger.info("[MinecraftCog] m.mcchat enable: Estableciendo chat_bridge_active=True. Llamando a _remote_log_polling_loop.start().")
                    self._remote_log_polling_loop.start()
                    logger.info(f"[MinecraftCog] m.mcchat enable: _remote_log_polling_loop.start() llamado. Tarea corriendo ahora: {self._remote_log_polling_loop.is_running()}")
                    await ctx.send(f"✅ Puente de chat activado. Mensajes a {target_channel.mention}.")
                except RuntimeError as e:
                    logger.error(f"[MinecraftCog] m.mcchat enable: Error al iniciar _remote_log_polling_loop (texto): {e}", exc_info=True)
                    await ctx.send(f"⚠️ No se pudo iniciar la tarea: {e}.")
            else:
                self.chat_bridge_active = True
                logger.info(f"[MinecraftCog] m.mcchat enable: Puente de chat ya estaba activo o tarea ya corría. chat_bridge_active={self.chat_bridge_active}")
                await ctx.send(f"ℹ️ El puente de chat ya está activo ({target_channel.mention}).")

        elif action == "disable":
            logger.info(f"[MinecraftCog] m.mcchat disable: Intentando desactivar puente. Tarea corriendo: {self._remote_log_polling_loop.is_running()}, chat_bridge_active: {self.chat_bridge_active}")
            self.chat_bridge_active = False
            if self._remote_log_polling_loop.is_running():
                self._remote_log_polling_loop.cancel()
                logger.info("[MinecraftCog] m.mcchat disable: Tarea _remote_log_polling_loop cancelada.")
                await ctx.send("✅ Puente de chat desactivado.")
            else:
                logger.info("[MinecraftCog] m.mcchat disable: Puente de chat ya estaba inactivo o tarea no corría.")
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
            logger.debug(f"[MinecraftCog] m.mcchat status: bridge_active={self.chat_bridge_active}, task_running={self._remote_log_polling_loop.is_running()}, api_url_set={bool(self.mc_log_api_url)}, api_token_set={bool(self.mc_log_api_token)}, channel_id={self.chat_channel_id}")
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
        
        if response is not None and response.startswith("❌ Error ejecutando comando:"):
            logger.warning(f"Error de RCON al intentar enviar '/say {message}': {response}")
            await interaction.followup.send(f"⚠️ Error al enviar mensaje al servidor: ```{response}```", ephemeral=True)
        elif response is None or response == "" or message in response:
            logger.info(f"Mensaje '/say {message}' enviado a Minecraft vía RCON. Respuesta: '{response}'")
            await interaction.followup.send(f"✅ Mensaje enviado al servidor: `{message}`")
        else:
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
        elif response is None or response == "" or message in response:
            logger.info(f"Mensaje '/say {message}' enviado a Minecraft vía RCON (comando de texto). Respuesta: '{response}'")
            await ctx.send(f"✅ Mensaje enviado al servidor: `{message}`")
        else:
            logger.info(f"Respuesta inesperada de RCON para '/say {message}' (comando de texto): '{response}'")
            await ctx.send(f"ℹ️ Respuesta del servidor: ```{response}```")
            
    def cog_unload(self):
        logger.info("[MinecraftCog] Descargando MinecraftCog...")
        if hasattr(self, '_remote_log_polling_loop') and self._remote_log_polling_loop.is_running():
            self._remote_log_polling_loop.cancel()
            logger.info("[MinecraftCog] Tarea de polling de logs remotos cancelada.")
        
        # Guardar logs procesados antes de descargar
        try:
            logger.info("[MinecraftCog] Guardando logs procesados antes de descargar...")
            self._save_processed_logs_sync(self.processed_log_timestamps)
            logger.info(f"[MinecraftCog] Guardados {len(self.processed_log_timestamps)} logs procesados")
        except Exception as e:
            logger.error(f"[MinecraftCog] Error al guardar logs procesados durante descarga: {e}", exc_info=True)
        
        if hasattr(self, 'aiohttp_session') and self.aiohttp_session and not self.aiohttp_session.closed:
            try:
                asyncio.create_task(self.aiohttp_session.close())
                logger.info("[MinecraftCog] Cierre de sesión aiohttp programado.")
            except Exception as e:
                logger.error(f"[MinecraftCog] Error al programar cierre de sesión aiohttp: {e}", exc_info=True)
        else:
            logger.info("[MinecraftCog] No se encontró sesión aiohttp activa para cerrar o ya estaba cerrada.")
        
        logger.info("[MinecraftCog] MinecraftCog descargado.")

    @commands.command(name="mclogs", help="Gestiona la persistencia de logs. Uso: m.mclogs <info|clear|save>")
    async def text_minecraft_logs_management(self, ctx: commands.Context, action: str = "info"):
        """Gestiona el sistema de persistencia de logs procesados"""
        action = action.lower()
        
        if action == "info":
            # Mostrar información sobre logs procesados
            total_logs = len(self.processed_log_timestamps)
            file_exists = os.path.exists(self.processed_logs_file)
            file_size = 0
            file_date = "N/A"
            
            if file_exists:
                try:
                    file_size = os.path.getsize(self.processed_logs_file)
                    file_date = datetime.fromtimestamp(os.path.getmtime(self.processed_logs_file)).strftime("%Y-%m-%d %H:%M:%S")
                except:
                    pass
            
            embed = discord.Embed(title="📊 Información de Logs Procesados", color=discord.Color.blue())
            embed.add_field(name="🔢 Logs en memoria", value=str(total_logs), inline=True)
            embed.add_field(name="📁 Archivo existe", value="✅ Sí" if file_exists else "❌ No", inline=True)
            embed.add_field(name="📏 Tamaño archivo", value=f"{file_size:,} bytes" if file_exists else "N/A", inline=True)
            embed.add_field(name="📅 Última modificación", value=file_date, inline=False)
            embed.add_field(name="📂 Ruta archivo", value=f"`{self.processed_logs_file}`", inline=False)
            
            await ctx.send(embed=embed)
            
        elif action == "clear":
            # Limpiar logs procesados (solo administradores)
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("❌ Solo los administradores pueden limpiar los logs procesados.")
                return
                
            # Solicitar confirmación
            confirm_msg = await ctx.send("⚠️ **¿Estás seguro de que quieres limpiar todos los logs procesados?**\n"
                                       "Esto significa que el bot volverá a procesar todos los logs del servidor la próxima vez que se reinicie.\n"
                                       "Reacciona con ✅ para confirmar o ❌ para cancelar.")
            await confirm_msg.add_reaction("✅")
            await confirm_msg.add_reaction("❌")
            
            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id
            
            try:
                reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
                if str(reaction.emoji) == "✅":
                    # Limpiar logs
                    old_count = len(self.processed_log_timestamps)
                    self.processed_log_timestamps.clear()
                    
                    # Eliminar archivo de persistencia
                    try:
                        if os.path.exists(self.processed_logs_file):
                            os.remove(self.processed_logs_file)
                        await ctx.send(f"✅ Limpiados {old_count} logs procesados y eliminado archivo de persistencia.")
                        logger.info(f"[LOGS MANAGEMENT] Usuario {ctx.author} limpió {old_count} logs procesados")
                    except Exception as e:
                        await ctx.send(f"⚠️ Logs en memoria limpiados pero error al eliminar archivo: {e}")
                else:
                    await ctx.send("❌ Operación cancelada.")
            except asyncio.TimeoutError:
                await ctx.send("⏰ Tiempo agotado. Operación cancelada.")
                
        elif action == "save":
            # Forzar guardado manual
            try:
                await self.save_processed_logs()
                await ctx.send(f"✅ Guardados {len(self.processed_log_timestamps)} logs procesados en `{self.processed_logs_file}`")
                logger.info(f"[LOGS MANAGEMENT] Usuario {ctx.author} forzó guardado de logs")
            except Exception as e:
                await ctx.send(f"❌ Error al guardar logs: {e}")
                logger.error(f"[LOGS MANAGEMENT] Error en guardado manual: {e}", exc_info=True)
                
        else:
            await ctx.send("❌ Acción inválida. Acciones disponibles: `info`, `clear`, `save`")

    def is_allowed_guild(self, ctx_or_interaction) -> bool:
        if not self.allowed_guild_id: return True
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

    async def combined_access_check(self, ctx_or_interaction) -> bool:
        if not self.is_allowed_guild(ctx_or_interaction):
            raise commands.CheckFailure("Este comando no está permitido en este servidor.")
        if not self.is_allowed_channel(ctx_or_interaction):
            raise commands.CheckFailure("Este comando no está permitido en este canal.")
        if not self.is_allowed_user(ctx_or_interaction):
            raise commands.CheckFailure("No tienes permiso para usar este comando.")
        return True

    async def cog_check(self, ctx_or_interaction: Union[Interaction, commands.Context]):
        if isinstance(ctx_or_interaction, commands.Context):
            return await self.combined_access_check(ctx_or_interaction)
        elif isinstance(ctx_or_interaction, Interaction):
            return await self.combined_access_check(ctx_or_interaction)
        return False

    async def cog_command_error(self, ctx_or_interaction: Union[Interaction, commands.Context], error):
        if isinstance(error, commands.CheckFailure):
            message = str(error) if str(error) else "No cumples con los requisitos para usar este comando aquí."
            if isinstance(ctx_or_interaction, Interaction):
                if ctx_or_interaction.response.is_done():
                    await ctx_or_interaction.followup.send(message, ephemeral=True)
                else:
                    await ctx_or_interaction.response.send_message(message, ephemeral=True)
        else:
            await ctx_or_interaction.send(message, ephemeral=True)

    @tasks.loop(seconds=5)
    async def _remote_log_polling_loop(self):
        logger.info(f"[MinecraftCog] Inicio de ciclo _remote_log_polling_loop. chat_bridge_active={self.chat_bridge_active}")
        if not self.chat_bridge_active:
            logger.debug("[MinecraftCog] _remote_log_polling_loop: Saliendo porque chat_bridge_active es False.")
            return

        if not self.mc_log_api_url or not self.mc_log_api_token:
            logger.warning("[MinecraftCog] _remote_log_polling_loop: Saliendo porque MC_LOG_API_URL o MC_LOG_API_TOKEN no están configurados.")
            return

        logger.debug("[MinecraftCog] _remote_log_polling_loop: Verificando sesión aiohttp.")
        if not self.aiohttp_session or self.aiohttp_session.closed:
            logger.warning("[MinecraftCog] _remote_log_polling_loop: Sesión aiohttp no disponible o cerrada. Recreando...")
            try:
                self.aiohttp_session = aiohttp.ClientSession()
                logger.info("[MinecraftCog] _remote_log_polling_loop: Sesión aiohttp recreada en polling task.")
            except Exception as e:
                logger.error(f"[MinecraftCog] _remote_log_polling_loop: No se pudo recrear la sesión aiohttp: {e}. Saltando ciclo.", exc_info=True)
                return
        
        headers = {
            "Authorization": f"Bearer {self.mc_log_api_token}", 
            "User-Agent": "DiscordBot-MinecraftCog/1.0"
        }
        full_url = f"{self.mc_log_api_url.rstrip('/')}/get_new_logs"
        logger.debug(f"[MinecraftCog] _remote_log_polling_loop: Haciendo petición GET a {full_url}")

        try:
            async with self.aiohttp_session.get(full_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                logger.debug(f"[MinecraftCog] _remote_log_polling_loop: Respuesta recibida del API: Status {response.status}")
                if response.status == 200:
                    data = await response.json()
                    
                    # Información del servidor optimizado
                    client_id = data.get("client_id", "unknown")
                    total_new_lines = data.get("total_new_lines", 0)
                    is_first_request = data.get("is_first_request", False)
                    last_line_processed = data.get("last_line_processed", 0)
                    
                    logger.info(f"[MinecraftCog] Cliente: {client_id}, Nuevas líneas: {total_new_lines}, Primera petición: {is_first_request}, Última línea procesada: {last_line_processed}")
                    
                    new_lines = data.get("new_lines", [])
                    if new_lines:
                        logger.info(f"[MinecraftCog] _remote_log_polling_loop: {len(new_lines)} nuevas líneas recibidas. Procesando...")
                        
                        # Procesar cada línea nueva con el formato optimizado
                        for item in new_lines:
                            line_to_process = None
                            timestamp_for_line = None
                            line_number = None
                            
                            if isinstance(item, dict):
                                # Nuevo formato optimizado del servidor
                                line_to_process = item.get("content")  # Campo 'content' en lugar de 'line'
                                timestamp_for_line = item.get("timestamp")
                                line_number = item.get("line_number")
                            elif isinstance(item, str):
                                # Formato antiguo para compatibilidad hacia atrás
                                line_to_process = item
                            
                            if line_to_process:
                                # Crear identificador único usando line_number si está disponible
                                if line_number:
                                    log_identifier = f"{line_number}-{line_to_process}"
                                else:
                                    log_identifier = f"{timestamp_for_line}-{line_to_process}" if timestamp_for_line else line_to_process
                                
                                # Solo procesar si no la hemos visto antes
                                if log_identifier not in self.processed_log_timestamps:
                                    await self.process_log_line(line_to_process, timestamp_for_line)
                                else:
                                    logger.debug(f"[MinecraftCog] Línea ya procesada localmente, saltando: {line_to_process[:50]}...")
                    else:
                        logger.debug("[MinecraftCog] _remote_log_polling_loop: No hay nuevas líneas en la respuesta.")
                        
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
        logger.info("[MinecraftCog] before_remote_log_polling: Esperando que el bot esté listo.")
        await self.bot.wait_until_ready()
        if not self.aiohttp_session or self.aiohttp_session.closed:
            logger.info("[MinecraftCog] before_remote_log_polling: Creando sesión aiohttp inicial.")
            self.aiohttp_session = aiohttp.ClientSession()
        logger.info("⛏️ [MinecraftCog] Tarea de polling de logs lista y sesión aiohttp preparada. Se ejecutará si el puente de chat está activo.")

    @commands.command(name="mcdiag", help="Muestra información de diagnóstico del MinecraftCog.")
    async def text_minecraft_diag(self, ctx: commands.Context):
        logger.info("[MinecraftCog] m.mcdiag: Comando de diagnóstico recibido.")
        diag_message = "🔧 **Diagnóstico de MinecraftCog:**\\n"
        diag_message += f"- `MC_LOG_API_URL` configurado: {bool(self.mc_log_api_url)}\\n"
        diag_message += f"  - Valor (primeros 20 chars): `{self.mc_log_api_url[:20] if self.mc_log_api_url else 'No establecido'}`\\n"
        diag_message += f"- `MC_LOG_API_TOKEN` configurado: {bool(self.mc_log_api_token)}\\n"
        diag_message += f"  - Valor (primeros 5 chars): `{self.mc_log_api_token[:5] + '...' if self.mc_log_api_token else 'No establecido'}`\\n"
        diag_message += f"- `MC_CHAT_CHANNEL_ID` configurado: {self.chat_channel_id if self.chat_channel_id != 0 else 'No establecido (0)'}\\n"
        
        task_running = False
        if hasattr(self, '_remote_log_polling_loop'):
            task_running = self._remote_log_polling_loop.is_running()
        diag_message += f"- Tarea `_remote_log_polling_loop` existe: {hasattr(self, '_remote_log_polling_loop')}\\n"
        diag_message += f"- Tarea `_remote_log_polling_loop` corriendo: {task_running}\\n"
        diag_message += f"- `chat_bridge_active` (flag): {self.chat_bridge_active}\\n"
        
        if hasattr(self, 'aiohttp_session') and self.aiohttp_session:
            diag_message += f"- Sesión `aiohttp_session` cerrada: {self.aiohttp_session.closed}\\n"
        else:
            diag_message += "- Sesión `aiohttp_session`: No inicializada o no existe\\n"
            
        diag_message += "\\n*Intenta `m.mcchat enable` y luego `m.mcdiag` otra vez después de ~10s.*"
        
        logger.info(f"[MinecraftCog] m.mcdiag: Enviando mensaje de diagnóstico:\\n{diag_message}")
        await ctx.send(diag_message)

async def setup(bot):
    cog = MinecraftCog(bot)
    await bot.add_cog(cog)
    logger.info("MinecraftCog añadido al bot y setup completado. cog_load será llamado por discord.py.")
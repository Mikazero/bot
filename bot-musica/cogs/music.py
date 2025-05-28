import discord
from discord.ext import commands
from discord import app_commands
import wavelink
import os
from typing import Optional
import asyncio
from datetime import timedelta, datetime

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self.connect_nodes())
        self.queues = {}
        # Registrar manualmente el evento de wavelink
        bot.add_listener(self.on_wavelink_track_end, "on_wavelink_track_end")
        # Diccionario para controlar temporizadores de desconexión
        self.disconnect_timers = {}
        # Iniciar la tarea de verificación periódica
        self.check_voice_state_task = self.bot.loop.create_task(self.check_voice_state_loop())

    async def connect_nodes(self):
        """Conecta a los nodos de Lavalink"""
        await self.bot.wait_until_ready()

        lavalink_uri = os.environ.get("LAVALINK_URI", "http://127.0.0.1:2333")
        lavalink_password = os.environ.get("LAVALINK_PASSWORD", "youshallnotpass")

        nodes = [
            wavelink.Node(
                uri=lavalink_uri,
                password=lavalink_password,
            )
        ]
        await wavelink.Pool.connect(nodes=nodes, client=self.bot, cache_capacity=100)
        print("Conectado a los nodos de Lavalink")
        
        # Verificar la versión del servidor
        try:
            node = wavelink.Pool.get_node()
            if node:
                print(f"🔗 Servidor Lavalink: {node.uri}")
                print(f"📊 Estado del nodo: {'Conectado' if node.status else 'Desconectado'}")
                # Intentar obtener información del servidor
                if hasattr(node, 'version'):
                    print(f"🏷️ Versión de Lavalink: {node.version}")
        except Exception as e:
            print(f"⚠️ No se pudo obtener información del servidor: {e}")

    def get_queue(self, guild_id: int) -> list[wavelink.Playable]:
        """Obtiene la cola de reproducción del servidor"""
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        return self.queues[guild_id]

    def format_time(self, milliseconds: int) -> str:
        """Formatea el tiempo en milisegundos a formato legible"""
        if milliseconds is None:
            return "N/A"
        return str(timedelta(milliseconds=milliseconds)).split('.')[0]

    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """Evento que se dispara cuando termina una canción"""
        print(f"Evento on_wavelink_track_end disparado: {payload.reason}")
        
        player = payload.player
        if not player:
            print("No se encontró el player")
            return

        # Verificar que el guild existe para evitar acceder a objetos inválidos
        if not hasattr(player, 'guild') or not player.guild:
            print("El player no tiene guild asociado")
            return

        # Solo reproducir la siguiente canción si la canción actual terminó naturalmente
        # Usar comparaciones en minúsculas para evitar problemas de mayúsculas
        reason_lower = payload.reason.lower() if payload.reason else ""
        
        if reason_lower == "finished":
            print("Canción terminada naturalmente")
            await self.play_next(player)
        elif reason_lower == "replaced":
            print("Canción reemplazada (skip)")
            # No hacemos nada, el skip ya se encarga de reproducir la siguiente
            pass
        elif reason_lower in ["stopped", "ended", "cleanup", "loading_failed"]:
            print(f"Canción terminada por: {payload.reason}")
            # Para casos como STOPPED, ENDED, etc. verificar si debemos reproducir la siguiente
            if self.get_queue(player.guild.id):
                await self.play_next(player)
        else:
            print(f"Canción terminada por otra razón desconocida: {payload.reason}")
            # Para otros casos desconocidos, intentar reproducir la siguiente
            try:
                await self.play_next(player)
            except Exception as e:
                print(f"Error al intentar reproducir siguiente canción: {e}")
                # Si falla, intentar una reconexión si el canal aún existe
                try:
                    if hasattr(player, 'text_channel') and player.text_channel:
                        await player.text_channel.send("⚠️ Hubo un problema con el reproductor. Intentando recuperar...")
                        queue = self.get_queue(player.guild.id)
                        if queue and player.guild.voice_client:
                            await player.guild.voice_client.disconnect()
                            # No reproducimos aquí, solo notificamos para que el usuario inicie manualmente
                            await player.text_channel.send("🔄 Por favor, usa el comando play nuevamente.")
                except Exception as recovery_error:
                    print(f"Error durante la recuperación: {recovery_error}")

    async def play_next(self, player: wavelink.Player):
        """Reproduce la siguiente canción en la cola"""
        guild_id = player.guild.id
        queue = self.get_queue(guild_id)
        
        if not queue:
            print("No hay más canciones en la cola")
            # No hay más canciones en la cola
            try:
                if hasattr(player, 'text_channel') and player.text_channel:
                    embed = discord.Embed(
                        title="⏹️ Cola finalizada",
                        description="No hay más canciones en la cola.",
                        color=discord.Color.blue()
                    )
                    await player.text_channel.send(embed=embed)
            except Exception as e:
                print(f"Error al enviar mensaje de cola finalizada: {e}")
            return
        
        try:
            # Tomar la siguiente canción de la cola
            next_track = queue.pop(0)
            print(f"Reproduciendo siguiente canción: {next_track.title}")
            
            # Verificar si el reproductor sigue conectado
            # Usar player.guild.voice_client en lugar de is_connected()
            if not player.guild.voice_client or player.guild.voice_client != player:
                print("El player ya no está conectado")
                if hasattr(player, 'text_channel') and player.text_channel:
                    await player.text_channel.send("❌ El bot se desconectó. Por favor, vuelve a usar el comando play.")
                return
            
            # Intentar reproducir la siguiente canción
            await player.play(next_track)
            
            # Enviar embed informando la nueva canción
            if hasattr(player, 'text_channel') and player.text_channel:
                embed = discord.Embed(
                    title="▶️ Reproduciendo ahora",
                    description=f"**{next_track.title}**\nDuración: {self.format_time(next_track.length)}",
                    color=discord.Color.blue()
                )
                try:
                    await player.text_channel.send(embed=embed)
                except discord.HTTPException as e:
                    print(f"Error al enviar mensaje de reproducción: {e}")
        except Exception as e:
            print(f"Error al reproducir la siguiente canción: {e}")
            # Intentar con la siguiente canción si hay error
            if queue:
                print("Intentando con la siguiente canción debido a un error")
                await self.play_next(player)

    @commands.command(name="play")
    async def play_(self, ctx: commands.Context, *, search: str):
        if not ctx.author.voice:
            await ctx.send("❌ Debes estar en un canal de voz para usar este comando.")
            return

        player: wavelink.Player
        if not ctx.voice_client:
            try:
                player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
                player.text_channel = ctx.channel  # Establecer el canal de texto al crear el player
            except Exception as e:
                await ctx.send(f"❌ Error al conectar al canal de voz: {e}")
                return
        else:
            player = ctx.voice_client
            player.text_channel = ctx.channel  # Actualizar el canal de texto si el player ya existe

        embed_color = discord.Color.blue()
        embed = discord.Embed(title="⏳ Buscando...", description=f"Buscando: `{search}`", color=embed_color)
        msg = await ctx.send(embed=embed)

        try:
            results: wavelink.Playlist | list[wavelink.Playable] | None = await wavelink.Playable.search(search)
            
            if not results:
                await msg.edit(embed=discord.Embed(title="❌ No se encontraron resultados.", description=f"No pude encontrar nada para: `{search}`", color=discord.Color.red()))
                return

            queue = self.get_queue(ctx.guild.id)

            if isinstance(results, wavelink.Playlist):
                playlist = results
                if not playlist.tracks:
                    await msg.edit(embed=discord.Embed(title=f"❌ La playlist '{playlist.name}' está vacía o no se pudo cargar.", color=discord.Color.red()))
                    return

                tracks_from_playlist = playlist.tracks
                num_tracks = len(tracks_from_playlist)
                playlist_name = playlist.name if playlist.name else "Playlist sin nombre"

                if player.current: # Player is busy
                    for track_in_playlist in tracks_from_playlist:
                        queue.append(track_in_playlist)
                    embed = discord.Embed(
                        title="🎵 Playlist añadida a la cola",
                        description=f"Se añadieron {num_tracks} canciones de **{playlist_name}** a la cola.",
                        color=embed_color
                    )
                    await msg.edit(embed=embed)
                else: # Player is idle, play first and queue rest
                    first_track = tracks_from_playlist[0]
                    await player.play(first_track)
                    
                    desc = f"Empezando con: **{first_track.title}** ({self.format_time(first_track.length)})"
                    for track_in_playlist in tracks_from_playlist[1:]:
                        queue.append(track_in_playlist)
                    
                    if num_tracks > 1:
                        desc += f"\n{num_tracks - 1} más canciones de **{playlist_name}** añadidas a la cola."

                    embed = discord.Embed(
                        title=f"▶️ Reproduciendo playlist: {playlist_name}",
                        description=desc,
                        color=embed_color
                    )
                    await msg.edit(embed=embed)

            elif isinstance(results, list): # List of Playable tracks
                track: wavelink.Playable = results[0] # Take the first result
                
                if player.current:
                    queue.append(track)
                    embed = discord.Embed(
                        title="🎵 Añadida a la cola",
                        description=f"**{track.title}**\nDuración: {self.format_time(track.length)}",
                        color=embed_color
                    )
                    await msg.edit(embed=embed)
                else:
                    await player.play(track)
                    embed = discord.Embed(
                        title="▶️ Reproduciendo",
                        description=f"**{track.title}**\nDuración: {self.format_time(track.length)}",
                        color=embed_color
                    )
                    await msg.edit(embed=embed)
            else: 
                await msg.edit(embed=discord.Embed(title="❌ Formato de resultado inesperado.", color=discord.Color.red()))
                return

        except Exception as e:
            await msg.edit(embed=discord.Embed(title="❌ Error", description=f"Ocurrió un error: {str(e)}", color=discord.Color.red()))
            print(f"Error en play: {e}")

    @commands.command(name="stop")
    async def stop_(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client
        if not player:
            await ctx.send("❌ No estoy reproduciendo música.")
            return

        # Guardar referencia al canal para enviar el mensaje después de desconectar
        text_channel = ctx.channel
        guild_id = ctx.guild.id
        
        # Limpiar la cola antes de desconectar
        if guild_id in self.queues:
            self.queues[guild_id] = []
            
        # Desconectar el reproductor    
        await player.disconnect()
        
        embed = discord.Embed(title="⏹️ Música detenida", color=discord.Color.blue())
        await text_channel.send(embed=embed)

    @commands.command(name="pause")
    async def pause_(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client
        if not player or not player.current:
            await ctx.send("❌ No hay música reproduciéndose para pausar.")
            return

        if player.paused:
            await ctx.send("❌ La música ya está pausada.")
            return

        await player.pause(True)
        embed = discord.Embed(title="⏸️ Música pausada", color=discord.Color.blue())
        await ctx.send(embed=embed)

    @commands.command(name="resume")
    async def resume_(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client
        if not player or not player.current:
            await ctx.send("❌ No hay música pausada para reanudar.")
            return

        if not player.paused:
            await ctx.send("❌ La música no está pausada.")
            return

        await player.pause(False)
        embed = discord.Embed(title="▶️ Música reanudada", color=discord.Color.blue())
        await ctx.send(embed=embed)

    @commands.command(name="skip")
    async def skip_(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client
        if not player or not player.current:
            await ctx.send("❌ No hay música reproduciéndose para saltar.")
            return

        queue = self.get_queue(ctx.guild.id)
        
        # Guardar canal para enviar mensaje después de stop
        text_channel = ctx.channel
        
        if queue:
            try:
                next_track = queue.pop(0)
                print(f"Saltando a la siguiente canción: {next_track.title}")
                
                # Comprobar que el player sigue conectado antes de reproducir
                if not ctx.voice_client or ctx.voice_client != player:
                    await ctx.send("❌ Se perdió la conexión con el canal de voz.")
                    return
                    
                await player.play(next_track)
                embed = discord.Embed(title="⏭️ Canción saltada, reproduciendo la siguiente.", description=f"Ahora reproduciendo: **{next_track.title}**", color=discord.Color.blue())
                await text_channel.send(embed=embed)
            except Exception as e:
                print(f"Error al saltar a la siguiente canción: {e}")
                await ctx.send("❌ Ocurrió un error al intentar reproducir la siguiente canción.")
                # Intentar detener la reproducción actual si hubo error
                try:
                    await player.stop()
                except:
                    pass
        else:
            print("No hay más canciones para saltar")
            try:
                await player.stop()
                embed = discord.Embed(title="⏭️ Canción saltada. No hay más canciones en la cola.", color=discord.Color.blue())
                await text_channel.send(embed=embed)
            except Exception as e:
                print(f"Error al detener la reproducción: {e}")
                await ctx.send("❌ Ocurrió un error al intentar detener la reproducción.")

    @commands.command(name="queue")
    async def queue_(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client
        if not player:
            await ctx.send("❌ No estoy conectado a un canal de voz.")
            return

        queue = self.get_queue(ctx.guild.id)
        current_track = player.current

        if not current_track and not queue:
            await ctx.send("❌ No hay canciones en la cola ni reproduciéndose.")
            return
        
        embed = discord.Embed(title="🎵 Cola de reproducción", color=discord.Color.blue())
        
        if current_track:
            embed.add_field(
                name="▶️ Reproduciendo ahora",
                value=f"**{current_track.title}**\nDuración: {self.format_time(current_track.length)}",
                inline=False
            )

        if queue:
            total_duration = sum(track.length for track in queue if track.length is not None)
            queue_text = ""
            for i, track in enumerate(queue[:10], 1):
                queue_text += f"{i}. **{track.title}** - {self.format_time(track.length)}\n"
            
            if len(queue) > 10:
                queue_text += f"\n...y {len(queue) - 10} canciones más"
            
            embed.add_field(
                name="📋 Próximas canciones",
                value=queue_text if queue_text else "Nada más en la cola.",
                inline=False
            )
            if total_duration > 0:
                embed.add_field(
                    name="⏱️ Duración total de la cola",
                    value=self.format_time(total_duration),
                    inline=False
                )
        elif not current_track:
            embed.description = "La cola está vacía y nada se está reproduciendo."

        await ctx.send(embed=embed)

    @commands.command(name="info", aliases=['np', 'nowplaying'])
    async def info_(self, ctx: commands.Context):
        """Muestra información sobre la canción que se está reproduciendo actualmente."""
        player: wavelink.Player | None = ctx.voice_client
        embed_color = discord.Color.blue() # O config.EMBED_COLOR

        if not player or not player.current:
            embed = discord.Embed(
                title="ℹ️ Información", 
                description="No hay ninguna canción reproduciéndose actualmente.", 
                color=embed_color
            )
            await ctx.send(embed=embed)
            return

        track: wavelink.Playable = player.current
        position = self.format_time(player.position)
        duration = self.format_time(track.length)
        
        description_lines = []
        if track.author and track.author != "Unknown Artist":
            description_lines.append(f"**Artista:** {track.author}")
        
        description_lines.append(f"**Duración:** {position} / {duration}")
        
        if track.uri:
            description_lines.append(f"**Fuente:** [Click aquí]({track.uri})")
        else:
            description_lines.append("**Fuente:** No disponible")

        embed = discord.Embed(
            title=f"▶️ Reproduciendo ahora: {track.title}",
            description="\n".join(description_lines),
            color=embed_color
        )

        if hasattr(track, 'artwork') and track.artwork:
            embed.set_thumbnail(url=track.artwork)
        elif hasattr(track, 'album') and hasattr(track.album, 'artwork') and track.album.artwork: # Para algunas fuentes como Spotify
             embed.set_thumbnail(url=track.album.artwork)


        await ctx.send(embed=embed)

    # Slash commands
    @app_commands.command(name="play", description="Reproduce música de YouTube o Spotify!")
    async def play_slash(self, interaction: discord.Interaction, search: str):
        mock_message = discord.Object(id=interaction.id)
        mock_message.author = interaction.user
        mock_message.channel = interaction.channel
        mock_message.guild = interaction.guild
        ctx = await self.bot.get_context(mock_message)
        ctx.voice_client = interaction.guild.voice_client
        await self.play_(ctx, search=search)

    @app_commands.command(name="stop", description="Detén la música.")
    async def stop_slash(self, interaction: discord.Interaction):
        mock_message = discord.Object(id=interaction.id)
        mock_message.author = interaction.user
        mock_message.channel = interaction.channel
        mock_message.guild = interaction.guild
        ctx = await self.bot.get_context(mock_message)
        ctx.voice_client = interaction.guild.voice_client
        await self.stop_(ctx)

    @app_commands.command(name="pause", description="Pausa la música.")
    async def pause_slash(self, interaction: discord.Interaction):
        mock_message = discord.Object(id=interaction.id)
        mock_message.author = interaction.user
        mock_message.channel = interaction.channel
        mock_message.guild = interaction.guild
        ctx = await self.bot.get_context(mock_message)
        ctx.voice_client = interaction.guild.voice_client
        await self.pause_(ctx)

    @app_commands.command(name="resume", description="Reanuda la música pausada.")
    async def resume_slash(self, interaction: discord.Interaction):
        mock_message = discord.Object(id=interaction.id)
        mock_message.author = interaction.user
        mock_message.channel = interaction.channel
        mock_message.guild = interaction.guild
        ctx = await self.bot.get_context(mock_message)
        ctx.voice_client = interaction.guild.voice_client
        await self.resume_(ctx)

    @app_commands.command(name="skip", description="Salta la canción actual.")
    async def skip_slash(self, interaction: discord.Interaction):
        mock_message = discord.Object(id=interaction.id)
        mock_message.author = interaction.user
        mock_message.channel = interaction.channel
        mock_message.guild = interaction.guild
        ctx = await self.bot.get_context(mock_message)
        ctx.voice_client = interaction.guild.voice_client
        await self.skip_(ctx)

    @app_commands.command(name="queue", description="Muestra la cola de reproducción.")
    async def queue_slash(self, interaction: discord.Interaction):
        mock_message = discord.Object(id=interaction.id)
        mock_message.author = interaction.user
        mock_message.channel = interaction.channel
        mock_message.guild = interaction.guild
        ctx = await self.bot.get_context(mock_message)
        ctx.voice_client = interaction.guild.voice_client
        await self.queue_(ctx)

    @commands.command(name="lavalink")
    async def lavalink_info(self, ctx: commands.Context):
        """Muestra información sobre el servidor Lavalink"""
        try:
            node = wavelink.Pool.get_node()
            if not node:
                await ctx.send("❌ No hay nodos de Lavalink conectados.")
                return
            
            embed = discord.Embed(
                title="🔗 Información de Lavalink",
                color=discord.Color.blue()
            )
            
            embed.add_field(name="🌐 URI", value=node.uri, inline=False)
            embed.add_field(name="📊 Estado", value="🟢 Conectado" if node.status else "🔴 Desconectado", inline=True)
            
            if hasattr(node, 'version') and node.version:
                embed.add_field(name="🏷️ Versión", value=node.version, inline=True)
            else:
                embed.add_field(name="🏷️ Versión", value="No disponible", inline=True)
                
            if hasattr(node, 'players'):
                embed.add_field(name="🎵 Reproductores activos", value=len(node.players), inline=True)
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error al obtener información de Lavalink: {e}")

    async def check_voice_state_loop(self):
        """Tarea de verificación periódica del estado de los canales de voz"""
        await self.bot.wait_until_ready()
        try:
            while not self.bot.is_closed():
                for guild in self.bot.guilds:
                    # Comprobar si el bot está en un canal de voz
                    if not guild.voice_client or not isinstance(guild.voice_client, wavelink.Player):
                        continue
                    
                    player = guild.voice_client
                    channel = player.channel
                    
                    # Si no hay canal (extraño pero posible), continuar
                    if not channel:
                        continue
                    
                    # Contar miembros humanos en el canal de voz
                    human_members = [m for m in channel.members if not m.bot]
                    
                    # Si está reproduciendo activamente música, resetear cualquier temporizador
                    if player.current:
                        if guild.id in self.disconnect_timers:
                            # Cancelar temporizador si existe
                            self.disconnect_timers[guild.id].cancel()
                            self.disconnect_timers.pop(guild.id, None)
                        continue
                    
                    # Caso 1: Bot solo en el canal - esperar 5 minutos
                    if len(human_members) == 0:
                        if guild.id not in self.disconnect_timers:
                            print(f"Bot solo en el canal de voz en {guild.name}. Programando desconexión en 5 minutos.")
                            self.disconnect_timers[guild.id] = self.bot.loop.create_task(
                                self.disconnect_after(player, 5 * 60, guild.id)
                            )
                    
                    # Caso 2: Bot con otros usuarios pero sin reproducir - esperar 15 minutos
                    elif not player.current:
                        if guild.id not in self.disconnect_timers:
                            print(f"Bot inactivo con usuarios en el canal en {guild.name}. Programando desconexión en 15 minutos.")
                            self.disconnect_timers[guild.id] = self.bot.loop.create_task(
                                self.disconnect_after(player, 15 * 60, guild.id)
                            )
                
                # Esperar 30 segundos antes de la próxima verificación
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error en la tarea de verificación de canales de voz: {e}")

    async def disconnect_after(self, player: wavelink.Player, seconds: int, guild_id: int):
        """Desconecta al bot después de un tiempo determinado si no se reanuda la reproducción"""
        try:
            # Esperar el tiempo especificado
            await asyncio.sleep(seconds)
            
            # Verificar si el bot sigue conectado y si sigue sin reproducir
            if (player.guild and player.guild.voice_client == player and 
                not player.current):
                
                # Enviar mensaje si hay un canal de texto asociado
                if hasattr(player, 'text_channel') and player.text_channel:
                    try:
                        minutes = seconds // 60
                        embed = discord.Embed(
                            title="🎵 Desconexión automática",
                            description=f"Me he desconectado después de {minutes} minutos de inactividad.",
                            color=discord.Color.blue(),
                            timestamp=datetime.now()
                        )
                        await player.text_channel.send(embed=embed)
                    except Exception as e:
                        print(f"Error al enviar mensaje de desconexión: {e}")
                
                # Limpiar cola
                if guild_id in self.queues:
                    self.queues[guild_id] = []
                
                # Desconectar
                await player.disconnect()
                print(f"Bot desconectado por inactividad en servidor {guild_id}")
            
        except asyncio.CancelledError:
            # Tarea cancelada - probablemente porque se reanudó la música
            pass
        except Exception as e:
            print(f"Error en temporizador de desconexión: {e}")
        finally:
            # Limpiar referencia del temporizador
            self.disconnect_timers.pop(guild_id, None)

    def cog_unload(self):
        """Limpieza al descargar el cog"""
        # Cancelar tareas programadas
        if hasattr(self, 'check_voice_state_task') and self.check_voice_state_task:
            self.check_voice_state_task.cancel()
        
        # Cancelar todos los temporizadores de desconexión
        for timer in self.disconnect_timers.values():
            timer.cancel()
        self.disconnect_timers.clear()

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
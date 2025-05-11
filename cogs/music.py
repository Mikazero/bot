import discord
from discord.ext import commands
from discord import app_commands
import wavelink
import config
from typing import Optional
import asyncio
from datetime import timedelta
import os

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.loop.create_task(self.connect_nodes())
        self.queues = {}

    async def connect_nodes(self):
        """Conecta a los nodos de Lavalink"""
        await self.bot.wait_until_ready()
        nodes = [
            wavelink.Node(
                uri="http://127.0.0.1:2333",
                password="youshallnotpass",
            )
        ]
        await wavelink.Pool.connect(nodes=nodes, client=self.bot, cache_capacity=100)

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

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """Evento que se dispara cuando termina una canción"""
        player: wavelink.Player | None = payload.player
        if not player:
            return

        queue = self.get_queue(player.guild.id)
        if queue:
            next_track = queue.pop(0)
            await player.play(next_track)
        # else:
            # Optionally, handle player disconnect or stay connected.
            # await player.disconnect() # Desconectar si la cola está vacía

    @commands.command(name="play")
    async def play_(self, ctx: commands.Context, *, search: str):
        if not ctx.author.voice:
            await ctx.send("❌ Debes estar en un canal de voz para usar este comando.")
            return

        player: wavelink.Player
        if not ctx.voice_client:
            try:
                player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
            except Exception as e:
                await ctx.send(f"❌ Error al conectar al canal de voz: {e}")
                return
        else:
            player = ctx.voice_client

        embed = discord.Embed(title="⏳ Buscando música...", description=search, color=config.EMBED_COLOR)
        msg = await ctx.send(embed=embed)

        try:
            tracks: list[wavelink.Playable] | None = await wavelink.Playable.search(search)
            if not tracks:
                await msg.edit(embed=discord.Embed(title="❌ No se encontraron resultados", color=config.EMBED_COLOR))
                return

            track: wavelink.Playable = tracks[0]
            
            queue = self.get_queue(ctx.guild.id)

            if player.current:
                queue.append(track)
                embed = discord.Embed(
                    title="🎵 Añadida a la cola",
                    description=f"**{track.title}**\nDuración: {self.format_time(track.length)}",
                    color=config.EMBED_COLOR
                )
                await msg.edit(embed=embed)
            else:
                await player.play(track)
                embed = discord.Embed(
                    title="▶️ Reproduciendo",
                    description=f"**{track.title}**\nDuración: {self.format_time(track.length)}",
                    color=config.EMBED_COLOR
                )
                await msg.edit(embed=embed)

        except Exception as e:
            await msg.edit(embed=discord.Embed(title="❌ Error", description=str(e), color=config.EMBED_COLOR))
            print(f"Error en play: {e}")

    @commands.command(name="stop")
    async def stop_(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client
        if not player:
            await ctx.send("❌ No estoy reproduciendo música.")
            return

        await player.disconnect()
        if ctx.guild.id in self.queues:
            self.queues[ctx.guild.id] = []
        
        embed = discord.Embed(title="⏹️ Música detenida", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

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
        embed = discord.Embed(title="⏸️ Música pausada", color=config.EMBED_COLOR)
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
        embed = discord.Embed(title="▶️ Música reanudada", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="skip")
    async def skip_(self, ctx: commands.Context):
        player: wavelink.Player | None = ctx.voice_client
        if not player or not player.current:
            await ctx.send("❌ No hay música reproduciéndose para saltar.")
            return

        queue = self.get_queue(ctx.guild.id)
        if queue:
            next_track = queue.pop(0)
            await player.play(next_track)
            embed = discord.Embed(title="⏭️ Canción saltada, reproduciendo la siguiente.", description=f"Ahora reproduciendo: **{next_track.title}**", color=config.EMBED_COLOR)
        else:
            await player.stop()
            embed = discord.Embed(title="⏭️ Canción saltada. No hay más canciones en la cola.", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

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
        
        embed = discord.Embed(title="🎵 Cola de reproducción", color=config.EMBED_COLOR)
        
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

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
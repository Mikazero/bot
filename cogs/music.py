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
        node = wavelink.Node(
            uri=f"http://{os.getenv('LAVALINK_HOST', '127.0.0.1')}:{os.getenv('LAVALINK_PORT', '2333')}",
            password=os.getenv('LAVALINK_PASSWORD', 'youshallnotpass')
        )
        await wavelink.NodePool.connect(client=self.bot, nodes=[node])

    def get_queue(self, guild_id: int) -> list:
        """Obtiene la cola de reproducción del servidor"""
        if guild_id not in self.queues:
            self.queues[guild_id] = []
        return self.queues[guild_id]

    def format_time(self, milliseconds: int) -> str:
        """Formatea el tiempo en milisegundos a formato legible"""
        return str(timedelta(milliseconds=milliseconds)).split('.')[0]

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackEndEventPayload):
        """Evento que se dispara cuando termina una canción"""
        if not payload.player:
            return

        queue = self.get_queue(payload.player.guild.id)
        if queue:
            next_track = queue.pop(0)
            await payload.player.play(next_track)
        else:
            await payload.player.disconnect()

    @commands.command(name="play")
    async def play_(self, ctx, *, search: str):
        if not ctx.author.voice:
            await ctx.send("❌ Debes estar en un canal de voz para usar este comando.")
            return

        if not ctx.voice_client:
            vc: wavelink.Player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
        else:
            vc: wavelink.Player = ctx.voice_client

        embed = discord.Embed(title="⏳ Buscando música...", description=search, color=config.EMBED_COLOR)
        msg = await ctx.send(embed=embed)

        try:
            tracks = await wavelink.NodePool.get_node().get_tracks(query=search)
            if not tracks:
                await msg.edit(embed=discord.Embed(title="❌ No se encontraron resultados", color=config.EMBED_COLOR))
                return

            track = tracks[0]
            queue = self.get_queue(ctx.guild.id)

            if vc.is_playing():
                queue.append(track)
                embed = discord.Embed(
                    title="🎵 Añadida a la cola",
                    description=f"**{track.title}**\nDuración: {self.format_time(track.duration)}",
                    color=config.EMBED_COLOR
                )
                await msg.edit(embed=embed)
            else:
                await vc.play(track)
                embed = discord.Embed(
                    title="▶️ Reproduciendo",
                    description=f"**{track.title}**\nDuración: {self.format_time(track.duration)}",
                    color=config.EMBED_COLOR
                )
                await msg.edit(embed=embed)

        except Exception as e:
            await msg.edit(embed=discord.Embed(title="❌ Error", description=str(e), color=config.EMBED_COLOR))

    @commands.command(name="stop")
    async def stop_(self, ctx):
        if not ctx.voice_client:
            await ctx.send("❌ No estoy reproduciendo música.")
            return

        vc: wavelink.Player = ctx.voice_client
        await vc.disconnect()
        self.queues[ctx.guild.id] = []
        
        embed = discord.Embed(title="⏹️ Música detenida", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="pause")
    async def pause_(self, ctx):
        if not ctx.voice_client:
            await ctx.send("❌ No estoy reproduciendo música.")
            return

        vc: wavelink.Player = ctx.voice_client
        if vc.is_paused():
            await ctx.send("❌ La música ya está pausada.")
            return

        await vc.pause()
        embed = discord.Embed(title="⏸️ Música pausada", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="resume")
    async def resume_(self, ctx):
        if not ctx.voice_client:
            await ctx.send("❌ No estoy reproduciendo música.")
            return

        vc: wavelink.Player = ctx.voice_client
        if not vc.is_paused():
            await ctx.send("❌ La música no está pausada.")
            return

        await vc.resume()
        embed = discord.Embed(title="▶️ Música reanudada", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="skip")
    async def skip_(self, ctx):
        if not ctx.voice_client:
            await ctx.send("❌ No estoy reproduciendo música.")
            return

        vc: wavelink.Player = ctx.voice_client
        if not vc.is_playing():
            await ctx.send("❌ No hay música reproduciéndose.")
            return

        await vc.stop()
        embed = discord.Embed(title="⏭️ Canción saltada", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="queue")
    async def queue_(self, ctx):
        if not ctx.voice_client:
            await ctx.send("❌ No estoy reproduciendo música.")
            return

        queue = self.get_queue(ctx.guild.id)
        if not queue and not ctx.voice_client.is_playing():
            await ctx.send("❌ No hay canciones en la cola.")
            return

        embed = discord.Embed(title="🎵 Cola de reproducción", color=config.EMBED_COLOR)
        
        # Canción actual
        if ctx.voice_client.is_playing():
            current = ctx.voice_client.track
            embed.add_field(
                name="▶️ Reproduciendo ahora",
                value=f"**{current.title}**\nDuración: {self.format_time(current.duration)}",
                inline=False
            )

        # Próximas canciones
        if queue:
            total_duration = sum(track.duration for track in queue)
            queue_text = ""
            for i, track in enumerate(queue[:10], 1):
                queue_text += f"{i}. **{track.title}** - {self.format_time(track.duration)}\n"
            
            if len(queue) > 10:
                queue_text += f"\n...y {len(queue) - 10} canciones más"
            
            embed.add_field(
                name="📋 Próximas canciones",
                value=queue_text,
                inline=False
            )
            embed.add_field(
                name="⏱️ Duración total",
                value=self.format_time(total_duration),
                inline=False
            )

        await ctx.send(embed=embed)

    # Slash commands
    @app_commands.command(name="play", description="Reproduce música de YouTube o Spotify!")
    async def play_slash(self, interaction: discord.Interaction, search: str):
        ctx = await self.bot.get_context(interaction)
        await self.play_(ctx, search=search)

    @app_commands.command(name="stop", description="Detén la música.")
    async def stop_slash(self, interaction: discord.Interaction):
        ctx = await self.bot.get_context(interaction)
        await self.stop_(ctx)

    @app_commands.command(name="pause", description="Pausa la música.")
    async def pause_slash(self, interaction: discord.Interaction):
        ctx = await self.bot.get_context(interaction)
        await self.pause_(ctx)

    @app_commands.command(name="resume", description="Reanuda la música pausada.")
    async def resume_slash(self, interaction: discord.Interaction):
        ctx = await self.bot.get_context(interaction)
        await self.resume_(ctx)

    @app_commands.command(name="skip", description="Salta la canción actual.")
    async def skip_slash(self, interaction: discord.Interaction):
        ctx = await self.bot.get_context(interaction)
        await self.skip_(ctx)

    @app_commands.command(name="queue", description="Muestra la cola de reproducción.")
    async def queue_slash(self, interaction: discord.Interaction):
        ctx = await self.bot.get_context(interaction)
        await self.queue_(ctx)

async def setup(bot):
    await bot.add_cog(Music(bot))
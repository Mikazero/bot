import discord
from discord.ext import commands
from discord import app_commands
import wavelink
import config

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="play")
    async def play_(self, ctx, *, search: str):
        embed = discord.Embed(title="⏳ Buscando música...", description=search, color=config.EMBED_COLOR)
        await ctx.send(embed=embed)
        # Lógica de música se agrega después

    @commands.command(name="stop")
    async def stop_(self, ctx):
        embed = discord.Embed(title="⏹️ Música detenida", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="pause")
    async def pause_(self, ctx):
        embed = discord.Embed(title="⏸️ Música pausada (placeholder)", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="resume")
    async def resume_(self, ctx):
        embed = discord.Embed(title="▶️ Música reanudada (placeholder)", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="skip")
    async def skip_(self, ctx):
        embed = discord.Embed(title="⏭️ Canción saltada (placeholder)", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="queue")
    async def queue_(self, ctx):
        embed = discord.Embed(title="🎵 Cola de canciones (placeholder)", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    # Slash commands equivalentes
    @app_commands.command(name="play", description="Reproduce música de YouTube o Spotify!")
    async def play_slash(self, interaction: discord.Interaction, search: str):
        embed = discord.Embed(title="⏳ Buscando música...", description=search, color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="stop", description="Detén la música.")
    async def stop_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⏹️ Música detenida", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pause", description="Pausa la música.")
    async def pause_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⏸️ Música pausada (placeholder)", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="resume", description="Reanuda la música pausada.")
    async def resume_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="▶️ Música reanudada (placeholder)", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="skip", description="Salta la canción actual.")
    async def skip_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⏭️ Canción saltada (placeholder)", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="queue", description="Muestra la cola de reproducción.")
    async def queue_slash(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🎵 Cola de canciones (placeholder)", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Music(bot))
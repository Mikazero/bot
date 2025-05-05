import discord
from discord.ext import commands
from discord import app_commands
import config
import asyncio

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = None):
        await member.kick(reason=reason)
        embed = discord.Embed(title="🚪 Usuario expulsado", description=f"{member.mention} fue expulsado.\nMotivo: {reason}", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = None):
        await member.ban(reason=reason)
        embed = discord.Embed(title="🔨 Usuario baneado", description=f"{member.mention} fue baneado.\nMotivo: {reason}", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="mute")
    @commands.has_permissions(manage_roles=True)
    async def mute(self, ctx, member: discord.Member, time: int = 0):
        # Placeholder (añadir role 'Muted')
        embed = discord.Embed(title="🔇 Mute (placeholder)", description=f"{member.mention} fue muteado por {time}s.", color=config.EMBED_COLOR)
        await ctx.send(embed=embed)

    @commands.command(name="purge")
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int = 5):
        deleted = await ctx.channel.purge(limit=amount)
        embed = discord.Embed(title="🧹 Mensajes eliminados", description=f"{len(deleted)} mensajes borrados.", color=config.EMBED_COLOR)
        await ctx.send(embed=embed, delete_after=5)

    # Slash commands
    @app_commands.command(name="kick", description="Expulsa a un usuario del servidor.")
    @app_commands.describe(user="Usuario a expulsar", reason="Motivo")
    async def kick_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = ""):
        await user.kick(reason=reason)
        embed = discord.Embed(title="🚪 Usuario expulsado", description=f"{user.mention} fue expulsado.\nMotivo: {reason}", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="Banea a un usuario del servidor.")
    @app_commands.describe(user="Usuario a banear", reason="Motivo")
    async def ban_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = ""):
        await user.ban(reason=reason)
        embed = discord.Embed(title="🔨 Usuario baneado", description=f"{user.mention} fue baneado.\nMotivo: {reason}", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mute", description="Mutea a un usuario (no implementado completamente)")
    @app_commands.describe(user="Usuario a mutear", duration="Duración en segundos")
    async def mute_slash(self, interaction: discord.Interaction, user: discord.Member, duration: int = 0):
        embed = discord.Embed(title="🔇 Mute (placeholder)", description=f"{user.mention} fue muteado por {duration}s.", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="purge", description="Elimina mensajes del canal actual.")
    @app_commands.describe(amount="Cantidad de mensajes")
    async def purge_slash(self, interaction: discord.Interaction, amount: int = 5):
        deleted = await interaction.channel.purge(limit=amount)
        embed = discord.Embed(title="🧹 Mensajes eliminados", description=f"{len(deleted)} mensajes borrados.", color=config.EMBED_COLOR)
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
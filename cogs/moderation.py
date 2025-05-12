import discord
from discord.ext import commands
from discord import app_commands
import config
import asyncio
from datetime import datetime, timedelta
import re # Añadido para parsear la duración

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.muted_users = {}

    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = None):
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ No puedes expulsar a alguien con un rol igual o superior al tuyo.")
            return
        
        try:
            await member.send(f"Has sido expulsado de {ctx.guild.name}\nMotivo: {reason}")
        except:
            pass  # Si no se puede enviar DM, continuamos

        await member.kick(reason=reason)
        embed = discord.Embed(
            title="🚪 Usuario expulsado",
            description=f"{member.mention} fue expulsado.\nMotivo: {reason}",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Expulsado por {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="ban")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, member: discord.Member, *, reason: str = None):
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ No puedes banear a alguien con un rol igual o superior al tuyo.")
            return

        try:
            await member.send(f"Has sido baneado de {ctx.guild.name}\nMotivo: {reason}")
        except:
            pass

        await member.ban(reason=reason)
        embed = discord.Embed(
            title="🔨 Usuario baneado",
            description=f"{member.mention} fue baneado.\nMotivo: {reason}",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Baneado por {ctx.author}")
        await ctx.send(embed=embed)

    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: int):
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user)
            embed = discord.Embed(
                title="🔓 Usuario desbaneado",
                description=f"{user.mention} ha sido desbaneado.",
                color=config.EMBED_COLOR,
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Desbaneado por {ctx.author}")
            await ctx.send(embed=embed)
        except:
            await ctx.send("❌ No se pudo encontrar al usuario o no está baneado.")

    @commands.command(name="mute")
    @commands.has_permissions(manage_roles=True)
    async def mute(self, ctx, member: discord.Member, *time_and_reason_parts):
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ No puedes mutear a alguien con un rol igual o superior al tuyo.")
            return
        if member == ctx.guild.me:
            await ctx.send("❌ No me puedo mutear a mí mismo.")
            return

        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if not muted_role:
            try:
                muted_role = await ctx.guild.create_role(name="Muted", reason="Rol para usuarios muteados")
                for channel in ctx.guild.text_channels:
                    await channel.set_permissions(muted_role, send_messages=False, reason="Configuración del rol Muted")
                for channel in ctx.guild.voice_channels:
                    await channel.set_permissions(muted_role, speak=False, reason="Configuración del rol Muted")
            except discord.Forbidden:
                await ctx.send("❌ No tengo permisos para crear o configurar el rol 'Muted'. Revisa mis permisos.")
                return
            except Exception as e:
                await ctx.send(f"❌ Ocurrió un error al crear/configurar el rol 'Muted': {e}")
                return

        duration_seconds = 10 * 60  # Default 10 minutos
        human_readable_duration = "10 minutos"
        reason = None
        
        args_list = list(time_and_reason_parts)
        reason_parts_list = []

        if not args_list:
            # No time/reason provided, use default 10 minutes, reason is None
            pass
        else:
            first_arg = args_list[0]
            potential_reason_args = args_list[1:]

            # Regex corregidas para usar \d+ directamente
            match_combined = re.fullmatch(r"(\d+)([mhds])", first_arg, re.IGNORECASE)
            match_numeric = re.fullmatch(r"(\d+)", first_arg)

            parsed_time_successfully = False
            if match_combined:
                value = int(match_combined.group(1))
                unit = match_combined.group(2).lower()
                if unit == 's':
                    duration_seconds = value
                    human_readable_duration = f"{value} segundo" if value == 1 else f"{value} segundos"
                elif unit == 'm':
                    duration_seconds = value * 60
                    human_readable_duration = f"{value} minuto" if value == 1 else f"{value} minutos"
                elif unit == 'h':
                    duration_seconds = value * 3600
                    human_readable_duration = f"{value} hora" if value == 1 else f"{value} horas"
                elif unit == 'd':
                    duration_seconds = value * 86400
                    human_readable_duration = f"{value} día" if value == 1 else f"{value} días"
                reason_parts_list = potential_reason_args # Resto de args son la razón
                parsed_time_successfully = True
            elif match_numeric and potential_reason_args and potential_reason_args[0].lower() in ['s', 'm', 'h', 'd']:
                value = int(match_numeric.group(1))
                unit = potential_reason_args[0].lower()
                reason_parts_list = potential_reason_args[1:] # Resto de args (después de la unidad) son la razón
                if unit == 's':
                    duration_seconds = value
                    human_readable_duration = f"{value} segundo" if value == 1 else f"{value} segundos"
                elif unit == 'm':
                    duration_seconds = value * 60
                    human_readable_duration = f"{value} minuto" if value == 1 else f"{value} minutos"
                elif unit == 'h':
                    duration_seconds = value * 3600
                    human_readable_duration = f"{value} hora" if value == 1 else f"{value} horas"
                elif unit == 'd':
                    duration_seconds = value * 86400
                    human_readable_duration = f"{value} día" if value == 1 else f"{value} días"
                parsed_time_successfully = True
            elif match_numeric: # Solo un número, se interpreta como minutos por defecto
                value = int(match_numeric.group(1))
                duration_seconds = value * 60 
                human_readable_duration = f"{value} minuto" if value == 1 else f"{value} minutos"
                reason_parts_list = potential_reason_args # Resto de args son la razón
                parsed_time_successfully = True
            
            if not parsed_time_successfully: # Si no se parseó tiempo, todos los args son la razón
                reason_parts_list = args_list
            
            if reason_parts_list:
                reason = " ".join(reason_parts_list)

        if muted_role in member.roles and not duration_seconds > 0:
            self.muted_users.pop((member.id, ctx.guild.id), None)
            # Si ya tiene el rol y la nueva duración es indefinida, no hace falta añadirlo de nuevo.
            # Podríamos enviar un mensaje informando que el mute se ha actualizado a indefinido.
        else:
            try:
                await member.add_roles(muted_role, reason=reason)
            except discord.Forbidden:
                await ctx.send(f"❌ No tengo permisos para añadir el rol 'Muted' a {member.mention}.")
                return
            except Exception as e:
                await ctx.send(f"❌ Ocurrió un error al intentar mutear a {member.mention}: {e}")
                return
        
        embed_description = f"{member.mention} fue muteado."
        if reason:
            embed_description += f"\nMotivo: {reason}" # Usar \n para nueva línea
        
        current_mute_marker = object()
        
        if duration_seconds > 0:
            embed_description += f"\nDuración: {human_readable_duration}" # Usar \n para nueva línea
            self.muted_users[(member.id, ctx.guild.id)] = current_mute_marker
        else:
            embed_description += "\nDuración: Indefinida (hasta desmuteo manual, o tiempo 0 especificado)" # Usar \n
            self.muted_users.pop((member.id, ctx.guild.id), None)

        embed = discord.Embed(
            title="🔇 Usuario muteado",
            description=embed_description,
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Muteado por {ctx.author}")
        await ctx.send(embed=embed)

        if duration_seconds > 0:
            await asyncio.sleep(duration_seconds)
            if self.muted_users.get((member.id, ctx.guild.id)) == current_mute_marker:
                # Intentar obtener el miembro actualizado por si acaso
                guild = ctx.guild
                try:
                    member_actual = guild.get_member(member.id)
                    if member_actual is None:
                        # Si el miembro no está en caché, intentar buscarlo
                        member_actual = await guild.fetch_member(member.id)
                except Exception:
                    member_actual = member
                # Llamar al comando unmute para reutilizar la lógica y el embed
                try:
                    await self.unmute(ctx, member_actual)
                except Exception:
                    # Si falla, intentar quitar el rol manualmente como fallback
                    muted_role = discord.utils.get(guild.roles, name="Muted")
                    if muted_role and muted_role in member_actual.roles:
                        try:
                            await member_actual.remove_roles(muted_role, reason="Tiempo de mute expirado (fallback)")
                        except Exception:
                            pass
                self.muted_users.pop((member.id, ctx.guild.id), None)

    @commands.command(name="unmute")
    @commands.has_permissions(manage_roles=True)
    async def unmute(self, ctx, member: discord.Member):
        muted_role = discord.utils.get(ctx.guild.roles, name="Muted")
        if muted_role and muted_role in member.roles:
            try:
                await member.remove_roles(muted_role, reason=f"Desmuteado manualmente por {ctx.author}")
                self.muted_users.pop((member.id, ctx.guild.id), None)
                
                embed = discord.Embed(
                    title="🔊 Usuario desmuteado",
                    description=f"{member.mention} ha sido desmuteado.",
                    color=config.EMBED_COLOR,
                    timestamp=datetime.now()
                )
                embed.set_footer(text=f"Desmuteado por {ctx.author}")
                await ctx.send(embed=embed)
            except discord.Forbidden:
                await ctx.send(f"❌ No tengo permisos para desmutear a {member.mention}.")
            except Exception as e:
                await ctx.send(f"❌ Ocurrió un error al intentar desmutear a {member.mention}: {e}")
        else:
            await ctx.send("❌ Este usuario no está muteado o el rol 'Muted' no existe.")

    @commands.command(name="purge")
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx, amount: int = 5):
        if amount > 100:
            await ctx.send("❌ No puedes eliminar más de 100 mensajes a la vez.")
            return

        deleted = await ctx.channel.purge(limit=amount + 1)  # +1 para incluir el comando
        embed = discord.Embed(
            title="🧹 Mensajes eliminados",
            description=f"{len(deleted)-1} mensajes borrados.",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        msg = await ctx.send(embed=embed)
        await asyncio.sleep(5)
        await msg.delete()

    @commands.command(name="warn")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = None):
        if member.top_role >= ctx.author.top_role:
            await ctx.send("❌ No puedes advertir a alguien con un rol igual o superior al tuyo.")
            return

        embed = discord.Embed(
            title="⚠️ Usuario advertido",
            description=f"{member.mention} ha recibido una advertencia.\nMotivo: {reason}",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Advertido por {ctx.author}")
        await ctx.send(embed=embed)

    # Slash commands
    @app_commands.command(name="kick", description="Expulsa a un usuario del servidor.")
    @app_commands.describe(user="Usuario a expulsar", reason="Motivo de la expulsión")
    async def kick_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = ""):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("❌ No tienes permisos para expulsar usuarios.", ephemeral=True)
            return

        if user.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ No puedes expulsar a alguien con un rol igual o superior al tuyo.", ephemeral=True)
            return

        try:
            await user.send(f"Has sido expulsado de {interaction.guild.name}\nMotivo: {reason}")
        except:
            pass

        await user.kick(reason=reason)
        embed = discord.Embed(
            title="🚪 Usuario expulsado",
            description=f"{user.mention} fue expulsado.\nMotivo: {reason}",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Expulsado por {interaction.user}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="Banea a un usuario del servidor.")
    @app_commands.describe(user="Usuario a banear", reason="Motivo del baneo")
    async def ban_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = ""):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ No tienes permisos para banear usuarios.", ephemeral=True)
            return

        if user.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ No puedes banear a alguien con un rol igual o superior al tuyo.", ephemeral=True)
            return

        try:
            await user.send(f"Has sido baneado de {interaction.guild.name}\nMotivo: {reason}")
        except:
            pass

        await user.ban(reason=reason)
        embed = discord.Embed(
            title="🔨 Usuario baneado",
            description=f"{user.mention} fue baneado.\nMotivo: {reason}",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Baneado por {interaction.user}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unban", description="Desbanea a un usuario del servidor.")
    @app_commands.describe(user_id="ID del usuario a desbanear")
    async def unban_slash(self, interaction: discord.Interaction, user_id: str):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("❌ No tienes permisos para desbanear usuarios.", ephemeral=True)
            return

        try:
            user = await self.bot.fetch_user(int(user_id))
            await interaction.guild.unban(user)
            embed = discord.Embed(
                title="🔓 Usuario desbaneado",
                description=f"{user.mention} ha sido desbaneado.",
                color=config.EMBED_COLOR,
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Desbaneado por {interaction.user}")
            await interaction.response.send_message(embed=embed)
        except:
            await interaction.response.send_message("❌ No se pudo encontrar al usuario o no está baneado.", ephemeral=True)

    @app_commands.command(name="mute", description="Mutea a un usuario temporalmente.")
    @app_commands.describe(user="Usuario a mutear", duration="Duración en segundos", reason="Motivo del mute")
    async def mute_slash(self, interaction: discord.Interaction, user: discord.Member, duration: int = 0, reason: str = ""):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ No tienes permisos para mutear usuarios.", ephemeral=True)
            return

        if user.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ No puedes mutear a alguien con un rol igual o superior al tuyo.", ephemeral=True)
            return

        muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if not muted_role:
            muted_role = await interaction.guild.create_role(name="Muted")
            for channel in interaction.guild.channels:
                await channel.set_permissions(muted_role, speak=False, send_messages=False)

        await user.add_roles(muted_role)
        
        if duration > 0:
            self.muted_users[user.id] = interaction.guild.id
            await asyncio.sleep(duration)
            if user.id in self.muted_users:
                await user.remove_roles(muted_role)
                del self.muted_users[user.id]

        embed = discord.Embed(
            title="🔇 Usuario muteado",
            description=f"{user.mention} fue muteado.\nDuración: {duration}s\nMotivo: {reason}",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Muteado por {interaction.user}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unmute", description="Desmutea a un usuario.")
    @app_commands.describe(user="Usuario a desmutear")
    async def unmute_slash(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("❌ No tienes permisos para desmutear usuarios.", ephemeral=True)
            return

        muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
        if muted_role in user.roles:
            await user.remove_roles(muted_role)
            if user.id in self.muted_users:
                del self.muted_users[user.id]
            embed = discord.Embed(
                title="🔊 Usuario desmuteado",
                description=f"{user.mention} ha sido desmuteado.",
                color=config.EMBED_COLOR,
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"Desmuteado por {interaction.user}")
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ Este usuario no está muteado.", ephemeral=True)

    @app_commands.command(name="purge", description="Elimina mensajes del canal actual.")
    @app_commands.describe(amount="Cantidad de mensajes a eliminar (máximo 100)")
    async def purge_slash(self, interaction: discord.Interaction, amount: int = 5):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ No tienes permisos para eliminar mensajes.", ephemeral=True)
            return

        if amount > 100:
            await interaction.response.send_message("❌ No puedes eliminar más de 100 mensajes a la vez.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        embed = discord.Embed(
            title="🧹 Mensajes eliminados",
            description=f"{len(deleted)} mensajes borrados.",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="warn", description="Advierte a un usuario.")
    @app_commands.describe(user="Usuario a advertir", reason="Motivo de la advertencia")
    async def warn_slash(self, interaction: discord.Interaction, user: discord.Member, reason: str = ""):
        if not interaction.user.guild_permissions.manage_messages:
            await interaction.response.send_message("❌ No tienes permisos para advertir usuarios.", ephemeral=True)
            return

        if user.top_role >= interaction.user.top_role:
            await interaction.response.send_message("❌ No puedes advertir a alguien con un rol igual o superior al tuyo.", ephemeral=True)
            return

        embed = discord.Embed(
            title="⚠️ Usuario advertido",
            description=f"{user.mention} ha recibido una advertencia.\nMotivo: {reason}",
            color=config.EMBED_COLOR,
            timestamp=datetime.now()
        )
        embed.set_footer(text=f"Advertido por {interaction.user}")
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Moderation(bot))
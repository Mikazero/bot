import discord
from discord.ext import commands
from discord import app_commands
import random
from typing import Optional, List, Dict
import asyncio

class BuckshotGame:
    def __init__(self, host: discord.Member):
        self.host = host
        self.players = [host]  # Lista de jugadores
        self.round = 1
        self.player_lives = {}  # Diccionario para las vidas de cada jugador
        self.dealer_lives = 2
        self.shotgun = []
        self.current_chamber = 0
        self.player_items = {}  # Diccionario para los ítems de cada jugador
        self.dealer_items = []
        self.current_player_index = 0  # Índice del jugador actual
        self.game_active = True
        self.game_started = False
        self.saw_active = False
        self.dealer_skips_turn = False

    def add_player(self, player: discord.Member) -> bool:
        """Añade un jugador al juego si hay espacio"""
        if len(self.players) >= 4:
            return False
        if player in self.players:
            return False
        self.players.append(player)
        return True

    def initialize_player(self, player: discord.Member):
        """Inicializa las vidas y ítems de un jugador"""
        self.player_lives[player.id] = 2
        self.player_items[player.id] = []

    def get_current_player(self) -> discord.Member:
        """Obtiene el jugador actual"""
        return self.players[self.current_player_index]

    def next_player(self):
        """Avanza al siguiente jugador"""
        self.current_player_index = (self.current_player_index + 1) % len(self.players)

    def load_shotgun(self):
        """Carga la escopeta con cartuchos aleatorios"""
        total_shells = random.randint(2, 8)
        live_shells = total_shells // 2
        empty_shells = total_shells - live_shells
        
        # Asegurar al menos un cartucho de cada tipo
        if live_shells == 0:
            live_shells = 1
            empty_shells -= 1
        elif empty_shells == 0:
            empty_shells = 1
            live_shells -= 1

        self.shotgun = ['LIVE'] * live_shells + ['EMPTY'] * empty_shells
        random.shuffle(self.shotgun)
        self.current_chamber = 0

    def get_current_shell(self) -> str:
        """Obtiene el tipo de cartucho actual"""
        return self.shotgun[self.current_chamber]

    def next_chamber(self):
        """Avanza al siguiente cartucho"""
        self.current_chamber = (self.current_chamber + 1) % len(self.shotgun)

    def distribute_items(self):
        """Distribuye ítems según la ronda actual"""
        items = ['CIGARETTE', 'BEER', 'SAW', 'MAGNIFYING_GLASS', 'HANDCUFFS', 'EXPIRED_MEDICINE', 'INVERTER']
        if self.round == 2:
            num_items = 2
        elif self.round == 3:
            num_items = 4
        else:
            return

        # Distribuir ítems aleatorios a cada jugador
        for player in self.players:
            self.player_items[player.id] = random.sample(items, num_items)
        self.dealer_items = random.sample(items, num_items)

class Buckshot(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_games: Dict[int, BuckshotGame] = {}

    @commands.command(name="buckshot")
    async def start_game(self, ctx: commands.Context):
        """Inicia una nueva partida de Buckshot Roulette"""
        if ctx.guild.id in self.active_games:
            await ctx.send("❌ Ya hay una partida en curso en este servidor.")
            return

        game = BuckshotGame(ctx.author)
        game.initialize_player(ctx.author)
        self.active_games[ctx.guild.id] = game

        embed = discord.Embed(
            title="🎮 Buckshot Roulette",
            description="¡Se ha creado una nueva partida! Usa `g.jg` para unirte.\nMáximo 4 jugadores.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Jugadores", value=f"1. {ctx.author.mention}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="jg")
    async def join_game(self, ctx: commands.Context):
        """Únete a una partida de Buckshot Roulette"""
        if ctx.guild.id not in self.active_games:
            await ctx.send("❌ No hay ninguna partida en curso en este servidor.")
            return

        game = self.active_games[ctx.guild.id]
        if game.game_started:
            await ctx.send("❌ La partida ya ha comenzado.")
            return

        if game.add_player(ctx.author):
            game.initialize_player(ctx.author)
            players_list = "\n".join([f"{i+1}. {player.mention}" for i, player in enumerate(game.players)])
            embed = discord.Embed(
                title="🎮 Buckshot Roulette",
                description=f"¡{ctx.author.mention} se ha unido a la partida!",
                color=discord.Color.blue()
            )
            embed.add_field(name="Jugadores", value=players_list, inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ No puedes unirte a la partida. Ya estás en ella o está llena.")

    @commands.command(name="start")
    async def start_round(self, ctx: commands.Context):
        """Inicia la ronda cuando todos los jugadores estén listos"""
        if ctx.guild.id not in self.active_games:
            await ctx.send("❌ No hay ninguna partida en curso en este servidor.")
            return

        game = self.active_games[ctx.guild.id]
        if game.game_started:
            await ctx.send("❌ La partida ya ha comenzado.")
            return

        if ctx.author != game.host:
            await ctx.send("❌ Solo el anfitrión puede iniciar la partida.")
            return

        # Si solo está el anfitrión, permitir que juegue contra el bot
        if len(game.players) == 1:
            embed = discord.Embed(
                title="🎮 Buckshot Roulette",
                description="Nadie más se ha unido. ¿Quieres jugar contra el bot?",
                color=discord.Color.blue()
            )
            message = await ctx.send(embed=embed)
            await message.add_reaction("✅")
            await message.add_reaction("❌")

            def check(reaction, user):
                return user == ctx.author and str(reaction.emoji) in ["✅", "❌"]

            try:
                reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
                if str(reaction.emoji) == "❌":
                    await ctx.send("❌ La partida ha sido cancelada.")
                    del self.active_games[ctx.guild.id]
                    return
            except asyncio.TimeoutError:
                await ctx.send("⏰ Se acabó el tiempo. La partida ha sido cancelada.")
                del self.active_games[ctx.guild.id]
                return

        game.game_started = True
        game.load_shotgun()

        embed = discord.Embed(
            title="🎮 Buckshot Roulette",
            description="¡La partida ha comenzado! La escopeta ha sido cargada...",
            color=discord.Color.red()
        )
        embed.add_field(name="Ronda", value=f"{game.round}/3", inline=True)
        
        # Mostrar vidas de todos los jugadores
        lives_text = ""
        for player in game.players:
            lives_text += f"{player.mention}: {'❤️' * game.player_lives[player.id]}\n"
        if len(game.players) == 1:
            lives_text += f"🤖 Dealer: {'❤️' * game.dealer_lives}\n"
        embed.add_field(name="Vidas", value=lives_text, inline=False)
        
        await ctx.send(embed=embed)
        
        # Mostrar información sobre los cartuchos
        await self.show_shotgun_info(ctx, game)
        
        await self.show_turn_options(ctx, game)

    async def show_shotgun_info(self, ctx: commands.Context, game: BuckshotGame):
        """Muestra información sobre la carga de la escopeta"""
        total_shells = len(game.shotgun)
        live_shells = game.shotgun.count('LIVE')
        empty_shells = game.shotgun.count('EMPTY')
        
        # Representación visual de los cartuchos
        live_visual = "🟥 " * live_shells  # Cuadrado rojo para cartuchos vivos
        empty_visual = "🟦 " * empty_shells  # Cuadrado azul para cartuchos vacíos
        
        embed = discord.Embed(
            title="🔫 Cartuchos cargados",
            description=f"La escopeta ha sido cargada con {total_shells} cartuchos ordenados aleatoriamente.",
            color=discord.Color.orange()
        )
        embed.add_field(
            name="Cartuchos",
            value=f"Vivos: {live_shells} {live_visual}\nVacíos: {empty_shells} {empty_visual}",
            inline=False
        )
        embed.set_footer(text="Los cartuchos están ordenados de forma aleatoria. ¡Buena suerte!")
        
        await ctx.send(embed=embed)

    async def show_turn_options(self, ctx: commands.Context, game: BuckshotGame):
        """Muestra las opciones disponibles para el turno actual"""
        current_player = game.get_current_player()
        if ctx.author != current_player:
            return

        embed = discord.Embed(
            title=f"Turno de {current_player.name}",
            description="¿Qué quieres hacer?",
            color=discord.Color.blue()
        )
        
        # Opciones básicas
        if len(game.players) > 2:
            embed.add_field(
                name="Acciones",
                value="1️⃣ Dispararte a ti mismo\n2️⃣ Disparar a otro jugador",
                inline=False
            )
        elif len(game.players) == 2:
            embed.add_field(
                name="Acciones",
                value="1️⃣ Dispararte a ti mismo\n2️⃣ Disparar al Dealer",
                inline=False
            )
        else:
            # Modo un jugador contra el bot
            embed.add_field(
                name="Acciones",
                value="1️⃣ Dispararte a ti mismo\n2️⃣ Disparar al Dealer",
                inline=False
            )

        # Mostrar ítems si hay disponibles
        if game.player_items[current_player.id]:
            items_text = "\n".join([f"{i+3}️⃣ {item}" for i, item in enumerate(game.player_items[current_player.id])])
            embed.add_field(name="Tus ítems", value=items_text, inline=False)

        message = await ctx.send(embed=embed)
        
        # Añadir reacciones para las opciones
        await message.add_reaction("1️⃣")
        await message.add_reaction("2️⃣")
        for i in range(len(game.player_items[current_player.id])):
            await message.add_reaction(f"{i+3}️⃣")

        def check(reaction, user):
            return user == current_player and str(reaction.emoji) in ["1️⃣", "2️⃣"] + [f"{i+3}️⃣" for i in range(len(game.player_items[current_player.id]))]

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            
            if str(reaction.emoji) == "1️⃣":
                await self.shoot_self(ctx, game)
            elif str(reaction.emoji) == "2️⃣":
                if len(game.players) > 2:
                    await self.show_target_selection(ctx, game)
                else:
                    await self.shoot_dealer(ctx, game)
            else:
                item_index = ["1️⃣", "2️⃣"].index(str(reaction.emoji)) - 2
                await self.use_item(ctx, game, game.player_items[current_player.id][item_index])

        except asyncio.TimeoutError:
            await ctx.send(f"⏰ Se acabó el tiempo. El turno pasa al siguiente jugador.")
            game.next_player()
            if len(game.players) == 1:
                await self.dealer_turn(ctx, game)
            else:
                await self.show_turn_options(ctx, game)

    async def show_target_selection(self, ctx: commands.Context, game: BuckshotGame):
        """Muestra la lista de jugadores para seleccionar objetivo"""
        current_player = game.get_current_player()
        if ctx.author != current_player:
            return

        embed = discord.Embed(
            title="Selecciona un objetivo",
            description="¿A quién quieres disparar?",
            color=discord.Color.blue()
        )

        # Lista de jugadores disponibles (excluyendo al jugador actual)
        available_players = [p for p in game.players if p != current_player]
        players_text = "\n".join([f"{i+1}️⃣ {player.mention}" for i, player in enumerate(available_players)])
        embed.add_field(name="Jugadores", value=players_text, inline=False)

        message = await ctx.send(embed=embed)
        
        # Añadir reacciones para cada jugador
        for i in range(len(available_players)):
            await message.add_reaction(f"{i+1}️⃣")

        def check(reaction, user):
            return user == current_player and str(reaction.emoji) in [f"{i+1}️⃣" for i in range(len(available_players))]

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=30.0, check=check)
            target_index = int(str(reaction.emoji)[0]) - 1
            target = available_players[target_index]
            await self.shoot_player(ctx, game, target)

        except asyncio.TimeoutError:
            await ctx.send("⏰ Se acabó el tiempo. El turno pasa al siguiente jugador.")
            game.next_player()
            await self.show_turn_options(ctx, game)

    async def shoot_player(self, ctx: commands.Context, game: BuckshotGame, target: discord.Member):
        """Dispara a otro jugador"""
        shell = game.get_current_shell()
        game.next_chamber()

        if shell == 'EMPTY':
            embed = discord.Embed(
                title="💨 ¡Vacío!",
                description=f"El cartucho estaba vacío. El turno pasa al siguiente jugador.",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            game.next_player()
            await self.show_turn_options(ctx, game)
        else:
            damage = 2 if game.saw_active else 1
            game.player_lives[target.id] -= damage
            game.saw_active = False  # Resetear el efecto de la sierra
            
            embed = discord.Embed(
                title="💥 ¡BANG!",
                description=f"¡El cartucho estaba cargado! {target.mention} ha perdido {damage} {'vidas' if damage > 1 else 'vida'}.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            
            if game.player_lives[target.id] <= 0:
                await self.end_round(ctx, game)
            else:
                game.next_player()
                await self.show_turn_options(ctx, game)

    async def shoot_self(self, ctx: commands.Context, game: BuckshotGame):
        """El jugador se dispara a sí mismo"""
        shell = game.get_current_shell()
        game.next_chamber()

        if shell == 'EMPTY':
            embed = discord.Embed(
                title="💨 ¡Vacío!",
                description="El cartucho estaba vacío. ¡Sigues con vida!",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            await self.show_turn_options(ctx, game)
        else:
            damage = 2 if game.saw_active else 1
            game.player_lives[ctx.author.id] -= damage
            game.saw_active = False  # Resetear el efecto de la sierra
            
            embed = discord.Embed(
                title="💥 ¡BANG!",
                description=f"¡El cartucho estaba cargado! Has perdido {damage} {'vidas' if damage > 1 else 'vida'}.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            
            if game.player_lives[ctx.author.id] <= 0:
                await self.end_round(ctx, game)
            else:
                game.current_player_index = (game.current_player_index + 1) % len(game.players)
                await self.dealer_turn(ctx, game)

    async def shoot_dealer(self, ctx: commands.Context, game: BuckshotGame):
        """El jugador dispara al Dealer"""
        shell = game.get_current_shell()
        game.next_chamber()

        if shell == 'EMPTY':
            embed = discord.Embed(
                title="💨 ¡Vacío!",
                description="El cartucho estaba vacío. El turno pasa al Dealer.",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            game.current_player_index = (game.current_player_index + 1) % len(game.players)
            await self.dealer_turn(ctx, game)
        else:
            damage = 2 if game.saw_active else 1
            game.dealer_lives -= damage
            game.saw_active = False  # Resetear el efecto de la sierra
            
            embed = discord.Embed(
                title="💥 ¡BANG!",
                description=f"¡El cartucho estaba cargado! El Dealer ha perdido {damage} {'vidas' if damage > 1 else 'vida'}.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
            
            if game.dealer_lives <= 0:
                await self.end_round(ctx, game)
            else:
                game.current_player_index = (game.current_player_index + 1) % len(game.players)
                await self.dealer_turn(ctx, game)

    async def dealer_turn(self, ctx: commands.Context, game: BuckshotGame):
        """Turno del dealer con IA mejorada"""
        if game.dealer_skips_turn:
            embed = discord.Embed(
                title="🔒 Dealer encadenado",
                description="El Dealer está encadenado y pierde su turno.",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            game.dealer_skips_turn = False
            game.next_player()
            await self.show_turn_options(ctx, game)
            return

        embed = discord.Embed(
            title="🤖 Turno del Dealer",
            description="El Dealer está pensando...",
            color=discord.Color.blue()
        )
        message = await ctx.send(embed=embed)
        await asyncio.sleep(2)  # Pequeña pausa para dar sensación de que el dealer "piensa"

        # Lógica de IA para el Dealer
        current_shell = game.get_current_shell()
        next_shell = game.shotgun[(game.current_chamber + 1) % len(game.shotgun)]
        
        # Calcular probabilidades
        total_shells = len(game.shotgun)
        live_shells = game.shotgun.count('LIVE')
        empty_shells = total_shells - live_shells
        live_probability = live_shells / total_shells if total_shells > 0 else 0

        # Estrategia del Dealer
        should_shoot_self = False
        
        # Si el Dealer tiene 1 vida, es más cauteloso
        if game.dealer_lives == 1:
            # Si hay más probabilidad de cartucho vacío, se dispara a sí mismo
            should_shoot_self = live_probability < 0.5
        # Si el jugador tiene 1 vida, el Dealer es más agresivo
        elif game.player_lives[game.get_current_player().id] == 1:
            # Si hay más probabilidad de cartucho vivo, dispara al jugador
            should_shoot_self = live_probability < 0.3
        # En otras situaciones, toma decisiones más balanceadas
        else:
            # Si el cartucho actual es vacío, se dispara a sí mismo
            if current_shell == 'EMPTY':
                should_shoot_self = True
            # Si el siguiente cartucho es vivo, dispara al jugador
            elif next_shell == 'LIVE':
                should_shoot_self = False
            # En caso de duda, toma una decisión aleatoria con sesgo
            else:
                should_shoot_self = random.random() < 0.4  # 40% de probabilidad de dispararse a sí mismo

        if should_shoot_self:
            shell = game.get_current_shell()
            game.next_chamber()

            if shell == 'EMPTY':
                embed = discord.Embed(
                    title="💨 ¡Vacío!",
                    description="El Dealer se dispara a sí mismo... ¡El cartucho estaba vacío!",
                    color=discord.Color.blue()
                )
                await message.edit(embed=embed)
                game.next_player()
                await self.show_turn_options(ctx, game)
            else:
                damage = 2 if game.saw_active else 1
                game.dealer_lives -= damage
                game.saw_active = False
                
                embed = discord.Embed(
                    title="💥 ¡BANG!",
                    description=f"El Dealer se dispara a sí mismo... ¡El cartucho estaba cargado! Ha perdido {damage} {'vidas' if damage > 1 else 'vida'}.",
                    color=discord.Color.red()
                )
                await message.edit(embed=embed)
                
                if game.dealer_lives <= 0:
                    await self.end_round(ctx, game)
                else:
                    game.next_player()
                    await self.show_turn_options(ctx, game)
        else:
            # Disparar al jugador
            shell = game.get_current_shell()
            game.next_chamber()

            if shell == 'EMPTY':
                embed = discord.Embed(
                    title="💨 ¡Vacío!",
                    description=f"El Dealer dispara a {game.get_current_player().mention}... ¡El cartucho estaba vacío!",
                    color=discord.Color.blue()
                )
                await message.edit(embed=embed)
                game.next_player()
                await self.show_turn_options(ctx, game)
            else:
                damage = 2 if game.saw_active else 1
                game.player_lives[game.get_current_player().id] -= damage
                game.saw_active = False
                
                embed = discord.Embed(
                    title="💥 ¡BANG!",
                    description=f"El Dealer dispara a {game.get_current_player().mention}... ¡El cartucho estaba cargado! Has perdido {damage} {'vidas' if damage > 1 else 'vida'}.",
                    color=discord.Color.red()
                )
                await message.edit(embed=embed)
                
                if game.player_lives[game.get_current_player().id] <= 0:
                    await self.end_round(ctx, game)
                else:
                    game.next_player()
                    await self.show_turn_options(ctx, game)

    async def end_round(self, ctx: commands.Context, game: BuckshotGame):
        """Finaliza la ronda actual y prepara la siguiente"""
        if game.round == 3:
            if game.player_lives[ctx.author.id] <= 0:
                embed = discord.Embed(
                    title="Game Over",
                    description="Has perdido todas tus vidas en la ronda final. ¡Game Over!",
                    color=discord.Color.red()
                )
            else:
                embed = discord.Embed(
                    title="¡Victoria!",
                    description="¡Has derrotado al Dealer en la ronda final!",
                    color=discord.Color.green()
                )
            await ctx.send(embed=embed)
            del self.active_games[ctx.guild.id]
            return

        # Preparar siguiente ronda
        game.round += 1
        if game.round == 2:
            for player in game.players:
                game.player_lives[player.id] = 4
            game.dealer_lives = 4
        elif game.round == 3:
            for player in game.players:
                game.player_lives[player.id] = 5
            game.dealer_lives = 5

        game.load_shotgun()
        game.distribute_items()

        embed = discord.Embed(
            title=f"Ronda {game.round}",
            description="¡Nueva ronda! La escopeta ha sido recargada...",
            color=discord.Color.blue()
        )
        embed.add_field(name="Tus vidas", value="❤️" * game.player_lives[ctx.author.id], inline=True)
        embed.add_field(name="Vidas del Dealer", value="❤️" * game.dealer_lives, inline=True)
        
        await ctx.send(embed=embed)
        
        # Mostrar información sobre los cartuchos
        await self.show_shotgun_info(ctx, game)
        
        game.current_player_index = (game.current_player_index + 1) % len(game.players)
        await self.show_turn_options(ctx, game)

    async def use_item(self, ctx: commands.Context, game: BuckshotGame, item: str):
        """Usa un ítem del jugador"""
        if item not in game.player_items[ctx.author.id]:
            await ctx.send("❌ No tienes ese ítem.")
            return

        game.player_items[ctx.author.id].remove(item)
        
        if item == 'CIGARETTE':
            game.player_lives[ctx.author.id] = min(game.player_lives[ctx.author.id] + 1, 5)
            embed = discord.Embed(
                title="🚬 Cigarrillo",
                description="Has recuperado una vida.",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
            
        elif item == 'BEER':
            shell = game.get_current_shell()
            game.next_chamber()
            embed = discord.Embed(
                title="🍺 Cerveza",
                description=f"Has expulsado un cartucho {'vivo' if shell == 'LIVE' else 'vacío'}.",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            
        elif item == 'SAW':
            game.saw_active = True
            embed = discord.Embed(
                title="🪚 Sierra",
                description="El próximo disparo hará doble daño.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            
        elif item == 'MAGNIFYING_GLASS':
            shell = game.get_current_shell()
            embed = discord.Embed(
                title="🔍 Gafas de Aumento",
                description=f"El cartucho actual es {'vivo' if shell == 'LIVE' else 'vacío'}.",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            
        elif item == 'HANDCUFFS':
            game.dealer_skips_turn = True
            embed = discord.Embed(
                title="🔗 Esposas",
                description="El Dealer perderá su próximo turno.",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)
            
        elif item == 'EXPIRED_MEDICINE':
            if random.random() < 0.5:  # 50% de probabilidad
                game.player_lives[ctx.author.id] = min(game.player_lives[ctx.author.id] + 2, 5)
                embed = discord.Embed(
                    title="💊 Medicina Caducada",
                    description="¡Has recuperado dos vidas!",
                    color=discord.Color.green()
                )
            else:
                game.player_lives[ctx.author.id] = max(game.player_lives[ctx.author.id] - 1, 0)
                embed = discord.Embed(
                    title="💊 Medicina Caducada",
                    description="¡Has perdido una vida!",
                    color=discord.Color.red()
                )
            await ctx.send(embed=embed)
            
        elif item == 'INVERTER':
            # Invertir la cantidad de cartuchos vivos y vacíos
            live_count = game.shotgun.count('LIVE')
            empty_count = game.shotgun.count('EMPTY')
            game.shotgun = ['LIVE'] * empty_count + ['EMPTY'] * live_count
            random.shuffle(game.shotgun)
            embed = discord.Embed(
                title="🔄 Inversor",
                description="Se han invertido los cartuchos vivos y vacíos.",
                color=discord.Color.blue()
            )
            await ctx.send(embed=embed)

        # Verificar si el jugador ha perdido todas sus vidas
        if game.player_lives[ctx.author.id] <= 0:
            await self.end_round(ctx, game)
        else:
            await self.show_turn_options(ctx, game)

    @commands.command(name="solo")
    async def solo_game(self, ctx: commands.Context):
        """Inicia una partida de Buckshot Roulette directamente contra el bot"""
        if ctx.guild.id in self.active_games:
            await ctx.send("❌ Ya hay una partida en curso en este servidor.")
            return

        game = BuckshotGame(ctx.author)
        game.initialize_player(ctx.author)
        self.active_games[ctx.guild.id] = game
        game.game_started = True
        game.load_shotgun()

        embed = discord.Embed(
            title="🎮 Buckshot Roulette - Modo Solitario",
            description="¡Iniciando partida contra el Dealer!",
            color=discord.Color.red()
        )
        embed.add_field(name="Ronda", value=f"{game.round}/3", inline=True)
        
        # Mostrar vidas
        lives_text = f"{ctx.author.mention}: {'❤️' * game.player_lives[ctx.author.id]}\n"
        lives_text += f"🤖 Dealer: {'❤️' * game.dealer_lives}\n"
        embed.add_field(name="Vidas", value=lives_text, inline=False)
        
        await ctx.send(embed=embed)
        
        # Mostrar información sobre los cartuchos
        await self.show_shotgun_info(ctx, game)
        
        await self.show_turn_options(ctx, game)

async def setup(bot: commands.Bot):
    await bot.add_cog(Buckshot(bot)) 
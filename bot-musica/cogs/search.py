import discord
from discord.ext import commands
from discord import app_commands
import config
import requests

class Search(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------ Comando ANIME prefijo ------------------
    @commands.command(name='anime')
    async def anime(self, ctx, *, mensaje: str):
        try:
            # Lógica igual que en tu main.py (usa config.MAL_TOKEN)
            if '|' in mensaje:
                nombre, limite = mensaje.split('|', 1)
                nombre = nombre.strip()
                limite = limite.strip()
                if not limite.isdigit() or int(limite) <= 0:
                    await ctx.send('El número de resultados debe ser un número entero positivo.')
                    return
                limite = min(int(limite), 10)
            else:
                nombre = mensaje.strip()
                limite = 1

            url = f'https://api.myanimelist.net/v2/anime?q={nombre}&limit={limite}'
            headers = {'Authorization': f'Bearer {config.MAL_TOKEN}'}
            response = requests.get(url, headers=headers)
            data = response.json()

            if 'data' in data and len(data['data']) > 0:
                for item in data['data']:
                    anime_id = item['node']['id']
                    details_url = f'https://api.myanimelist.net/v2/anime/{anime_id}?fields=title,synopsis,mean,genres,num_episodes,status,main_picture,media_type,start_date,end_date,studios'
                    details_response = requests.get(details_url, headers=headers)
                    details = details_response.json()

                    # Translate and shorten synopsis
                    translated_description = details.get('synopsis', 'Sin descripción disponible.')
                    translate_url = "https://translate.googleapis.com/translate_a/single"
                    translate_params = {
                        "client": "gtx",
                        "sl": "en",
                        "tl": "es",
                        "dt": "t",
                        "q": translated_description
                    }
                    translate_response = requests.get(translate_url, params=translate_params)
                    translation = translate_response.json()
                    translated_description = ''.join([t[0] for t in translation[0]])
                    if len(translated_description) > 350:
                        translated_description = translated_description[:350] + "..."

                    estado = details.get('status', 'N/A').lower()
                    estados_traducidos = {
                        "finished_airing": "Finalizado",
                        "currently_airing": "En emisión",
                        "not_yet_aired": "No emitido"
                    }
                    estado_traducido = estados_traducidos.get(estado, "Desconocido")

                    start_date = details.get('start_date', 'Desconocido')
                    end_date = details.get('end_date', 'Desconocido')
                    studios = ', '.join([studio['name'] for studio in details.get('studios', [])]) or 'Desconocido'

                    embed = discord.Embed(
                        title=details['title'],
                        description=translated_description,
                        color=discord.Color.teal()
                    )
                    embed.add_field(name='Tipo', value=details.get('media_type', 'Desconocido').capitalize(), inline=True)
                    embed.add_field(name='Puntuación', value=details.get('mean', 'N/A'), inline=True)
                    embed.add_field(name='Episodios', value=details.get('num_episodes', 'N/A'), inline=True)
                    embed.add_field(name='Estado', value=estado_traducido, inline=True)
                    embed.add_field(name='Fecha de inicio', value=start_date, inline=True)
                    embed.add_field(name='Fecha de fin', value=end_date, inline=True)
                    embed.add_field(name='Estudios', value=studios, inline=False)
                    embed.add_field(
                        name='Géneros',
                        value=', '.join([genre['name'] for genre in details.get('genres', [])]) or 'N/A',
                        inline=False
                    )
                    if 'main_picture' in details:
                        embed.set_image(url=details['main_picture']['large'])
                    embed.set_footer(text='Información obtenida de MyAnimeList')
                    await ctx.send(embed=embed)
            else:
                await ctx.send('No se encontró ningún anime con ese nombre.')

        except Exception as e:
            await ctx.send(f'Ocurrió un error al buscar el anime: {e}')

    # ------------- Comando ANIME slash --------------
    @app_commands.command(name="anime", description="Busca información de un anime en MyAnimeList.")
    @app_commands.describe(mensaje="Nombre del anime y límite de resultados (ejemplo: Chainsaw Man | 3)")
    async def anime_slash(self, interaction: discord.Interaction, mensaje: str):
        ctx = await self.bot.get_context(interaction)
        await self.anime(ctx, mensaje=mensaje)

    # ------------------ Comando CONVERT prefijo ------------------
    @commands.command(name='convert')
    async def convert(self, ctx, *, mensaje: str):
        try:
            # Dividir el mensaje en partes usando "to" como separador
            partes = mensaje.split(" to ")
            if len(partes) != 2:
                await ctx.send('Formato incorrecto. Usa: g.convert [cantidad] [moneda origen] to [moneda destino]')
                return

            # Obtener la cantidad y la moneda de origen
            primera_parte = partes[0].strip().split()
            if len(primera_parte) != 2:
                await ctx.send('Formato incorrecto. Usa: g.convert [cantidad] [moneda origen] to [moneda destino]')
                return

            try:
                cantidad = float(primera_parte[0])
            except ValueError:
                await ctx.send('La cantidad debe ser un número válido.')
                return

            origen = primera_parte[1].upper()
            destino = partes[1].strip().upper()

            url = f'https://api.exchangerate-api.com/v4/latest/{origen}'
            response = requests.get(url)
            data = response.json()
            tasas = data["rates"]

            if destino in tasas:
                relacion = tasas[destino] / tasas[origen]
                resultado = cantidad * relacion

                embed = discord.Embed(
                    title="Conversión",
                    description=f"{origen} a {destino}",
                    color=discord.Color.teal()
                )
                embed.add_field(name="Relación", value=f"1 {origen} = {relacion:.4f} {destino}", inline=False)
                embed.add_field(name="Conversión", value=f"{cantidad} {origen} son {resultado:.2f} {destino}", inline=False)
                embed.set_footer(text="Información obtenida de Exchange Rate API")

                await ctx.send(embed=embed)
            else:
                await ctx.send(f'No se encontró la tasa de cambio para {destino}.')

        except KeyError:
            await ctx.send(f'No se encontró la divisa {origen} o {destino}.')
        except Exception as e:
            await ctx.send(f'Ocurrió un error: {e}')

    # ------------------ Comando CONVERT slash -------------------
    @app_commands.command(name="convert", description="Convierte una cantidad de una moneda a otra.")
    @app_commands.describe(mensaje="Formato: [cantidad] [moneda origen] to [moneda destino]")
    async def convert_slash(self, interaction: discord.Interaction, mensaje: str):
        ctx = await self.bot.get_context(interaction)
        await self.convert(ctx, mensaje=mensaje)

    # ------------------ Comando IMG prefijo ------------------
    @commands.command(name='img')
    async def image(self, ctx, *, query: str):
        try:
            url = "https://www.googleapis.com/customsearch/v1"
            params = {
                "q": query,
                "cx": config.CX,
                "key": config.CUSTOM_SEARCH_API_KEY,
                "searchType": "image",
                "num": 1,
                "safe": "active"
            }
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if 'items' in data and len(data['items']) > 0:
                    image_url = data['items'][0]['link']
                    embed = discord.Embed(
                        title="Resultado de búsqueda",
                        description=f"Resultado para: {query}",
                        color=discord.Color.blue()
                    )
                    embed.set_image(url=image_url)
                    await ctx.send(embed=embed)
                else:
                    await ctx.send("No se encontraron imágenes para esta búsqueda.")
            else:
                await ctx.send(f"Error al buscar imágenes: {response.status_code}, {response.text}")
        except Exception as e:
            await ctx.send(f"Ocurrió un error: {e}")

    # ------------------ Comando IMG slash ------------------
    @app_commands.command(name="img", description="Devuelve una imagen relacionada a tu búsqueda (Google)")
    @app_commands.describe(query="Término de búsqueda de la imagen.")
    async def image_slash(self, interaction: discord.Interaction, query: str):
        ctx = await self.bot.get_context(interaction)
        await self.image(ctx, query=query)

async def setup(bot):
    await bot.add_cog(Search(bot))
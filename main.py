import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import asyncio
import os
from collections import deque

# Bot konfigurācija
intents = discord.Intents.default()
intents.message_content = True
# Izslēdz default help komandu
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Mūzikas rinda katram serverim
music_queues = {}

# yt-dlp konfigurācija
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    # Anti-bot bypass headers
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-us,en;q=0.5',
        'Accept-Encoding': 'gzip,deflate',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    },
    'geo_bypass': True,
    'geo_bypass_country': 'US',
    # YouTube specific options
    'extractor_args': {
        'youtube': {
            'skip': ['dash', 'hls']
        }
    },
    # Fallback options
    'extract_flat': False,
    'writethumbnail': False,
    'writeinfojson': False,
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# FFmpeg ceļš (Ubuntu/Linux serveriem parasti ir PATH)
ffmpeg_executable = 'ffmpeg'

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        
        # First attempt with standard extraction
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        except Exception as e:
            print(f"Primary extraction failed: {e}")
            
            # Fallback: try with different search method
            try:
                # If direct URL fails, try search
                if 'youtube.com' in url or 'youtu.be' in url:
                    # Extract video ID and search by title instead
                    import re
                    video_id_match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
                    if video_id_match:
                        # Try ytsearch instead of direct URL
                        search_query = f"ytsearch:{video_id_match.group(1)}"
                        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=not stream))
                    else:
                        raise e
                else:
                    # For search queries, add ytsearch prefix
                    search_query = f"ytsearch:{url}"
                    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(search_query, download=not stream))
                    
            except Exception as e2:
                print(f"Fallback extraction also failed: {e2}")
                raise e  # Re-raise original error
        
        if 'entries' in data:
            data = data['entries'][0]
        
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, executable=ffmpeg_executable, **ffmpeg_options), data=data)

def has_dj_role():
    """Pārbauda vai lietotājam ir DJ role"""
    async def predicate(ctx):
        # Pārbauda vai lietotājam ir "DJ" role vai administrator tiesības
        if ctx.author.guild_permissions.administrator:
            return True
        
        dj_role = discord.utils.get(ctx.author.roles, name="DJ")
        if dj_role:
            return True
        
        await ctx.send("❌ Tev nepieciešama **DJ** role, lai izmantotu mūzikas komandas!")
        return False
    
    return commands.check(predicate)

@bot.event
async def on_ready():
    print(f'{bot.user} ir gatavs atskaņot mūziku! 🎵')
    print(f'Pievienots {len(bot.guilds)} serveriem')
    
    # Sinhronizē slash komandas automātiski serverī
    try:
        # Globāla sinhronizācija
        synced = await bot.tree.sync()
        print(f"✅ Sinhronizēju {len(synced)} globālās slash komandas")
        
        # Guild-specific sync ātrākai sinhronizācijai (noņem komentāru ja vajag)
        # for guild in bot.guilds:
        #     try:
        #         guild_synced = await bot.tree.sync(guild=guild)
        #         print(f"✅ Sinhronizēju {len(guild_synced)} komandas serverim {guild.name}")
        #     except Exception as e:
        #         print(f"❌ Nevarēju sinhronizēt serverim {guild.name}: {e}")
        
    except Exception as e:
        print(f"❌ Nevarēju sinhronizēt slash komandas: {e}")
    
    # Pārbauda vai botam ir nepieciešamās tiesības
    for guild in bot.guilds:
        bot_member = guild.get_member(bot.user.id)
        if bot_member:
            permissions = bot_member.guild_permissions
            missing_perms = []
            
            if not permissions.send_messages:
                missing_perms.append("Send Messages")
            if not permissions.connect:
                missing_perms.append("Connect")
            if not permissions.speak:
                missing_perms.append("Speak")
            if not permissions.use_voice_activation:
                missing_perms.append("Use Voice Activity")
            # use_slash_commands nav īsts permission - noņemam
                
            if missing_perms:
                print(f"⚠️  Serverī '{guild.name}' trūkst tiesību: {', '.join(missing_perms)}")
            else:
                print(f"✅ Serverī '{guild.name}' visas tiesības ir OK")

@bot.command(name='join', help='Pievieno botu voice kanālam')
@has_dj_role()
async def join(ctx):
    if not ctx.author.voice:
        await ctx.send("❌ Tu neesi voice kanālā!")
        return
    
    channel = ctx.author.voice.channel
    
    # Ja bots jau ir savienojies kaut kur
    if ctx.voice_client is not None:
        if ctx.voice_client.channel == channel:
            await ctx.send(f"✅ Es jau esmu **{channel}** kanālā!")
            return
        else:
            await ctx.voice_client.move_to(channel)
            await ctx.send(f"🔄 Pārvietojos uz **{channel}** kanālu!")
            return
    
    # Pievienojas kanālam
    try:
        await channel.connect()
        await ctx.send(f"✅ Pievienojies **{channel}** kanālam!")
    except Exception as e:
        print(f"Join kļūda: {e}")
        await ctx.send("❌ Nevarēju pievienoties voice kanālam!")

@bot.command(name='leave', help='Iziet no voice kanāla')
@has_dj_role()
async def leave(ctx):
    if ctx.voice_client:
        guild_id = ctx.guild.id
        if guild_id in music_queues:
            music_queues[guild_id].clear()
        await ctx.voice_client.disconnect()
        await ctx.send("👋 Atstāju voice kanālu!")
    else:
        await ctx.send("❌ Es neesmu voice kanālā!")

@bot.command(name='play', help='Atskaņo dziesmu no YouTube')
@has_dj_role()
async def play(ctx, *, url_or_search):
    # Pārbauda vai bots ir voice kanālā
    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            await ctx.send("❌ Tu neesi voice kanālā!")
            return
    
    guild_id = ctx.guild.id
    if guild_id not in music_queues:
        music_queues[guild_id] = deque()
    
    # Parāda loading ziņu
    loading_msg = await ctx.send("🔍 Meklēju dziesmu...")
    
    try:
        # Meklē un sagatavo dziesmu
        player = await YTDLSource.from_url(url_or_search, loop=bot.loop, stream=True)
        
        # Pievieno rindā
        music_queues[guild_id].append(player)
        
        # Ja nekas neatskaņojas, sāk atskaņot
        if not ctx.voice_client.is_playing():
            await play_next(ctx)
        else:
            await loading_msg.edit(content=f"➕ **{player.title}** pievienots rindai!")
            
    except Exception as e:
        print(f"Play kļūda: {str(e)}")
        await loading_msg.edit(content=f"❌ Kļūda: Nevarēju ielādēt dziesmu")

async def play_next(ctx):
    """Atskaņo nākamo dziesmu no rindas"""
    guild_id = ctx.guild.id
    
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        return
    
    player = music_queues[guild_id].popleft()
    
    def after_playing(error):
        if error:
            print(f'Atskaņošanas kļūda: {error}')
        
        # Atskaņo nākamo dziesmu
        coro = play_next(ctx)
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            fut.result()
        except:
            pass
    
    ctx.voice_client.play(player, after=after_playing)
    await ctx.send(f"🎵 Tagad atskaņoju: **{player.title}**")

@bot.command(name='pause', help='Pauzē mūziku')
@has_dj_role()
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Mūzika pauzēta!")
    else:
        await ctx.send("❌ Nekas neatskaņojas!")

@bot.command(name='resume', help='Turpina mūziku')
@has_dj_role()
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Mūzika turpināta!")
    else:
        await ctx.send("❌ Mūzika nav pauzēta!")

@bot.command(name='stop', help='Aptur mūziku un iztīra rindu')
@has_dj_role()
async def stop(ctx):
    if ctx.voice_client:
        guild_id = ctx.guild.id
        if guild_id in music_queues:
            music_queues[guild_id].clear()
        ctx.voice_client.stop()
        await ctx.send("⏹️ Mūzika apturēta un rinda iztīrīta!")
    else:
        await ctx.send("❌ Nekas neatskaņojas!")

@bot.command(name='skip', aliases=['next'], help='Izlaiž pašreizējo dziesmu')
@has_dj_role()
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Dziesma izlaista!")
    else:
        await ctx.send("❌ Nekas neatskaņojas!")

@bot.command(name='queue', help='Parāda mūzikas rindu')
async def queue_cmd(ctx):
    guild_id = ctx.guild.id
    
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        await ctx.send("📝 Mūzikas rinda ir tukša!")
        return
    
    queue_list = []
    for i, player in enumerate(list(music_queues[guild_id])[:10], 1):
        queue_list.append(f"{i}. {player.title}")
    
    queue_text = "🎵 **Mūzikas rinda:**\n" + "\n".join(queue_list)
    
    if len(music_queues[guild_id]) > 10:
        queue_text += f"\n\n**Un vēl:** +{len(music_queues[guild_id]) - 10} dziesmas"
    
    await ctx.send(queue_text)

@bot.command(name='volume', help='Maina skaļumu (0-100)')
@has_dj_role()
async def volume(ctx, volume: int):
    if ctx.voice_client is None:
        return await ctx.send("❌ Nav pievienojies voice kanālam!")
    
    if 0 <= volume <= 100:
        ctx.voice_client.source.volume = volume / 100
        await ctx.send(f"🔊 Skaļums uzstādīts uz {volume}%")
    else:
        await ctx.send("❌ Skaļumam jābūt starp 0 un 100!")

@bot.command(name='nowplaying', aliases=['np', 'current'], help='Parāda pašreiz atskaņojamo dziesmu')
async def nowplaying(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        # Mēģina atrast pašreizējo dziesmu
        if hasattr(ctx.voice_client.source, 'title'):
            title = ctx.voice_client.source.title
            await ctx.send(f"🎵 **Tagad atskaņoju:** {title}")
        else:
            await ctx.send("🎵 Kaut kas atskaņojas, bet nezinu nosaukumu...")
    else:
        await ctx.send("❌ Nekas neatskaņojas!")

@bot.command(name='clear', aliases=['empty'], help='Iztīra mūzikas rindu')
@has_dj_role()
async def clear_queue(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues:
        cleared_count = len(music_queues[guild_id])
        music_queues[guild_id].clear()
        await ctx.send(f"🗑️ Iztīrīju {cleared_count} dziesmas no rindas!")
    else:
        await ctx.send("📝 Rinda jau ir tukša!")

@bot.command(name='shuffle', help='Samaina rindu nejauši')
@has_dj_role()
async def shuffle_queue(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 1:
        import random
        queue_list = list(music_queues[guild_id])
        random.shuffle(queue_list)
        music_queues[guild_id] = deque(queue_list)
        await ctx.send(f"🔀 Rinda samaisīta! ({len(queue_list)} dziesmas)")
    else:
        await ctx.send("❌ Rindā nav pietiekami daudz dziesmu!")

@bot.command(name='remove', help='Izņem dziesmu no rindas (pēc numura)')
@has_dj_role()
async def remove_song(ctx, position: int):
    guild_id = ctx.guild.id
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        await ctx.send("❌ Rinda ir tukša!")
        return
    
    if 1 <= position <= len(music_queues[guild_id]):
        queue_list = list(music_queues[guild_id])
        removed_song = queue_list.pop(position - 1)
        music_queues[guild_id] = deque(queue_list)
        await ctx.send(f"❌ Izņēmu: **{removed_song.title}** (pozīcija {position})")
    else:
        await ctx.send(f"❌ Nederīga pozīcija! Izmanto 1-{len(music_queues[guild_id])}")

# Pievienojam error handler
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        # Nedarām neko - ignorējam nepazīstamas komandas
        pass
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Trūkst argumentu! Izmanto: `!help {ctx.command.name}`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Nepareizs arguments! Pārbaudi komandas sintaksi.")
    else:
        print(f"Neparedzēta kļūda: {error}")
@bot.command(name='status', help='Parāda bota statusu')
async def status(ctx):
    """Debugošanas komanda"""
    voice_clients = len(bot.voice_clients)
    guilds = len(bot.guilds)
    await ctx.send(f"🤖 **Bot Status:**\n"
                  f"📊 Serveri: {guilds}\n"
                  f"🔊 Voice savienojumi: {voice_clients}\n"
                  f"🎵 Aktīvas rindas: {len(music_queues)}")

@bot.command(name='help', help='Parāda palīdzību')
async def help_command(ctx):
    """Custom help komanda bez embed"""
    help_text = """🎵 **DJShaled - Discord Music Bot**
Lietotāji ar **DJ** role var vadīt mūziku

**🎧 DJ Komandas:**
`!join` - Pievieno botu voice kanālam
`!leave` - Iziet no voice kanāla
`!play <dziesma>` - Atskaņo mūziku
`!pause` - Pauzē mūziku
`!resume` - Turpina mūziku
`!stop` - Aptur mūziku un iztīra rindu
`!skip` / `!next` - Izlaiž dziesmu
`!volume <0-100>` - Maina skaļumu
`!shuffle` - Samaina rindu
`!clear` - Iztīra rindu
`!remove <#>` - Izņem dziesmu no rindas

**📋 Vispārējās komandas:**
`!queue` - Parāda mūzikas rindu
`!nowplaying` / `!np` - Pašreizējā dziesma
`!status` - Bota statuss
`!commands` - Komandu saraksts

**💡 Piemēri:**
`!play Rick Astley Never Gonna Give You Up`
`!play https://youtube.com/watch?v=...`
`!volume 75`
`!remove 2`"""
    
    await ctx.send(help_text)

# Slash komandu DJ role pārbaude
def has_dj_role_slash():
    """Pārbauda vai lietotājam ir DJ role (slash komandām)"""
    def check(interaction: discord.Interaction) -> bool:
        # Administrator vienmēr var
        if interaction.user.guild_permissions.administrator:
            return True
        
        # Pārbauda DJ role
        dj_role = discord.utils.get(interaction.user.roles, name="DJ")
        return dj_role is not None
    
    return app_commands.check(check)

# SLASH KOMANDAS
@bot.tree.command(name="join", description="Pievieno botu voice kanālam")
@has_dj_role_slash()
async def slash_join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ Tu neesi voice kanālā!", ephemeral=True)
        return
    
    channel = interaction.user.voice.channel
    
    if interaction.guild.voice_client is not None:
        if interaction.guild.voice_client.channel == channel:
            await interaction.response.send_message(f"✅ Es jau esmu **{channel}** kanālā!")
            return
        else:
            await interaction.guild.voice_client.move_to(channel)
            await interaction.response.send_message(f"🔄 Pārvietojos uz **{channel}** kanālu!")
            return
    
    try:
        await channel.connect()
        await interaction.response.send_message(f"✅ Pievienojies **{channel}** kanālam!")
    except Exception as e:
        await interaction.response.send_message("❌ Nevarēju pievienoties voice kanālam!", ephemeral=True)

@bot.tree.command(name="play", description="Atskaņo dziesmu no YouTube")
@app_commands.describe(search="YouTube URL vai dziesmas nosaukums")
@has_dj_role_slash()
async def slash_play(interaction: discord.Interaction, search: str):
    # Defer response jo var būt lēns
    await interaction.response.defer()
    
    # Pārbauda vai bots ir voice kanālā
    if not interaction.guild.voice_client:
        if interaction.user.voice:
            await interaction.user.voice.channel.connect()
        else:
            await interaction.followup.send("❌ Tu neesi voice kanālā!")
            return
    
    guild_id = interaction.guild.id
    if guild_id not in music_queues:
        music_queues[guild_id] = deque()
    
    try:
        # Meklē un sagatavo dziesmu
        player = await YTDLSource.from_url(search, loop=bot.loop, stream=True)
        
        # Pievieno rindā
        music_queues[guild_id].append(player)
        
        # Ja nekas neatskaņojas, sāk atskaņot
        if not interaction.guild.voice_client.is_playing():
            await play_next_slash(interaction)
        else:
            await interaction.followup.send(f"➕ **{player.title}** pievienots rindai!")
            
    except Exception as e:
        await interaction.followup.send("❌ Nevarēju ielādēt dziesmu!")

@bot.tree.command(name="queue", description="Parāda mūzikas rindu")
async def slash_queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        await interaction.response.send_message("📝 Mūzikas rinda ir tukša!")
        return
    
    queue_list = []
    for i, player in enumerate(list(music_queues[guild_id])[:10], 1):
        queue_list.append(f"{i}. {player.title}")
    
    queue_text = "🎵 **Mūzikas rinda:**\n" + "\n".join(queue_list)
    
    if len(music_queues[guild_id]) > 10:
        queue_text += f"\n\n**Un vēl:** +{len(music_queues[guild_id]) - 10} dziesmas"
    
    await interaction.response.send_message(queue_text)

@bot.tree.command(name="skip", description="Izlaiž pašreizējo dziesmu")
@has_dj_role_slash()
async def slash_skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏭️ Dziesma izlaista!")
    else:
        await interaction.response.send_message("❌ Nekas neatskaņojas!", ephemeral=True)

@bot.tree.command(name="pause", description="Pauzē mūziku")
@has_dj_role_slash()
async def slash_pause(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.pause()
        await interaction.response.send_message("⏸️ Mūzika pauzēta!")
    else:
        await interaction.response.send_message("❌ Nekas neatskaņojas!", ephemeral=True)

@bot.tree.command(name="resume", description="Turpina mūziku")
@has_dj_role_slash()
async def slash_resume(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_paused():
        interaction.guild.voice_client.resume()
        await interaction.response.send_message("▶️ Mūzika turpināta!")
    else:
        await interaction.response.send_message("❌ Mūzika nav pauzēta!", ephemeral=True)

@bot.tree.command(name="stop", description="Aptur mūziku un iztīra rindu")
@has_dj_role_slash()
async def slash_stop(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        guild_id = interaction.guild.id
        if guild_id in music_queues:
            music_queues[guild_id].clear()
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("⏹️ Mūzika apturēta un rinda iztīrīta!")
    else:
        await interaction.response.send_message("❌ Nekas neatskaņojas!", ephemeral=True)

@bot.tree.command(name="volume", description="Maina skaļumu")
@app_commands.describe(level="Skaļuma līmenis (0-100)")
@has_dj_role_slash()
async def slash_volume(interaction: discord.Interaction, level: int):
    if interaction.guild.voice_client is None:
        await interaction.response.send_message("❌ Nav pievienojies voice kanālam!", ephemeral=True)
        return
    
    if 0 <= level <= 100:
        interaction.guild.voice_client.source.volume = level / 100
        await interaction.response.send_message(f"🔊 Skaļums uzstādīts uz {level}%")
    else:
        await interaction.response.send_message("❌ Skaļumam jābūt starp 0 un 100!", ephemeral=True)

@bot.tree.command(name="djhelp", description="Parāda visas bot komandas")
async def slash_djhelp(interaction: discord.Interaction):
    """Slash versija help komandai"""
    help_text = """🎵 **DJShaled - Discord Music Bot**
Lietotāji ar **DJ** role var vadīt mūziku

**🎧 DJ Komandas:**
`/join` - Pievieno botu voice kanālam  
`/play <search>` - Atskaņo mūziku
`/pause` - Pauzē mūziku
`/resume` - Turpina mūziku
`/stop` - Aptur mūziku un iztīra rindu
`/skip` - Izlaiž dziesmu
`/volume <level>` - Maina skaļumu (0-100)
`/shuffle` - Samaina rindu
`/clear` - Iztīra rindu
`/remove <position>` - Izņem dziesmu no rindas

**📋 Vispārējās komandas:**
`/queue` - Parāda mūzikas rindu
`/nowplaying` - Pašreizējā dziesma
`/djhelp` - Šis palīdzības saraksts

**💡 Piemēri:**
`/play Rick Astley Never Gonna Give You Up`
`/volume 75`
`/remove 2`

*Pieejamas arī ! komandas: !help, !play utt.*"""
    
    await interaction.response.send_message(help_text, ephemeral=True)

@bot.tree.command(name="leave", description="Iziet no voice kanāla")
@has_dj_role_slash()
async def slash_leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        guild_id = interaction.guild.id
        if guild_id in music_queues:
            music_queues[guild_id].clear()
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 Atstāju voice kanālu!")
    else:
        await interaction.response.send_message("❌ Es neesmu voice kanālā!", ephemeral=True)

@bot.tree.command(name="shuffle", description="Samaina mūzikas rindu nejauši")
@has_dj_role_slash()
async def slash_shuffle(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 1:
        import random
        queue_list = list(music_queues[guild_id])
        random.shuffle(queue_list)
        music_queues[guild_id] = deque(queue_list)
        await interaction.response.send_message(f"🔀 Rinda samaisīta! ({len(queue_list)} dziesmas)")
    else:
        await interaction.response.send_message("❌ Rindā nav pietiekami daudz dziesmu!", ephemeral=True)

@bot.tree.command(name="clear", description="Iztīra mūzikas rindu")
@has_dj_role_slash()
async def slash_clear(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in music_queues:
        cleared_count = len(music_queues[guild_id])
        music_queues[guild_id].clear()
        await interaction.response.send_message(f"🗑️ Iztīrīju {cleared_count} dziesmas no rindas!")
    else:
        await interaction.response.send_message("📝 Rinda jau ir tukša!", ephemeral=True)

@bot.tree.command(name="remove", description="Izņem dziesmu no rindas")
@app_commands.describe(position="Dziesmas pozīcija rindā (1, 2, 3...)")
@has_dj_role_slash()
async def slash_remove(interaction: discord.Interaction, position: int):
    guild_id = interaction.guild.id
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        await interaction.response.send_message("❌ Rinda ir tukša!", ephemeral=True)
        return
    
    if 1 <= position <= len(music_queues[guild_id]):
        queue_list = list(music_queues[guild_id])
        removed_song = queue_list.pop(position - 1)
        music_queues[guild_id] = deque(queue_list)
        await interaction.response.send_message(f"❌ Izņēmu: **{removed_song.title}** (pozīcija {position})")
    else:
        await interaction.response.send_message(f"❌ Nederīga pozīcija! Izmanto 1-{len(music_queues[guild_id])}", ephemeral=True)

# Palīgfunkcija slash komandām
async def play_next_slash(interaction):
    """Atskaņo nākamo dziesmu no rindas (slash version)"""
    guild_id = interaction.guild.id
    
    if guild_id not in music_queues or len(music_queues[guild_id]) == 0:
        return
    
    player = music_queues[guild_id].popleft()
    
    def after_playing(error):
        if error:
            print(f'Atskaņošanas kļūda: {error}')
        
        # Atskaņo nākamo dziesmu
        coro = play_next(interaction)
        fut = asyncio.run_coroutine_threadsafe(coro, bot.loop)
        try:
            fut.result()
        except:
            pass
    
    interaction.guild.voice_client.play(player, after=after_playing)
    await interaction.followup.send(f"🎵 Tagad atskaņoju: **{player.title}**")

# Error handler slash komandām
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("❌ Tev nepieciešama **DJ** role!", ephemeral=True)
    else:
        print(f"Slash command error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Kaut kas nogāja greizi!", ephemeral=True)

@bot.command(name='sync', help='Sinhronizē slash komandas (tikai admin)')
@commands.has_permissions(administrator=True)
async def sync_commands(ctx):
    """Manuāli sinhronizē slash komandas"""
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Sinhronizēju {len(synced)} slash komandas! Var aizņemt līdz 1 stundai.")
    except Exception as e:
        await ctx.send(f"❌ Kļūda sinhronizējot: {e}")

@bot.command(name='debug', help='Debug informācija')
async def debug(ctx):
    """Debug komanda"""
    try:
        # Pārbauda permissions
        perms = ctx.channel.permissions_for(ctx.guild.me)
        
        debug_info = f"""🔍 **Debug Info:**
**Bot ID:** {bot.user.id}
**Guild:** {ctx.guild.name}
**Channel:** {ctx.channel.name}

**Permissions:**
Send Messages: {'✅' if perms.send_messages else '❌'}
Read Message History: {'✅' if perms.read_message_history else '❌'}
Connect: {'✅' if perms.connect else '❌'}
Speak: {'✅' if perms.speak else '❌'}
Use Voice Activity: {'✅' if perms.use_voice_activation else '❌'}

**Slash Commands:** {len(bot.tree.get_commands())} komandas
**Voice Client:** {'✅' if ctx.voice_client else '❌'}
**Application Commands Scope:** {'✅' if hasattr(bot, 'tree') else '❌'}"""
        
        await ctx.send(debug_info)
    except Exception as e:
        await ctx.send(f"Debug kļūda: {e}")

# Pievienojam test komandu
@bot.command(name='testplay', help='Testē dažādas atskaņošanas metodes')
@has_dj_role()
async def testplay(ctx, *, search_term):
    """Test komanda dažādām meklēšanas metodēm"""
    if not ctx.voice_client:
        if ctx.author.voice:
            await ctx.author.voice.channel.connect()
        else:
            await ctx.send("❌ Tu neesi voice kanālā!")
            return
    
    loading_msg = await ctx.send("🔍 Testēju dažādas meklēšanas metodes...")
    
    # Test methods
    methods = [
        f"ytsearch:{search_term}",
        f"ytsearch5:{search_term}",
        search_term,
        f"{search_term} official audio",
        f"{search_term} lyrics"
    ]
    
    for i, method in enumerate(methods, 1):
        try:
            await loading_msg.edit(content=f"🔍 Mēģinu metodi {i}/5: {method[:50]}...")
            
            # Test extraction
            data = await asyncio.get_event_loop().run_in_executor(
                None, 
                lambda: ytdl.extract_info(method, download=False)
            )
            
            if 'entries' in data and data['entries']:
                title = data['entries'][0].get('title', 'Unknown')
                await loading_msg.edit(content=f"✅ Metode {i} strādā: **{title}**")
                return
            elif data.get('title'):
                await loading_msg.edit(content=f"✅ Metode {i} strādā: **{data['title']}**")
                return
                
        except Exception as e:
            print(f"Method {i} failed: {e}")
            continue
    
    await loading_msg.edit(content="❌ Visas metodes neizdevās. YouTube var bloķēt Railway serveri.")

# Palaiž botu
if __name__ == "__main__":
    # Iegūst token no environment variable
    token = os.getenv('DISCORD_BOT_TOKEN')
    
    if not token:
        print("❌ DISCORD_BOT_TOKEN nav atrasts environment variables!")
        print("Pārbaudi vai ir uzstādīts DISCORD_BOT_TOKEN")
        exit(1)
    
    try:
        bot.run(token)
    except Exception as e:
        print(f"❌ Kļūda palaižot botu: {e}")
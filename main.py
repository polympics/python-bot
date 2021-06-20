import discord
import json
import polympics
import sys
from aiohttp import web
from discord.ext import commands

import config

bot = commands.Bot(
    'p!', intents=discord.Intents.all()
)
bot.check(
    commands.guild_only()
)
bot.check(
    commands.check_any(
        commands.has_any_role(('Staff', 'Mod', 'Director', 'Polympic Committee', 'Infrastructure')),
        commands.is_owner(),
    )
)

server = web.Application()
polympics_client = polympics.AppClient(
    polympics.Credentials(config.api_user, config.api_token),
    base_url=config.base_url
)


def channel_name(name: str) -> str:
    return name.replace(' ', '-').lower()


async def create_team_on_discord(team: polympics.Team, guild: discord.Guild) -> (discord.Role, discord.TextChannel):
    """
    Create team role & Team Channel in Discord server if they don't exist already,
    return the discord Objects - role, channel
    """
    
    team_category: discord.CategoryChannel = discord.utils.get(guild.categories, id=846777453640024076)
    
    # Strip non-ascii characters
    no_emoji_name = team.name.encode('ascii', 'ignore').decode('ascii').strip()
    
    chan_name = channel_name(team.name)
    role = discord.utils.get(guild.roles, name=no_emoji_name) or await guild.create_role(
        reason='Create Team role because it didn\'t exist',
        name=no_emoji_name
    )
    
    if chan := discord.utils.get(team_category.channels, name=chan_name):
        channel = chan
    else:
        channel = team_category.create_text_channel(
            chan_name, reason='Create Team channel because it didn\'t exist',
            overwrites={
                role: discord.PermissionOverwrite(read_messages=True),
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
            }
        )
        
    return role, channel


async def callback(request: web.Request):
    # Verify it game from the polympics server
    if request.headers['Authorization'] != f'Bearer {config.secret}':
        print(f'Authorization doesn\'t match: {request.headers["Authorization"]} != {config.secret}')
        return web.Response(status=403)
    
    # Load the polympics server
    guild: discord.Guild = bot.get_guild(814317488418193478)
    print('Guild Loaded')
    
    # Load the data sent via the callback
    data: dict = await request.json()
    
    # Load the account and team from the data
    account: polympics.Account = polympics.Account.from_dict(d) if (d := data['account']) is not None else None
    team: polympics.Team = polympics.Team.from_dict(d) if (d := data['team']) is not None else None
    
    # is the member in the server?
    member: discord.Member = guild.get_member(account.id)
    if member is None:
        print('Member doesn\'t exist')
        # If not, return
        return
    print("member exists")
    if team is None:
        print("Team is None")
        # They've left whichever team they were on. Remove all team roles.
        await member.remove_roles(
            *filter(lambda x: x.name.startswith('Team:'), guild.roles)
        )
    else:
        print("Creating channel")
        role, channel = create_team_on_discord(team, guild)
        await member.add_roles(role)
    
    return web.Response(status=200)


@bot.command()
async def ping(ctx: commands.Context, *, _: str = None):
    return await ctx.send(f'Pong! `{bot.latency}`')


@bot.command()
@commands.is_owner()
async def restart(ctx: commands.Context, *, _: str = None):
    await ctx.send(f'Shutting down server & Polympics client...')
    await server.shutdown()
    await server.cleanup()
    await polympics_client.close()
    await ctx.send(f'Complete. Shutting down bot.')
    sys.exit(0)


@bot.event
async def on_ready():
    await polympics_client.create_callback(
        polympics.EventType.ACCOUNT_TEAM_UPDATE,
        config.callback_url,
        config.secret
    )
    
    # Add the routes for the server
    server.add_routes(
        [
            web.post("/callback/account_team_update", callback),
        ],
    )
    
    # logging.basicConfig(level=logging.DEBUG)
    
    # Create an AppRunner
    runner = web.AppRunner(server)
    # Set it up
    await runner.setup()
    # Create a TCPSite object which actually serves the callback
    site = web.TCPSite(runner, 'localhost', config.port)
    # Start the site
    await site.start()


if __name__ == '__main__':
    bot.run(config.discord_token)

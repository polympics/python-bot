# --------------------------------------------------------------------------------------------- #
# Copyright (c) 2021 Jasper Harrison. This file is licensed under the terms of the MIT License. #
# Please see the LICENSE file in the root of this repository for more details.                  #
# --------------------------------------------------------------------------------------------- #
import discord
import json
import pathlib
import polympics
import sys
from asyncio import Lock
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
        commands.has_any_role(('Staff', 'Mod', 'Polympic Committee', 'Infrastructure')),
        commands.is_owner(),
    )
)

DATA_PATH = pathlib.Path(__file__).parent.joinpath("data.json")
DATA_LOCK = Lock()
DATA = {}


async def store(key, value):
    async with DATA_LOCK:
        DATA[key] = value
        json.dump(DATA, DATA_PATH.open('w'))


async def get(key, default=None):
    async with DATA_LOCK:
        return DATA.get(key, default)


server = web.Application()
polympics_client = polympics.AppClient(
    polympics.Credentials(config.api_user, config.api_token),
    base_url=config.base_url
)


def strip_special(text):
    return text.encode('ascii', 'ignore').decode('ascii').strip()


async def create_team_on_discord(team: polympics.Team, guild: discord.Guild) -> (discord.Role, discord.TextChannel):
    """
    Create team role & Team Channel in Discord server if they don't exist already,
    return the discord Objects - role, channel
    """
    
    team_category: discord.CategoryChannel = discord.utils.get(guild.categories, id=846777453640024076)
    
    # Strip non-ascii characters
    no_emoji_name = strip_special(team.name)
    chan_name = no_emoji_name.replace(' ', '-').lower()
    
    team_data = await get(no_emoji_name, None)
    
    if team_data is None:
        role = await guild.create_role(
            reason='Create Team role because it didn\'t exist',
            name=f"Team: {no_emoji_name}"
        )
        # team-spirit
        c: discord.TextChannel = guild.get_channel(846777537799651388)
        await c.set_permissions(
            role, overwrite=discord.PermissionOverwrite(read_messages=True)
        )

        channel = await team_category.create_text_channel(
            chan_name, reason='Create Team channel because it didn\'t exist',
            overwrites={
                role: discord.PermissionOverwrite(read_messages=True),
                guild.default_role: discord.PermissionOverwrite(read_messages=False),
                # Muted role
                guild.get_role(856036892801630228): discord.PermissionOverwrite(send_messages=False,
                                                                                add_reactions=False)
            }
        )
        
        team_data = {
            'role': role.id,
            'channel': channel.id
        }
        
        await store(no_emoji_name, team_data)
        
    else:
        role = guild.get_role(team_data['role'])
        
    return role


async def callback(request: web.Request):
    # Verify it game from the polympics server
    if request.headers['Authorization'] != f'Bearer {config.secret}':
        print(f'Authorization doesn\'t match: {request.headers["Authorization"]} != {config.secret}')
        return web.Response(status=403)
    
    # Load the polympics server
    guild: discord.Guild = bot.get_guild(814317488418193478)
    
    # Load the data sent via the callback
    data: dict = await request.json()
    
    # Load the account and team from the data
    account: polympics.Account = polympics.Account.from_dict(d) if (d := data['account']) is not None else None
    team: polympics.Team = polympics.Team.from_dict(d) if (d := data['team']) is not None else None
    
    # is the member in the server?
    member: discord.Member = guild.get_member(account.id)
    if member is None:
        # If not, return
        print('Member not found')
        return
    
    # Remove any current team roles
    await member.remove_roles(
        *filter(lambda x: x.name.startswith('Team:'), guild.roles)
    )
    if team is not None:
        # Add new team roles if they're being added to a team
        role = await create_team_on_discord(team, guild)
        await member.add_roles(role)
    
    return web.Response(status=200)


@bot.command()
async def ping(ctx: commands.Context, *, _: str = None):
    return await ctx.send(f'Pong! `{bot.latency}`')


@bot.command()
@commands.is_owner()
async def check(ctx: commands.Context):
    
    guild: discord.Guild = ctx.guild
    
    async with ctx.typing():
    
        async for member in guild.fetch_members(limit=None):
            member: discord.Member
            try:
                account = await polympics_client.get_account(member.id)
            except Exception as e:
                print('Error with member', member.display_name, e)
                continue
            
            if account is None:
                await ctx.send(f'Member {member.display_name} not registered.')
                continue
            
            if account.team is not None:
                role = await create_team_on_discord(account.team, guild)
                await member.remove_roles(
                    *filter(lambda x: x.name.startswith('Team:'), guild.roles)
                )
                await member.add_roles(
                    role
                )
                await ctx.send(f"Fixed team roles for {member.display_name} - now on {account.team.name}")
        await ctx.send('Done')


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
async def on_user_update(before: discord.User, after: discord.User):
    try:
        if (account := await polympics_client.get_account(before.id)) is not None:
            
            if before.avatar != after.avatar:
                ext = 'gif' if after.is_avatar_animated() else 'png'
                avatar_url = f'https://cdn.discordapp.com/avatars/{account.id}/{after.avatar}.{ext}'
            else:
                avatar_url = account.avatar_url
            
            await polympics_client.update_account(
                account, name=after.name, discriminator=after.discriminator, avatar_url=avatar_url
            )
    except Exception as e:
        print(e)
        

@bot.event
async def on_member_join(member: discord.Member):
    try:
        account = await polympics_client.get_account(member.id)
    except Exception:
        return
    else:
        if account is None:
            return
    
    if account.team is not None:
        guild = bot.get_guild(814317488418193478)
        
        role = await create_team_on_discord(account.team, guild)
        await member.remove_roles(
            *filter(lambda x: x.name.startswith('Team:'), guild.roles)
        )
        await member.add_roles(
            role
        )


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
    DATA = json.loads(DATA_PATH.read_bytes())
    
    bot.run(config.discord_token)

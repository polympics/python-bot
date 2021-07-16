# -------------------------------------------------------------------------- #
# Copyright (c) 2021 Jasper Harrison. This file is licensed under the terms  #
# of the MIT License. Please see the LICENSE file in the root of this        #
# repository for more details.                                               #
# -------------------------------------------------------------------------- #
import csv
import io
import json
import pathlib
import sys
from asyncio import Lock
from typing import Any, Optional

import discord
import polympics
from aiohttp import web
from discord.ext import commands

import config


ADMIN_ROLES = 'Staff', 'Mod', 'Polympic Committee', 'Infrastructure'
TEAM_CATEGORY_ID = 846777453640024076
TEAM_CATEGORY_2_ID = 859349825774682112
TEAM_SPIRIT_ID = 846777537799651388
MUTED_ROLE_ID = 856036892801630228
GUILD_ID = 814317488418193478

bot = commands.Bot('p!', intents=discord.Intents.all())
bot.check(commands.guild_only())

default_check = commands.check_any(
    commands.has_any_role(*ADMIN_ROLES),
    commands.is_owner(),
)

DATA_PATH = pathlib.Path(__file__).parent / 'data.json'
DATA_LOCK = Lock()
DATA = {}


async def store(key: str, value: Any):
    async with DATA_LOCK:
        DATA[key] = value
        json.dump(DATA, DATA_PATH.open('w'))


async def get(key: str, default: Any = None) -> Any:
    async with DATA_LOCK:
        return DATA.get(key, default)


server = web.Application()
polympics_client = polympics.AppClient(
    polympics.Credentials(config.api_user, config.api_token),
    base_url=config.base_url
)


def strip_special(text: str) -> str:
    return text.encode('ascii', 'ignore').decode('ascii').strip()


async def create_team_on_discord(
        team: polympics.Team, guild: discord.Guild) -> discord.Role:
    """Ensure team role and channel exist in the server.

    Creates them if they don't exist already.
    """
    team_category: discord.CategoryChannel = guild.get_channel(
        TEAM_CATEGORY_ID
    )
    team_category_2: discord.CategoryChannel = guild.get_channel(
        TEAM_CATEGORY_2_ID
    )

    # Strip non-ascii characters
    no_emoji_name = strip_special(team.name)
    chan_name = no_emoji_name.replace(' ', '-').lower()

    team_data = await get(str(team.id), await get(no_emoji_name, None))

    if team_data is None:
        role = await guild.create_role(
            reason='Create Team role because it didn\'t exist',
            name=f"Team: {no_emoji_name}"
        )
        c: discord.TextChannel = guild.get_channel(TEAM_SPIRIT_ID)
        await c.set_permissions(
            role, overwrite=discord.PermissionOverwrite(read_messages=True)
        )

        cat = (
            team_category if len(team_category.channels) < 50
            else team_category_2
        )

        channel = await cat.create_text_channel(
            chan_name, reason='Create Team channel because it didn\'t exist',
            overwrites={
                role: discord.PermissionOverwrite(read_messages=True),
                guild.default_role: discord.PermissionOverwrite(
                    read_messages=False
                ),
                guild.get_role(MUTED_ROLE_ID): discord.PermissionOverwrite(
                    send_messages=False, add_reactions=False
                )
            }
        )

        team_data = {
            'role': role.id,
            'channel': channel.id
        }

        await store(str(team.id), team_data)

    else:
        role = guild.get_role(team_data['role'])

    return role


async def callback(request: web.Request) -> Optional[web.Response]:
    # Verify it came from the polympics server
    if request.headers['Authorization'] != f'Bearer {config.secret}':
        print('Bad token, ignoring request.')
        return web.Response(status=403)

    # Load the polympics server
    guild: discord.Guild = bot.get_guild(814317488418193478)

    # Load the data sent via the callback
    data: dict = await request.json()
    payload: polympics.AccountTeamUpdateEvent = polympics.account_team_update(data)

    # Is the member in the server?
    member: discord.Member = guild.get_member(payload.account.id)
    if member is None:
        # If not, return
        print('Member not found')
        return

    # Remove any current team roles
    await member.remove_roles(
        *filter(lambda x: x.name.startswith('Team:'), member.roles)
    )
    if payload.team is not None:
        # Add new team roles if they're being added to a team
        role = await create_team_on_discord(payload.team, guild)
        await member.add_roles(role)

    return web.Response(status=200)


@bot.command()
@default_check
async def ping(ctx: commands.Context, *, _: str = None):
    await ctx.send(f'Pong! `{bot.latency}`')


@bot.command(brief='Export users as a CSV.')
@default_check
async def export(ctx: commands.Context):
    """Export a CSV containing each user with their team and event roles."""
    file = io.StringIO()
    writer = csv.writer(file)
    writer.writerow(['ID', 'Username', 'Team', 'Events', 'FFA Roles'])
    user_count = no_team_count = 0
    async for member in ctx.guild.fetch_members(limit=None):
        team = None
        events = []
        ffa_roles = []
        for role in member.roles:
            if role.name.startswith('Team: '):
                team = role.name.removeprefix('Team: ')
            if role.name.startswith('Event: '):
                events.append(role.name.removeprefix('Event: '))
            if role.name[:5] in ('FFA 1', 'FFA 2', 'FFA 3', 'FFA 4'):
                ffa_roles.append(role.name)
        if team:
            writer.writerow([member.id, str(member), team, ';'.join(events), ';'.join(ffa_roles)])
            user_count += 1
        else:
            no_team_count += 1
    file.seek(0)
    await ctx.send(
        f'Exported {user_count} users, skipped {no_team_count} without a '
        'team role.',
        file=discord.File(file, filename='polympics_users.csv')
    )


@bot.command()
async def reload(ctx: commands.Context, *, member: str = None):
    async with ctx.typing():
        if member is None:
            member: discord.Member = ctx.author
        elif discord.utils.get(ctx.author.roles, name='Staff') is not None:
            try:
                member: discord.Member = await commands.MemberConverter(
                    ).convert(ctx, member)
            except Exception as e:
                print(f'Unable to find user {member}. Error: {e}')
                return await ctx.send(
                    'Unable to find user '
                    f'**{discord.utils.escape_markdown(member)}**. Try a '
                    'mention or a user ID.',
                    allowed_mentions=discord.AllowedMentions.none()
                )
        else:
            return await ctx.send(
                'Only staff members have permission to use this command on '
                'another user.'
            )

        try:
            account = await polympics_client.get_account(member.id)
        except Exception as e:
            print(e)
            account = None

        if account is None:
            return await ctx.send(
                f'{member.display_name} is not signed up to the Polympics.'
            )

        await member.remove_roles(
            *filter(lambda x: x.name.startswith('Team:'), member.roles)
        )
        if (team := account.team) is not None:
            role = await create_team_on_discord(team, ctx.guild)
            await member.add_roles(
                role
            )
            await ctx.send(
                f'Synced team roles for {member.display_name} to {team.name}'
            )
        else:
            await ctx.send(f'**{member.display_name}** has no team.')


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
                await ctx.send(
                    f'Fixed team roles for {member.display_name} - now on '
                    f'{account.team.name}.'
                )
        await ctx.send('Done')


@bot.command()
@commands.is_owner()
async def restart(ctx: commands.Context, *, _: str = None):
    await ctx.send('Shutting down server & Polympics client...')
    await server.shutdown()
    await server.cleanup()
    await polympics_client.close()
    await ctx.send('Complete. Shutting down bot.')
    sys.exit(0)


@bot.event
async def on_user_update(before: discord.User, after: discord.User):
    try:
        # Will error if account not found.
        account = await polympics_client.get_account(before.id)
        await polympics_client.update_account(
            account,
            name=after.name,
            discriminator=after.discriminator,
            avatar_url=str(after.avatar_url).split('?')[0]
        )
    except Exception as e:
        print(e)


@bot.event
async def on_member_join(member: discord.Member):
    try:
        account = await polympics_client.get_account(member.id)
    except Exception:
        return

    if account and account.team is not None:
        guild = bot.get_guild(GUILD_ID)

        role = await create_team_on_discord(account.team, guild)
        await member.remove_roles(
            *filter(lambda x: x.name.startswith('Team:'), member.roles)
        )
        await member.add_roles(role)


@bot.event
async def on_ready():
    await polympics_client.create_callback(
        polympics.EventType.ACCOUNT_TEAM_UPDATE,
        config.callback_url,
        config.secret
    )

    # Add the routes for the server
    server.add_routes([
        web.post('/callback/account_team_update', callback),
    ])

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
    try:
        DATA = json.loads(DATA_PATH.read_bytes())
    except FileNotFoundError:
        pass

    bot.run(config.discord_token)

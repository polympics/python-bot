import logging

import discord
from discord.ext import commands
import polympics
from aiohttp import web

import config


bot = commands.Bot(
    'p!'
)
bot.check(
    commands.guild_only()
)

server = web.Application()
polympics_client: [polympics.AppClient, None] = None


async def callback(request: web.Request):
    json_data = await request.json()
    
    print(type(json_data))
    
    return web.Response(status=200)


async def hello(_):
    return web.Response(body="Hello!")


@bot.command()
async def ping(ctx: commands.Context, *, _: str = None):
    return await ctx.send(f'Pong! `{bot.latency}`')


@bot.event
async def on_ready():
    global polympics_client
    
    polympics_client = polympics.AppClient(
        polympics.Credentials(config.api_user, config.api_token),
        base_url=config.base_url
    )
    
    await polympics_client.create_callback(
        polympics.EventType.ACCOUNT_TEAM_UPDATE,
        config.callback_url,
        config.secret
    )
    
    # Add the routes for the server
    server.add_routes(
        [
            web.post("/callback/account_team_update", callback),
            web.get("/", hello)
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

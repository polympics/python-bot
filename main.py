import polympics
import sys
from aiohttp import web
from discord.ext import commands

import config

bot = commands.Bot(
    'p!'
)
bot.check(
    commands.guild_only()
)

server = web.Application()
polympics_client = polympics.AppClient(
    polympics.Credentials(config.api_user, config.api_token),
    base_url=config.base_url
)


async def callback(request: web.Request):
    json_data = await request.json()
    
    print(type(json_data))
    
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

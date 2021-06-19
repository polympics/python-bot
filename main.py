import discord
import polympics
from aiohttp import web

import config


client = discord.Client()
server = web.Application()
polympics_client: [polympics.AppClient, None] = None


async def callback(request: web.Request):
    print(request.headers)
    print(await request.json())
    
    return web.Response(status=200)


@client.event
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
        [web.post("/callback/account_team_update", callback)]
    )
    # Create an AppRunner
    runner = web.AppRunner(server)
    # Set it up
    await runner.setup()
    # Create a TCPSite object which actually serves the callback
    site = web.TCPSite(runner, 'localhost', config.port)
    # Start the site
    await site.start()


if __name__ == '__main__':
    client.run(config.discord_token)

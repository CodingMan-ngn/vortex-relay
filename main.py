import os, asyncio, aiohttp
import discord
from discord.ext import tasks

WORKER_URL   = os.environ['WORKER_URL']      # https://cookie-snap-keys.j26064135.workers.dev
RELAY_SECRET = os.environ['ADMIN_HASH']       # same as your Cloudflare ADMIN_HASH

intents = discord.Intents.default()
intents.message_content = True
intents.guilds          = True
intents.members         = True
intents.reactions       = True
intents.invites         = True

client = discord.Client(intents=intents)
session: aiohttp.ClientSession | None = None
invite_cache: dict[int, list] = {}   # guild_id -> list[Invite]

async def forward(path, payload):
    global session
    if session is None:
        session = aiohttp.ClientSession()
    try:
        async with session.post(
            f"{WORKER_URL}/relay/{path}",
            json=payload,
            headers={"X-Relay-Secret": RELAY_SECRET},
            timeout=aiohttp.ClientTimeout(total=8)
        ) as r:
            if r.status >= 400:
                print(f"[relay] {path} -> {r.status} {await r.text()}")
    except Exception as e:
        print(f"[relay] error on {path}: {e}")

@client.event
async def on_ready():
    print(f"Relay online as {client.user} ({client.user.id})")
    # Cache invites for every guild
    for g in client.guilds:
        try:
            invite_cache[g.id] = await g.invites()
        except Exception as e:
            print(f"[invites] cache failed for {g.name}: {e}")

@client.event
async def on_message(message):
    if message.author.bot: return
    if not message.guild: return
    await forward("message", {
        "guild_id":    str(message.guild.id),
        "guild_name":  message.guild.name,
        "channel_id":  str(message.channel.id),
        "message_id":  str(message.id),
        "author_id":   str(message.author.id),
        "author_name": str(message.author),
        "author_tag":  str(message.author),
        "content":     message.content or "",
        "mentions":    [str(u.id) for u in message.mentions],
        "role_ids":    [str(r.id) for r in getattr(message.author, "roles", []) if r.name != "@everyone"],
    })

@client.event
async def on_raw_reaction_add(payload):
    if payload.user_id == client.user.id: return
    await forward("reaction", {
        "guild_id":   str(payload.guild_id) if payload.guild_id else None,
        "channel_id": str(payload.channel_id),
        "message_id": str(payload.message_id),
        "user_id":    str(payload.user_id),
        "emoji":      str(payload.emoji.name) if payload.emoji.is_unicode_emoji() else str(payload.emoji.id),
    })

@client.event
async def on_member_join(member):
    # Diff invites to find the inviter
    inviter_id = None
    inviter_count = None
    invite_code = None
    try:
        invites_after = await member.guild.invites()
        before = invite_cache.get(member.guild.id, [])
        for inv in invites_after:
            prev = next((i for i in before if i.code == inv.code), None)
            if prev and inv.uses > prev.uses:
                inviter_id = str(inv.inviter.id) if inv.inviter else None
                inviter_count = inv.uses
                invite_code = inv.code
                break
        invite_cache[member.guild.id] = invites_after
    except Exception as e:
        print(f"[invites] diff failed: {e}")

    await forward("join", {
        "guild_id":      str(member.guild.id),
        "guild_name":    member.guild.name,
        "guild_count":   member.guild.member_count,
        "user_id":       str(member.id),
        "user_name":     member.name,
        "user_tag":      str(member),
        "avatar":        str(member.display_avatar.url) if member.display_avatar else None,
        "inviter_id":    inviter_id,
        "inviter_count": inviter_count,
        "invite_code":   invite_code,
        "created_at":    int(member.created_at.timestamp() * 1000),
    })

@client.event
async def on_member_remove(member):
    # Reverse the invite credit if we know who invited them
    await forward("leave", {
        "guild_id":   str(member.guild.id),
        "guild_name": member.guild.name,
        "guild_count": member.guild.member_count,
        "user_id":    str(member.id),
        "user_name":  member.name,
        "user_tag":   str(member),
    })

if __name__ == "__main__":
    client.run(os.environ['DISCORD_BOT_TOKEN'])

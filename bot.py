import os
import re
import json
import html
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
TICKET_CATEGORY_ID = int(os.getenv("TICKET_CATEGORY_ID"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID"))

SUPPORT_ROLE_ID = int(os.getenv("SUPPORT_ROLE_ID"))
ACHAT_ROLE_ID = int(os.getenv("ACHAT_ROLE_ID"))
PARTENARIAT_ROLE_ID = int(os.getenv("PARTENARIAT_ROLE_ID"))
AUTRE_ROLE_ID = int(os.getenv("AUTRE_ROLE_ID"))

TICKET_TYPES = {
    "support": {
        "label": "Support",
        "emoji": "🛠️",
        "description": "Aide technique",
        "prefix": "support",
        "color": 0x3498DB,
        "role_id": SUPPORT_ROLE_ID
    },
    "achat": {
        "label": "Achat",
        "emoji": "💰",
        "description": "Question achat",
        "prefix": "achat",
        "color": 0x2ECC71,
        "role_id": ACHAT_ROLE_ID
    },
    "partenariat": {
        "label": "Partenariat",
        "emoji": "🤝",
        "description": "Demande partenariat",
        "prefix": "partenariat",
        "color": 0x9B59B6,
        "role_id": PARTENARIAT_ROLE_ID
    },
    "autre": {
        "label": "Autre",
        "emoji": "📩",
        "description": "Autre demande",
        "prefix": "autre",
        "color": 0xE67E22,
        "role_id": AUTRE_ROLE_ID
    }
}

DATA_DIR="data"
TRANSCRIPTS_DIR=f"{DATA_DIR}/transcripts"
TICKETS_FILE=f"{DATA_DIR}/tickets.json"

os.makedirs(TRANSCRIPTS_DIR,exist_ok=True)

intents=discord.Intents.default()
intents.guilds=True
intents.members=True
intents.messages=True

bot=commands.Bot(command_prefix="!",intents=intents)

def load_tickets():
    if not os.path.exists(TICKETS_FILE):
        return {}
    try:
        with open(TICKETS_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_tickets(data):
    with open(TICKETS_FILE,"w",encoding="utf-8") as f:
        json.dump(data,f,indent=4)

def sanitize(name):
    name=name.lower()
    name=re.sub(r"[^a-z0-9\-]","-",name)
    name=re.sub(r"-+","-",name).strip("-")
    return name[:90]

def build_topic(owner_id,ticket_type,claimed_by=None):
    claim=str(claimed_by) if claimed_by else "none"
    return f"ticket_owner:{owner_id}|type:{ticket_type}|claimed_by:{claim}"

def extract_meta(channel):
    data={"owner_id":None,"ticket_type":None,"claimed_by":None}
    if not channel.topic:
        return data

    for part in channel.topic.split("|"):
        if part.startswith("ticket_owner:"):
            data["owner_id"]=int(part.split(":")[1])

        elif part.startswith("type:"):
            data["ticket_type"]=part.split(":")[1]

        elif part.startswith("claimed_by:"):
            v=part.split(":")[1]
            if v.isdigit():
                data["claimed_by"]=int(v)

    return data

def is_staff(member,ticket_type):
    role_id=TICKET_TYPES[ticket_type]["role_id"]
    return any(r.id==role_id for r in member.roles)

async def send_log(guild,embed,file=None):
    c=guild.get_channel(LOG_CHANNEL_ID)
    if c:
        if file:
            await c.send(embed=embed,file=file)
        else:
            await c.send(embed=embed)

async def transcript(channel):
    rows=[]
    async for msg in channel.history(limit=None,oldest_first=True):
        rows.append(f"""
        <p><b>{html.escape(str(msg.author))}</b> :
        {html.escape(msg.content)}</p>
        """)

    path=f"{TRANSCRIPTS_DIR}/{channel.name}.html"

    with open(path,"w",encoding="utf-8") as f:
        f.write("<html><body>")
        f.write("".join(rows))
        f.write("</body></html>")

    return path

class TicketModal(discord.ui.Modal,title="Créer un ticket"):

    reason=discord.ui.TextInput(
        label="Explique ta demande",
        style=discord.TextStyle.paragraph,
        required=True
    )

    def __init__(self,ticket_key):
        super().__init__()
        self.ticket_key=ticket_key

    async def on_submit(self,interaction):

        guild=interaction.guild
        user=interaction.user

        tickets=load_tickets()

        if str(user.id) in tickets:
            ch=guild.get_channel(
                tickets[str(user.id)]["channel_id"]
            )
            if ch:
                return await interaction.response.send_message(
                    f"Ticket déjà ouvert : {ch.mention}",
                    ephemeral=True
                )

        data=TICKET_TYPES[self.ticket_key]

        category=guild.get_channel(TICKET_CATEGORY_ID)
        staff_role=guild.get_role(data["role_id"])

        overwrites={
            guild.default_role:discord.PermissionOverwrite(
                view_channel=False
            ),

            user:discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True
            ),

            guild.me:discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True
            )
        }

        if staff_role:
            overwrites[staff_role]=discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True
            )

        channel=await guild.create_text_channel(
            name=sanitize(f"{data['prefix']}-{user.name}"),
            category=category,
            overwrites=overwrites,
            topic=build_topic(
                user.id,
                self.ticket_key
            )
        )

        tickets[str(user.id)] = {
            "channel_id":channel.id
        }

        save_tickets(tickets)

        embed=discord.Embed(
            title=f"{data['emoji']} Ticket {data['label']}",
            description=self.reason.value,
            color=data["color"]
        )

        await channel.send(
            content=f"{user.mention} {staff_role.mention if staff_role else ''}",
            embed=embed,
            view=TicketView()
        )

        await interaction.response.send_message(
            f"Ticket créé {channel.mention}",
            ephemeral=True
        )

class AddMemberModal(discord.ui.Modal,title="Ajouter membre"):

    member_id=discord.ui.TextInput(
        label="ID membre"
    )

    async def on_submit(self,interaction):
        guild=interaction.guild
        channel=interaction.channel

        member=guild.get_member(
            int(self.member_id.value)
        )

        if not member:
            return await interaction.response.send_message(
                "Introuvable",
                ephemeral=True
            )

        await channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True
        )

        await interaction.response.send_message(
            f"{member.mention} ajouté."
        )

class RemoveMemberModal(discord.ui.Modal,title="Retirer membre"):

    member_id=discord.ui.TextInput(
        label="ID membre"
    )

    async def on_submit(self,interaction):

        guild=interaction.guild
        channel=interaction.channel

        member=guild.get_member(
            int(self.member_id.value)
        )

        if not member:
            return await interaction.response.send_message(
                "Introuvable",
                ephemeral=True
            )

        await channel.set_permissions(
            member,
            overwrite=None
        )

        await interaction.response.send_message(
            f"{member.mention} retiré."
        )

class RenameModal(discord.ui.Modal,title="Renommer"):

    new_name=discord.ui.TextInput(
        label="Nouveau nom"
    )

    async def on_submit(self,interaction):
        await interaction.channel.edit(
            name=sanitize(
                self.new_name.value
            )
        )

        await interaction.response.send_message(
            "Renommé."
        )

class TicketSelect(discord.ui.Select):
    def __init__(self):

        options=[]

        for key,data in TICKET_TYPES.items():
            options.append(
                discord.SelectOption(
                    label=data["label"],
                    value=key,
                    emoji=data["emoji"]
                )
            )

        super().__init__(
            placeholder="Choisis une catégorie",
            options=options
        )

    async def callback(self,interaction):
        await interaction.response.send_modal(
            TicketModal(
                self.values[0]
            )
        )

class TicketPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(
            TicketSelect()
        )

class TicketView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.primary
    )
    async def claim(self,interaction,button):

        meta=extract_meta(
            interaction.channel
        )

        if not is_staff(
            interaction.user,
            meta["ticket_type"]
        ):
            return await interaction.response.send_message(
                "Pas autorisé",
                ephemeral=True
            )

        if meta["claimed_by"]:
            return await interaction.response.send_message(
                "Déjà claim",
                ephemeral=True
            )

        await interaction.channel.edit(
            topic=build_topic(
                meta["owner_id"],
                meta["ticket_type"],
                interaction.user.id
            )
        )

        await interaction.response.send_message(
            f"{interaction.user.mention} a claim le ticket."
        )

    @discord.ui.button(
        label="Unclaim",
        style=discord.ButtonStyle.secondary
    )
    async def unclaim(self,interaction,button):

        meta=extract_meta(
            interaction.channel
        )

        if meta["claimed_by"]!=interaction.user.id:
            return await interaction.response.send_message(
                "Seul le claimer peut faire ça",
                ephemeral=True
            )

        await interaction.channel.edit(
            topic=build_topic(
                meta["owner_id"],
                meta["ticket_type"]
            )
        )

        await interaction.response.send_message(
            "Ticket unclaim."
        )

    @discord.ui.button(
        label="Ajouter membre",
        style=discord.ButtonStyle.secondary
    )
    async def add_member(self,interaction,button):

        await interaction.response.send_modal(
            AddMemberModal()
        )

    @discord.ui.button(
        label="Retirer membre",
        style=discord.ButtonStyle.secondary
    )
    async def remove_member(self,interaction,button):

        await interaction.response.send_modal(
            RemoveMemberModal()
        )

    @discord.ui.button(
        label="Renommer",
        style=discord.ButtonStyle.secondary
    )
    async def rename(self,interaction,button):

        await interaction.response.send_modal(
            RenameModal()
        )

    @discord.ui.button(
        label="Fermer",
        style=discord.ButtonStyle.danger
    )
    async def close(self,interaction,button):

        guild=interaction.guild
        channel=interaction.channel

        meta=extract_meta(channel)

        owner=meta["owner_id"]

        if (
            interaction.user.id!=owner and
            not is_staff(
                interaction.user,
                meta["ticket_type"]
            )
        ):
            return await interaction.response.send_message(
                "Pas autorisé",
                ephemeral=True
            )

        await interaction.response.send_message(
            "Fermeture..."
        )

        t_path=await transcript(channel)

        file=discord.File(
            t_path
        )

        embed=discord.Embed(
            title="Ticket fermé",
            description=f"{channel.name} fermé"
        )

        await send_log(
            guild,
            embed,
            file
        )

        tickets=load_tickets()

        if str(owner) in tickets:
            del tickets[str(owner)]
            save_tickets(
                tickets
            )

        await asyncio.sleep(2)

        await channel.delete()

@bot.event
async def on_ready():

    await bot.tree.sync(
        guild=discord.Object(
            id=GUILD_ID
        )
    )

    bot.add_view(
        TicketPanel()
    )

    bot.add_view(
        TicketView()
    )

    print(
        f"Connecté {bot.user}"
    )

@bot.tree.command(
    name="panel",
    description="Envoyer le panel",
    guild=discord.Object(
        id=GUILD_ID
    )
)
async def panel(interaction):

    embed=discord.Embed(
        title="🎫 Centre de tickets",
        description="Choisis une catégorie."
    )

    await interaction.response.send_message(
        embed=embed,
        view=TicketPanel()
    )

@bot.tree.command(
    name="ticket-info",
    description="Infos ticket",
    guild=discord.Object(
        id=GUILD_ID
    )
)
async def ticket_info(interaction):

    meta=extract_meta(
        interaction.channel
    )

    embed=discord.Embed(
        title="Infos ticket"
    )

    embed.add_field(
        name="Owner",
        value=str(
            meta["owner_id"]
        )
    )

    embed.add_field(
        name="Claim",
        value=str(
            meta["claimed_by"]
        )
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )

bot.run(TOKEN)

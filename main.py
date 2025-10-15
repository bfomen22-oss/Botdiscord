import os
import discord
from discord.ext import commands
from discord import app_commands
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
import random
from myserver import server_on

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=discord.Intents.all())

ALLOWED_ROLL_CHANNEL_ID = 1427269313798209597

# อัตราพื้นฐาน
BASE_RATE = {"B": 0.90, "A": 0.094, "S": 0.006}

# อัตรารวมเมื่อมีการันตี (เพิ่มนิดหน่อย)
BOOST_RATE = {"B": 0.84, "A": 0.144, "S": 0.016}

players = {}
REACTION_ROLES = {}  # message_id -> { emoji: role_id }
ADMIN_ROLE_ID = 1427595455239290940  # <-- ใส่ Role ID ของ Admin
ALLOWED_ROLE_CHANNEL_ID = 1427557443734470686


def get_emoji_key(payload):
    return payload.emoji.name if payload.emoji.id is None else str(
        payload.emoji.id)


async def fetch_member(guild, user_id):
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except Exception:
            return None
    return member




@bot.event
async def on_ready():
    print("bot on")
    await bot.tree.sync()


#-------------------------------------------------------------------------------------------------


def is_in_allowed_channel(ctx):
    return ctx.channel.id == ALLOWED_ROLL_CHANNEL_ID


def get_player_data(user_id):
    """ดึงข้อมูลผู้เล่น (สร้างใหม่ถ้าไม่มี)"""
    if user_id not in players:
        players[user_id] = {
            "count": 0,  # จำนวนครั้งที่สุ่มตั้งแต่ได้ S ล่าสุด
            "next_S_plus": False  # ถ้าได้ S- รอบหน้าจะการันตี S+
        }
    return players[user_id]


def get_s_rate(count):
    """คำนวณโอกาสออก S ตามจำนวนครั้ง (6.5% / 93.5%)"""
    if count < 70:
        return 0.001 + (count * 0.00009)  # ~6.5% ระหว่าง 10–69
    elif count < 90:
        return 0.065 + ((count - 70) * 0.0046)  # ~93.5% ระหว่าง 70–90
    else:
        return 1  # การันตี S ที่ 90


def roll_one(player_id):
    """สุ่ม 1 ครั้ง พร้อมคำนวณโอกาส"""
    data = get_player_data(player_id)
    count = data["count"]

    # คำนวณอัตราการได้ S ตามจำนวนครั้ง
    s_rate = get_s_rate(count)
    a_rate = BASE_RATE["A"]
    b_rate = 1 - (s_rate + a_rate)

    roll = random.random()
    result = "B"
    s_type = None

    # ตัดสินผล
    if roll < s_rate:
        result = "S"
    elif roll < s_rate + a_rate:
        result = "A"

    # ระบบการันตี S+ หลัง S-
    if result == "S":
        if data["next_S_plus"]:
            s_type = "S+"
            data["next_S_plus"] = False
        else:
            # สุ่ม 50/50 ระหว่าง S- และ S+
            s_type = "S+" if random.random() < 0.5 else "S-"
            if s_type == "S-":
                data["next_S_plus"] = True

        # รีเซ็ต count เมื่อได้ S
        data["count"] = 0

    else:
        data["count"] += 1

    # การันตี S เมื่อครบ 90 ครั้ง (สุ่ม S- หรือ S+ 50/50)
    if data["count"] >= 90:
        result = "S"
        s_type = "S+" if random.random() < 0.5 else "S-"
        if s_type == "S-":
            data["next_S_plus"] = True
        else:
            data["next_S_plus"] = False
        data["count"] = 0

    return result, s_type, data["count"]


@bot.command()
async def roll(ctx):
    """สุ่ม 1 ครั้ง"""
    if not is_in_allowed_channel(ctx):
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะห้องที่กำหนดเท่านั้น!")

    result, s_type, pity = roll_one(ctx.author.id)

    if result == "S":
        await ctx.send(f"🎉 ได้ **{s_type}** !!! (พอยิตี้: {pity}/90)")
    elif result == "A":
        await ctx.send(f"✨ ได้ A (พอยิตี้: {pity}/90)")
    else:
        await ctx.send(f"🔵 ได้ B (พอยิตี้: {pity}/90)")


@bot.command()
async def roll10(ctx):
    """สุ่ม 10 ครั้ง + การันตี A"""
    if not is_in_allowed_channel(ctx):
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะห้องที่กำหนดเท่านั้น!")

    data = get_player_data(ctx.author.id)
    results = []

    for _ in range(10):
        result, s_type, pity = roll_one(ctx.author.id)
        results.append((result, s_type))

    # ถ้าไม่มี S และไม่มี A ให้การันตี A
    if not any(r[0] in ["A", "S"] for r in results):
        results[-1] = ("A", None)

    msg = "🎲 **ผลการสุ่ม 10 ครั้ง:**\n"
    for i, (r, s) in enumerate(results, 1):
        if r == "S":
            msg += f"{i}. 🎉 **{s}**\n"
        elif r == "A":
            msg += f"{i}. ✨ A\n"
        else:
            msg += f"{i}. 🔵 B\n"

    msg += f"\n📊 พอยิตี้ปัจจุบัน: {data['count']}/90"
    await ctx.send(msg)


#-------------------------------------------------------------------------------------------------


@bot.tree.command(name="role", description="รับยศโว้ยย")
async def role_command(interaction: discord.Interaction):

    if interaction.channel.id != ALLOWED_ROLE_CHANNEL_ID:
        return  # ไม่เกิดผลเลยถ้าไม่ใช่ห้องที่กำหนด
    embed = discord.Embed(title="รับยศได้เลย",
                          description="ฮิฮิ ไปล้าา~~~~\n",
                          color=0x66FFFF,
                          timestamp=discord.utils.utcnow())

    embed.add_field(name="🟡 ZZZ", value="", inline=True)
    embed.add_field(name="🟠 Roblox", value="", inline=True)
    embed.add_field(name="🔴 Drawart", value="", inline=True)
    embed.add_field(name="🔵 HSR", value="", inline=True)

    embed.set_author(
        name="Yuzuha",
        icon_url=
        "https://i.pinimg.com/736x/6a/20/96/6a20963070a311e33d9e2e0146bb04b7.jpg"
    )
    embed.set_thumbnail(
        url=
        "https://i.pinimg.com/736x/70/76/f0/7076f0e820814748d04b9363d6453475.jpg"
    )
    embed.set_image(url="https://c.tenor.com/kStimMhVci4AAAAd/tenor.gif")
    embed.set_footer(
        text="เลือกเลยไม่แกล้งหลอก",
        icon_url=
        'https://i.pinimg.com/736x/6a/20/96/6a20963070a311e33d9e2e0146bb04b7.jpg'
    )

    # ส่ง embed
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()

    # เพิ่ม reaction ให้ embed
    emojis = ["🟡", "🟠", "🔴", "🔵"]
    for e in emojis:
        await msg.add_reaction(e)

    # บันทึก message_id + emoji -> role mapping
    global REACTION_ROLES
    REACTION_ROLES[msg.id] = {
        "🟡": 1335980600384946258,  # ZZZ
        "🟠": 1335980273099341856,  # Roblox
        "🔴": 1335979888808562738,  # Drawart
        "🔵": 1335980409451974739  # Admin (ตัวอย่าง)
    }


# --- เพิ่ม role เมื่อกด reaction ---
@bot.event
async def on_raw_reaction_add(payload):
    if payload.guild_id is None or payload.user_id == bot.user.id:
        return
    if payload.message_id not in REACTION_ROLES:
        return

    emoji = get_emoji_key(payload)
    role_id = REACTION_ROLES[payload.message_id].get(emoji)
    if not role_id:
        return

    guild = bot.get_guild(payload.guild_id)
    member = await fetch_member(guild, payload.user_id)
    role = guild.get_role(role_id)

    if member and role:
        try:
            await member.add_roles(role, reason="Reaction role added")
            # --- ส่งข้อความเฉพาะ Admin ---
            if role.id == ADMIN_ROLE_ID:
                channel = guild.get_channel(ALLOWED_ROLE_CHANNEL_ID)
                if channel:
                    await channel.send(
                        f"👑 {member.mention} ได้รับยศ **Admin** แล้ว!")
        except:
            pass


# --- ลบ role เมื่อเอา reaction ออก ---
@bot.event
async def on_raw_reaction_remove(payload):
    if payload.guild_id is None or payload.user_id == bot.user.id:
        return
    if payload.message_id not in REACTION_ROLES:
        return

    emoji = get_emoji_key(payload)
    role_id = REACTION_ROLES[payload.message_id].get(emoji)
    if not role_id:
        return

    guild = bot.get_guild(payload.guild_id)
    member = await fetch_member(guild, payload.user_id)
    role = guild.get_role(role_id)

    if member and role:
        try:
            await member.remove_roles(role, reason="Reaction role removed")
            # --- ส่งข้อความเฉพาะ Admin ---
            if role.id == ADMIN_ROLE_ID:
                channel = guild.get_channel(ALLOWED_ROLE_CHANNEL_ID)
                if channel:
                    await channel.send(
                        f"🗑️ {member.mention} ถูกลบยศ **Admin** แล้ว!")
        except:
            pass


#-------------------------------------------------------------------------------------------------
@bot.event
async def on_member_join(member):
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    response = requests.get(avatar_url)
    avatar = Image.open(BytesIO(response.content)).convert("RGBA")
    avatar = avatar.resize((250, 250))

    # --- สร้างพื้นหลัง ---
    bg = Image.new("RGBA", (800, 400), (0, 0, 48, 255))

    # --- สร้างหน้ากากวงกลมสำหรับครอบภาพ ---
    mask = Image.new("L", (250, 250), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, 250, 250), fill=255)
    bg.paste(avatar, (275, 30), mask)

    draw_circle = ImageDraw.Draw(bg)
    center_x, center_y = 400, 155  # จุดศูนย์กลางรูป (275+125, 30+125)
    radius = 125
    draw_circle.ellipse((center_x - radius - 5, center_y - radius - 5,
                         center_x + radius + 5, center_y + radius + 5),
                        outline="white",
                        width=8)

    draw = ImageDraw.Draw(bg)
    try:
        # ใช้ฟอนต์ Montserrat-Bold ถ้ามี
        font_title = ImageFont.truetype("Montserrat-Bold.ttf", 55)
        font_name = ImageFont.truetype("Montserrat-Bold.ttf", 30)
    except:
        # ถ้าไม่มีใช้ Arial แทน
        font_title = ImageFont.truetype("arialbd.ttf", 55)
        font_name = ImageFont.truetype("arialbd.ttf", 30)

    # จัดข้อความให้อยู่กึ่งกลางภาพ
    text_welcome = "WELCOME"
    text_name = member.name.upper()
    bbox1 = draw.textbbox((0, 0), text_welcome, font=font_title)
    bbox2 = draw.textbbox((0, 0), text_name, font=font_name)
    w1 = bbox1[2] - bbox1[0]
    w2 = bbox2[2] - bbox2[0]

    draw = ImageDraw.Draw(bg)
    try:
        font_title = ImageFont.truetype("Montserrat-Bold.ttf", 55)
        font_name = ImageFont.truetype("Montserrat-Bold.ttf", 30)
    except:
        font_title = ImageFont.truetype("arialbd.ttf", 55)
        font_name = ImageFont.truetype("arialbd.ttf", 30)
    # --- เพิ่มข้อความ ---
    bbox1 = draw.textbbox((0, 0), "WELCOME", font=font_title)
    bbox2 = draw.textbbox((0, 0), member.name.upper(), font=font_name)
    w1 = bbox1[2] - bbox1[0]
    w2 = bbox2[2] - bbox2[0]

    # เขียนข้อความให้อยู่ตรงกลาง
    draw.text(((805 - w1) / 2, 290), "WELCOME", font=font_title, fill="white")
    draw.text(((805 - w2) / 2, 350),
              member.name.upper(),
              font=font_name,
              fill="white")

    # --- ส่งภาพกลับใน Discord ---
    with BytesIO() as image_binary:
        bg.save(image_binary, 'PNG')
        image_binary.seek(0)
        channel = member.guild.get_channel(
            1427188881303797780)  # แทน ID ห้องจริง
        if channel:
            await channel.send(
                content=
                f"ยินดีต้อนรับ {member.mention} สู่ : ART DRAW ที่ไม่ DRAW",
                file=discord.File(fp=image_binary, filename="welcome.png"))


#-------------------------------------------------------------------------------------------------


@bot.event
async def on_member_remove(member):
    channel = bot.get_channel(1427188881303797780)
    embed = discord.Embed(title='GOODBYE',
                          description='ไปซะแล้วสิ',
                          color=discord.Color.red())
    embed.set_image(url='https://c.tenor.com/QVjkDHg8lQwAAAAd/tenor.gif')
    embed.set_thumbnail(
        url=
        'https://i.pinimg.com/736x/57/b5/a9/57b5a9964c49038f018b631a90cf5d57.jpg'
    )
    embed.set_author(name=member.name,
                     icon_url=member.avatar.url
                     if member.avatar else member.default_avatar.url)

    embed.add_field(name=member.name, value='See you again', inline=True)

    await channel.send(embed=embed)


#-------------------------------------------------------------------------------------------------
server_on()

bot.run(os.getenv('TK'))

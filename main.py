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


TK = 'MTQyNzEzMDY2OTU3MzYwNzUzNg.Gyq74f.E-tZbAgvHDFZs1Zoo0wrCCf7_mWX0GQkDk9i1g'


@bot.event
async def on_ready():
    print("bot on")
    await bot.tree.sync()


#-------------------------------------------------------------------------------------------------


import random

# ค่าคงที่การตั้งค่า
ALLOWED_ROLL_CHANNEL_ID = 1427269313798209597  # แก้ไขเป็น ID ช่องจริง
BASE_RATE = {
    "S": 0.007,  # 0.7% สำหรับ S-Rank
    "A": 0.072,  # 7.2% สำหรับ A-Rank
    "B": 0.921   # 92.1% สำหรับ B-Rank
}
MAX_PITY_S = 90  # การันตี S ที่ 90 ครั้ง
MAX_PITY_A = 10  # การันตี A ที่ 10 ครั้ง

# เก็บข้อมูลผู้เล่น
players = {}
featured_banners = {}  # เก็บแบนเนอร์ปัจจุบันของผู้เล่น

class Banner:
    def __init__(self, name, featured_S=None, featured_A=None, banner_type="character"):
        self.name = name
        self.featured_S = featured_S  # ตัวละคร S-Rank หน้าตู้
        self.featured_A = featured_A  # ตัวละคร A-Rank หน้าตู้
        self.banner_type = banner_type  # "character", "weapon", หรือ "bangboo"

# สร้างแบนเนอร์ตัวอย่าง
BANNERS = {
    "character": Banner("Character Event", "Ellen Joe", "Ben", "character"),
    "weapon": Banner("Weapon Event", "Signature W-Engine", None, "weapon"),
    "bangboo": Banner("Bangboo Event", "Bangboo S-Rank", "Bangboo A-Rank", "bangboo")
}

def is_in_allowed_channel(ctx):
    return ctx.channel.id == ALLOWED_ROLL_CHANNEL_ID

def get_player_data(user_id):
    """ดึงข้อมูลผู้เล่น (สร้างใหม่ถ้าไม่มี)"""
    if user_id not in players:
        players[user_id] = {
            "pity_S": 0,  # จำนวนครั้งที่สุ่มตั้งแต่ได้ S ล่าสุด
            "pity_A": 0,  # จำนวนครั้งที่สุ่มตั้งแต่ได้ A ล่าสุด
            "guaranteed_featured": False,  # ถ้าได้ S- รอบหน้าจะการันตี S+ (Featured)
            "current_banner": "character"  # แบนเนอร์ที่ใช้อยู่
        }
    return players[user_id]

def get_player_banner_data(user_id, banner_type=None):
    """ดึงข้อมูลแบนเนอร์ของผู้เล่น"""
    data = get_player_data(user_id)
    if banner_type:
        data["current_banner"] = banner_type
    
    if user_id not in featured_banners:
        featured_banners[user_id] = {}
    
    banner_type_key = data["current_banner"]
    if banner_type_key not in featured_banners[user_id]:
        featured_banners[user_id][banner_type_key] = {
            "pity_S": 0,
            "guaranteed_featured": False
        }
    
    return featured_banners[user_id][banner_type_key]

def get_s_rate(pity_count):
    """คำนวณโอกาสเพิ่มสำหรับ S-Rank ตาม pity"""
    if pity_count < 73:
        return BASE_RATE["S"]
    elif pity_count < 90:
        # โอกาสเพิ่มขึ้นเรื่อยๆ หลัง 73 ครั้ง
        return BASE_RATE["S"] + ((pity_count - 72) * 0.07)  # เพิ่ม ~7% ต่อครั้ง
    else:
        return 1  # การันตี S ที่ 90

def roll_one(player_id, banner_type="character"):
    """สุ่ม 1 ครั้งตามระบบ ZZZ"""
    data = get_player_data(player_id)
    banner_data = get_player_banner_data(player_id, banner_type)
    
    pity_S = banner_data["pity_S"]
    pity_A = data["pity_A"]
    guaranteed_featured = banner_data["guaranteed_featured"]
    
    current_banner = BANNERS[data["current_banner"]]
    
    # คำนวณอัตราการได้ S ตาม pity
    effective_s_rate = get_s_rate(pity_S)
    
    # โอกาสจริง (ต้องไม่เกิน 100%)
    actual_s_rate = min(effective_s_rate, 1.0)
    actual_a_rate = BASE_RATE["A"]
    actual_b_rate = 1 - (actual_s_rate + actual_a_rate)
    
    roll = random.random()
    result = "B"
    rank_type = None
    is_featured = False
    item_name = None
    
    # ตรวจสอบการันตี A-Rank
    if pity_A >= 9:  # ตั้งแต่ 9 ครั้งที่ไม่ได้ A
        result = "A"
        actual_s_rate = 0  # ปิดโอกาสได้ S เมื่อการันตี A
    # ตรวจสอบการันตี S-Rank
    elif pity_S >= 89:  # ตั้งแต่ 89 ครั้งที่ไม่ได้ S
        result = "S"
    # สุ่มตามอัตราปกติ
    else:
        if roll < actual_s_rate:
            result = "S"
        elif roll < actual_s_rate + actual_a_rate:
            result = "A"
        else:
            result = "B"
    
    # ตัดสินผลลัพธ์
    if result == "S":
        # ระบบ 50/50 สำหรับ Featured
        if guaranteed_featured or random.random() < 0.5:
            is_featured = True
            item_name = current_banner.featured_S
            banner_data["guaranteed_featured"] = False  # รีเซ็ตหลังได้ Featured
        else:
            is_featured = False
            item_name = "Standard S-Rank"  # ตัวละคร/อาวุธมาตรฐาน
            banner_data["guaranteed_featured"] = True  # การันตี Featured รอบหน้า
        
        rank_type = "S+" if is_featured else "S-"
        
        # รีเซ็ต pity สำหรับ S
        banner_data["pity_S"] = 0
        # รีเซ็ต pity สำหรับ A (เมื่อได้ S ก็ถือว่าได้ rare item)
        data["pity_A"] = 0
        
    elif result == "A":
        # โอกาสได้ Featured A-Rank
        if current_banner.featured_A and random.random() < 0.5:
            item_name = current_banner.featured_A
        else:
            item_name = "Standard A-Rank"
        
        rank_type = "A"
        
        # รีเซ็ต pity สำหรับ A
        data["pity_A"] = 0
        # เพิ่ม pity สำหรับ S
        banner_data["pity_S"] += 1
        
    else:  # B-Rank
        rank_type = "B"
        item_name = "B-Rank Item"
        
        # เพิ่ม pity ทั้งคู่
        banner_data["pity_S"] += 1
        data["pity_A"] += 1
    
    return result, rank_type, item_name, is_featured, banner_data["pity_S"], data["pity_A"], banner_data["guaranteed_featured"]

@bot.command()
async def banner(ctx, banner_type="character"):
    """เลือกแบนเนอร์ที่ต้องการสุ่ม"""
    if not is_in_allowed_channel(ctx):
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะห้องที่กำหนดเท่านั้น!")
    
    if banner_type not in BANNERS:
        available = ", ".join(BANNERS.keys())
        return await ctx.send(f"❌ แบนเนอร์ไม่ถูกต้อง! แบนเนอร์ที่มี: {available}")
    
    data = get_player_data(ctx.author.id)
    data["current_banner"] = banner_type
    
    banner_info = BANNERS[banner_type]
    banner_data = get_player_banner_data(ctx.author.id, banner_type)
    
    pity_S = banner_data["pity_S"]
    guaranteed = banner_data["guaranteed_featured"]
    
    message = f"🎪 **เปลี่ยนแบนเนอร์เป็น: {banner_info.name}**\n"
    message += f"📌 **Featured S-Rank:** {banner_info.featured_S}\n"
    if banner_info.featured_A:
        message += f"📌 **Featured A-Rank:** {banner_info.featured_A}\n"
    
    message += f"\n📊 สถานะปัจจุบัน:\n"
    message += f"• พอยิตี้ S-Rank: {pity_S}/{MAX_PITY_S}\n"
    message += f"• การันตี Featured: {'✅' if guaranteed else '❌'}\n"
    
    await ctx.send(message)

@bot.command()
async def roll(ctx):
    """สุ่ม 1 ครั้ง"""
    if not is_in_allowed_channel(ctx):
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะห้องที่กำหนดเท่านั้น!")
    
    data = get_player_data(ctx.author.id)
    result, rank_type, item_name, is_featured, pity_S, pity_A, guaranteed = roll_one(ctx.author.id, data["current_banner"])
    
    banner_info = BANNERS[data["current_banner"]]
    
    if result == "S":
        emoji = "🎉" if is_featured else "⭐"
        featured_text = " **(Featured!)**" if is_featured else " **(Standard)**"
        await ctx.send(f"{emoji} **{rank_type}** ได้ **{item_name}**{featured_text}\n"
                      f"📊 พอยิตี้ S: {pity_S}/{MAX_PITY_S} | A: {pity_A}/{MAX_PITY_A}\n"
                      f"🔮 การันตีรอบหน้า: {'Featured' if guaranteed else '50/50'}")
    elif result == "A":
        await ctx.send(f"✨ **{rank_type}** ได้ **{item_name}**\n"
                      f"📊 พอยิตี้ S: {pity_S}/{MAX_PITY_S} | A: {pity_A}/{MAX_PITY_A}")
    else:
        await ctx.send(f"🔵 **{rank_type}** ได้ **{item_name}**\n"
                      f"📊 พอยิตี้ S: {pity_S}/{MAX_PITY_S} | A: {pity_A}/{MAX_PITY_A}")

@bot.command()
async def roll10(ctx):
    """สุ่ม 10 ครั้ง"""
    if not is_in_allowed_channel(ctx):
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะห้องที่กำหนดเท่านั้น!")
    
    data = get_player_data(ctx.author.id)
    banner_info = BANNERS[data["current_banner"]]
    banner_data = get_player_banner_data(ctx.author.id)
    
    results = []
    s_count = 0
    a_count = 0
    
    # สุ่ม 9 ครั้งแรก
    for _ in range(9):
        result, rank_type, item_name, is_featured, pity_S, pity_A, guaranteed = roll_one(ctx.author.id, data["current_banner"])
        results.append((result, rank_type, item_name, is_featured))
        if result == "S":
            s_count += 1
        elif result == "A":
            a_count += 1
    
    # ครั้งที่ 10: การันตี A-Rank ถ้ายังไม่มี
    if a_count == 0:
        # บังคับให้ได้ A-Rank
        if random.random() < 0.5 and banner_info.featured_A:
            item_name = banner_info.featured_A
        else:
            item_name = "Standard A-Rank"
        results.append(("A", "A", item_name, False))
        a_count += 1
    else:
        # สุ่มปกติ
        result, rank_type, item_name, is_featured, pity_S, pity_A, guaranteed = roll_one(ctx.author.id, data["current_banner"])
        results.append((result, rank_type, item_name, is_featured))
        if result == "S":
            s_count += 1
        elif result == "A":
            a_count += 1
    
    # แสดงผล
    msg = f"🎪 **{banner_info.name} - 10x Roll**\n\n"
    
    for i, (result, rank_type, item_name, is_featured) in enumerate(results, 1):
        if result == "S":
            featured_icon = "✨" if is_featured else ""
            msg += f"{i}. 🎉 **{rank_type}** {featured_icon} {item_name}\n"
        elif result == "A":
            msg += f"{i}. ✨ **{rank_type}** {item_name}\n"
        else:
            msg += f"{i}. 🔵 **{rank_type}** {item_name}\n"
    
    # ดึงข้อมูลล่าสุด
    banner_data = get_player_banner_data(ctx.author.id)
    data = get_player_data(ctx.author.id)
    
    msg += f"\n📊 **สรุปผล:** S-Rank: {s_count} | A-Rank: {a_count} | B-Rank: {10 - s_count - a_count}\n"
    msg += f"📈 **พอยิตี้ปัจจุบัน:** S: {banner_data['pity_S']}/{MAX_PITY_S} | A: {data['pity_A']}/{MAX_PITY_A}\n"
    msg += f"🔮 **สถานะการันตี:** {'Featured' if banner_data['guaranteed_featured'] else '50/50'}"
    
    await ctx.send(msg)

@bot.command()
async def pity(ctx):
    """ตรวจสอบสถานะพอยิตี้"""
    if not is_in_allowed_channel(ctx):
        return await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะห้องที่กำหนดเท่านั้น!")
    
    data = get_player_data(ctx.author.id)
    banner_data = get_player_banner_data(ctx.author.id)
    banner_info = BANNERS[data["current_banner"]]
    
    pity_S = banner_data["pity_S"]
    pity_A = data["pity_A"]
    guaranteed = banner_data["guaranteed_featured"]
    
    # คำนวณโอกาส S ถัดไป
    next_s_rate = get_s_rate(pity_S) * 100
    
    message = f"🎪 **{banner_info.name} - สถานะพอยิตี้**\n\n"
    message += f"📊 **พอยิตี้ S-Rank:** {pity_S}/{MAX_PITY_S}\n"
    message += f"📊 **พอยิตี้ A-Rank:** {pity_A}/{MAX_PITY_A}\n\n"
    message += f"📈 **โอกาสได้ S-Rank ครั้งต่อไป:** {next_s_rate:.2f}%\n"
    message += f"🔮 **สถานะการันตี:** {'✅ Featured' if guaranteed else '❌ 50/50'}\n\n"
    
    # แสดงแบนเนอร์อื่นๆ ด้วย
    message += "🎪 **แบนเนอร์อื่นๆ:**\n"
    for banner_name, banner in BANNERS.items():
        if banner_name != data["current_banner"]:
            if ctx.author.id in featured_banners and banner_name in featured_banners[ctx.author.id]:
                other_pity = featured_banners[ctx.author.id][banner_name]["pity_S"]
                message += f"• {banner.name}: พอยิตี้ S-Rank = {other_pity}/{MAX_PITY_S}\n"
    
    await ctx.send(message)

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
    # กำหนดช่องที่จะส่งข้อความต้อนรับ
    welcome_channel = member.guild.get_channel(1427188881303797780)
    if not welcome_channel:
        return
    
    # ดาวน์โหลดอวตาร์
    avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
    response = requests.get(avatar_url)
    avatar = Image.open(BytesIO(response.content)).convert("RGBA")
    
    # ปรับขนาดและทำให้เป็นวงกลม
    avatar = avatar.resize((300, 300))
    mask = Image.new('L', (300, 300), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, 300, 300), fill=255)
    avatar.putalpha(mask)
    
    # สร้างพื้นหลังแบบ gradient
    bg = Image.new('RGBA', (1200, 500), (0, 0, 0, 255))
    draw = ImageDraw.Draw(bg)
    
    # วาด gradient พื้นหลัง
    for i in range(500):
        alpha = int(255 * (i / 500))
        color = (20, 30, 70, alpha)
        draw.line([(0, i), (1200, i)], fill=color)
    
    # วาดวงกลมล้อมรอบ
    draw.ellipse(
        [(450, 100), (750, 400)],
        outline=(100, 200, 255, 255),
        width=6
    )
    
    # วาดเอฟเฟกต์แสง
    for i in range(5):
        radius = 155 + (i * 5)
        color = (100, 200, 255, 50 - (i * 10))
        draw.ellipse(
            [(600 - radius, 250 - radius), (600 + radius, 250 + radius)],
            outline=color,
            width=2
        )
    
    # วางอวตาร์
    bg.paste(avatar, (450, 100), avatar)
    
    # เพิ่มเอฟเฟกต์เงาให้ข้อความ
    try:
        # ใช้ฟอนต์สไตล์โมเดิร์น
        font_big = ImageFont.truetype("fonts/Montserrat-Bold.ttf", 70)
        font_medium = ImageFont.truetype("fonts/Montserrat-SemiBold.ttf", 40)
        font_small = ImageFont.truetype("fonts/Montserrat-Regular.ttf", 30)
    except:
        # ถ้าไม่มีฟอนต์ที่กำหนด
        try:
            font_big = ImageFont.truetype("arialbd.ttf", 70)
            font_medium = ImageFont.truetype("arialbd.ttf", 40)
            font_small = ImageFont.truetype("arial.ttf", 30)
        except:
            # ใช้ฟอนต์พื้นฐานของ PIL
            font_big = ImageFont.load_default().font_variant(size=70)
            font_medium = ImageFont.load_default().font_variant(size=40)
            font_small = ImageFont.load_default().font_variant(size=30)
    
    # วาดข้อความต้อนรับ
    texts = [
        ("WELCOME", font_big, (100, 200, 255)),
        (member.name.upper(), font_medium, (255, 255, 255)),
        (f"Member #{member.guild.member_count}", font_small, (200, 200, 200))
    ]
    
    y_pos = 350
    for text, font, color in texts:
        # เงาของข้อความ
        shadow_color = (0, 0, 0, 180)
        for offset_x, offset_y in [(3, 3), (2, 2), (1, 1)]:
            text_width = draw.textlength(text, font=font)
            x_pos = (1200 - text_width) // 2
            draw.text(
                (x_pos + offset_x, y_pos + offset_y),
                text,
                font=font,
                fill=shadow_color
            )
        
        # ข้อความหลัก
        text_width = draw.textlength(text, font=font)
        x_pos = (1200 - text_width) // 2
        draw.text(
            (x_pos, y_pos),
            text,
            font=font,
            fill=color
        )
        y_pos += 70 if font == font_big else 50
    
    # เพิ่มโลโก้หรือดีเทลเล็กๆ
    try:
        # ลองโหลดโลโก้ถ้ามี
        logo = Image.open("assets/logo.png").convert("RGBA")
        logo = logo.resize((100, 100))
        bg.paste(logo, (50, 50), logo)
    except:
        pass
    
    # บันทึกลงไฟล์ชั่วคราว
    with BytesIO() as image_binary:
        bg.save(image_binary, 'PNG')
        image_binary.seek(0)
        
        # สร้าง embed สำหรับข้อความเพิ่มเติม
        embed = discord.Embed(
            title=f"🎉 ยินดีต้อนรับสู่ {member.guild.name}!",
            description=f"""
            สวัสดี {member.mention}! ยินดีต้อนรับสู่ชุมชนของเรา

            📋 **แนะนำตัวเอง:** <#1427188881303797780>
            📜 **อ่านกฎ:** <#1427188881303797781>
            🎮 **ช่องพูดคุย:** <#1427188881303797782>
            
            ขอให้สนุกกับการอยู่ในเซิร์ฟเวอร์นะ!
            """,
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        
        embed.set_footer(text=f"Member #{member.guild.member_count}")
        embed.set_thumbnail(url=member.guild.icon.url if member.guild.icon else None)
        
        # ส่งทั้งรูปภาพและ embed
        await welcome_channel.send(
            content=f"**✨ {member.mention} ได้เข้าร่วมเซิร์ฟเวอร์แล้ว!**",
            embed=embed,
            file=discord.File(fp=image_binary, filename="welcome.png")
        )



#-------------------------------------------------------------------------------------------------


@bot.event
async def on_member_remove(member):
    goodbye_channel = bot.get_channel(1427188881303797780)
    if not goodbye_channel:
        return
    
    # สร้างภาพ goodbye
    bg = Image.new('RGBA', (1000, 400), (30, 10, 40, 255))
    draw = ImageDraw.Draw(bg)
    
    # วาด gradient พื้นหลัง
    for i in range(400):
        alpha = int(200 * (i / 400))
        color = (70, 20, 50, alpha)
        draw.line([(0, i), (1000, i)], fill=color)
    
    # ดาวน์โหลดอวตาร์
    try:
        avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
        response = requests.get(avatar_url)
        avatar = Image.open(BytesIO(response.content)).convert("RGBA")
        avatar = avatar.resize((200, 200))
        
        # ทำให้เป็นวงกลม
        mask = Image.new('L', (200, 200), 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0, 200, 200), fill=255)
        avatar.putalpha(mask)
        
        # วางอวตาร์
        bg.paste(avatar, (100, 100), avatar)
        
        # วาดกรอบ
        draw.ellipse(
            [(95, 95), (305, 305)],
            outline=(200, 100, 150, 255),
            width=4
        )
    except:
        pass
    
    # เพิ่มข้อความ
    try:
        font_big = ImageFont.truetype("fonts/Montserrat-Bold.ttf", 60)
        font_medium = ImageFont.truetype("fonts/Montserrat-SemiBold.ttf", 30)
    except:
        try:
            font_big = ImageFont.truetype("arialbd.ttf", 60)
            font_medium = ImageFont.truetype("arialbd.ttf", 30)
        except:
            font_big = ImageFont.load_default().font_variant(size=60)
            font_medium = ImageFont.load_default().font_variant(size=30)
    
    # ข้อความ GOODBYE
    goodbye_text = "GOODBYE"
    text_width = draw.textlength(goodbye_text, font=font_big)
    x_pos = 700 - (text_width // 2)
    
    # เงา
    for offset in range(1, 4):
        draw.text(
            (x_pos + offset, 150 + offset),
            goodbye_text,
            font=font_big,
            fill=(0, 0, 0, 150)
        )
    
    # ข้อความหลัก
    draw.text(
        (x_pos, 150),
        goodbye_text,
        font=font_big,
        fill=(255, 150, 150, 255)
    )
    
    # ชื่อสมาชิก
    name_text = member.name.upper()
    text_width = draw.textlength(name_text, font=font_medium)
    x_pos = 700 - (text_width // 2)
    draw.text(
        (x_pos, 230),
        name_text,
        font=font_medium,
        fill=(255, 255, 255, 255)
    )
    
    # ข้อความลาจาก
    farewell_text = "We'll miss you..."
    text_width = draw.textlength(farewell_text, font=font_medium)
    x_pos = 700 - (text_width // 2)
    draw.text(
        (x_pos, 280),
        farewell_text,
        font=font_medium,
        fill=(200, 200, 200, 255)
    )
    
    # วาดเส้นคั่น
    draw.line([(350, 120), (650, 120)], fill=(200, 100, 150, 255), width=3)
    draw.line([(350, 330), (650, 330)], fill=(200, 100, 150, 255), width=3)
    
    # บันทึกลงไฟล์
    with BytesIO() as image_binary:
        bg.save(image_binary, 'PNG')
        image_binary.seek(0)
        
        # สร้าง embed
        embed = discord.Embed(
            title="👋 ลาก่อนนะ...",
            description=f"""
            **{member.name}** ได้ออกจากเซิร์ฟเวอร์แล้ว
            
            ⏰ **เข้าร่วมเมื่อ:** {discord.utils.format_dt(member.joined_at, style='R')}
            🎭 **สถานะ:** {"เคยเป็นสมาชิก" if member.joined_at else "ผู้มาเยือน"}
            
            ขอให้โชคดีในการเดินทางครั้งต่อไป!
            """,
            color=discord.Color.purple(),
            timestamp=discord.utils.utcnow()
        )
        
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        
        embed.set_footer(text=f"สมาชิกลงเหลือ: {member.guild.member_count} คน")
        
        # ส่งข้อความ
        await goodbye_channel.send(
            embed=embed,
            file=discord.File(fp=image_binary, filename="goodbye.png")
        )


#-------------------------------------------------------------------------------------------------
server_on()

bot.run(TK)



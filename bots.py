import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, date
import json
import os
import pytz

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

bot.remove_command("help")

VN_TIMEZONE = pytz.timezone("Asia/Ho_Chi_Minh")

NOTIFICATION_CHANNEL_ID = 1354521014964453667
REPORT_CHANNEL_ID = 1354521068026593371

ADMIN_ROLE_IDS = ["1346726279696613397", "1346726165976580178"]

DATA_FILE = "playtime.json"
ACTIVITY_FILE = "activity.json"
USER_MAPPING_FILE = "user_mapping.json"

def load_playtime_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_playtime_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_activity_data():
    if os.path.exists(ACTIVITY_FILE):
        with open(ACTIVITY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_activity_data(data):
    with open(ACTIVITY_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_user_mapping():
    if os.path.exists(USER_MAPPING_FILE):
        with open(USER_MAPPING_FILE, "r") as f:
            data = json.load(f)
            filtered_data = {}
            for user_id, user_info in data.items():
                if isinstance(user_info, dict) and "guild_id" in user_info:
                    filtered_data[user_id] = user_info
            if data != filtered_data:
                with open(USER_MAPPING_FILE, "w") as f:
                    json.dump(filtered_data, f, indent=4)
            return filtered_data
    return {}

def save_user_mapping(data):
    with open(USER_MAPPING_FILE, "w") as f:
        json.dump(data, f, indent=4)

def get_week_boundaries(date):
    start_of_week = date - timedelta(days=date.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    return start_of_week, end_of_week

def has_admin_role(member):
    for role in member.roles:
        if str(role.id) in ADMIN_ROLE_IDS:
            return True
    return False

start_times = {}
online_start_times = {}
paused_online_times = {}
playtime_data = load_playtime_data()
activity_data = load_activity_data()
user_mapping = load_user_mapping()

@bot.event
async def on_ready():
    print(f"Bot đã sẵn sàng: {bot.user}")
    check_vinewood_activity.start()
    daily_report.start()
    reset_weekly_data.start()

@tasks.loop(minutes=1)
async def check_vinewood_activity():
    global playtime_data, activity_data
    current_time = datetime.now(VN_TIMEZONE)
    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
    if not channel:
        print(f"Không tìm thấy kênh chat với ID {NOTIFICATION_CHANNEL_ID}")
        return

    users_to_remove = []

    for user_id in list(user_mapping.keys()):
        if user_id not in user_mapping:
            continue

        user_info = user_mapping[user_id]
        guild_id = user_info.get("guild_id")
        if not guild_id:
            users_to_remove.append(user_id)
            continue

        guild = bot.get_guild(int(guild_id))
        if not guild:
            users_to_remove.append(user_id)
            continue

        member = guild.get_member(int(user_id))
        if not member:
            continue

        vinewood_active = False
        for activity in member.activities:
            if isinstance(activity, discord.Game) or isinstance(activity, discord.Activity):
                activity_text = f"{activity.name} {activity.state or ''} {activity.details or ''}"
                if "Vinewood Park Dr" in activity_text:
                    vinewood_active = True
                    break

        if user_id not in activity_data:
            activity_data[user_id] = {}

        if vinewood_active and not activity_data[user_id].get("in_vinewood", False):
            activity_data[user_id]["in_vinewood"] = True
            activity_data[user_id]["vinewood_start_time"] = current_time.isoformat()
            save_activity_data(activity_data)
            await channel.send(
                f"{member.display_name} đã vào khu vực Vinewood Park Dr lúc {current_time.strftime('%H:%M:%S %Y-%m-%d')}."
            )

        elif not vinewood_active and activity_data[user_id].get("in_vinewood", False):
            start_time_str = activity_data[user_id].get("vinewood_start_time")
            if start_time_str:
                start_time = datetime.fromisoformat(start_time_str).astimezone(VN_TIMEZONE)
                time_spent_seconds = (current_time - start_time).total_seconds()
                hours = int(time_spent_seconds // 3600)
                minutes = int((time_spent_seconds % 3600) // 60)
                seconds = int(time_spent_seconds % 60)
                await channel.send(
                    f"{member.display_name} đã rời khỏi khu vực Vinewood Park Dr sau {hours} giờ {minutes} phút {seconds} giây "
                    f"vào lúc {current_time.strftime('%H:%M:%S %Y-%m-%d')}."
                )
            
            activity_data[user_id]["in_vinewood"] = False
            activity_data[user_id]["vinewood_start_time"] = None
            save_activity_data(activity_data)

    for user_id in users_to_remove:
        if user_id in user_mapping:
            del user_mapping[user_id]
    if users_to_remove:
        save_user_mapping(user_mapping)

@tasks.loop(minutes=1)
async def daily_report():
    current_time = datetime.now(VN_TIMEZONE)
    current_date = current_time.date()
    current_hour = current_time.hour
    current_minute = current_time.minute

    if current_hour != 23 or current_minute != 59:
        return

    channel = bot.get_channel(REPORT_CHANNEL_ID)
    if not channel:
        return

    report = f"📊 **Báo cáo on-duty ngày {current_date}**:\n"
    users_reported = 0

    users_to_remove = []

    for user_id, user_info in user_mapping.items():
        if not isinstance(user_info, dict):
            users_to_remove.append(user_id)
            continue

        guild_id = user_info.get("guild_id")
        if not guild_id:
            users_to_remove.append(user_id)
            continue

        guild = bot.get_guild(int(guild_id))
        if not guild:
            users_to_remove.append(user_id)
            continue

        member = guild.get_member(int(user_id))
        if not member:
            continue

        total_online = 0
        if user_id in playtime_data and "daily_online" in playtime_data[user_id]:
            current_date_str = current_date.isoformat()
            total_online = playtime_data[user_id]["daily_online"].get(current_date_str, 0)

        if total_online > 0:
            hours = int(total_online // 60)
            mins = int(total_online % 60)
            report += f"- {member.display_name}: {hours}h {mins}m\n"
            users_reported += 1

    if users_reported == 0:
        report += "Không có ai on-duty trong ngày hôm nay.\n"

    await channel.send(report)

    for user_id in users_to_remove:
        if user_id in user_mapping:
            del user_mapping[user_id]
    if users_to_remove:
        save_user_mapping(user_mapping)

@tasks.loop(hours=24)
async def reset_weekly_data():
    current_time = datetime.now(VN_TIMEZONE)
    current_date = current_time.date()

    if current_date.weekday() != 0:
        return

    two_weeks_ago = (current_time - timedelta(days=14)).date().isoformat()
    for user_id in playtime_data:
        if "weekly_online" in playtime_data[user_id]:
            playtime_data[user_id]["weekly_online"] = {
                week: minutes
                for week, minutes in playtime_data[user_id]["weekly_online"].items()
                if week >= two_weeks_ago
            }

        if "daily_online" in playtime_data[user_id]:
            playtime_data[user_id]["daily_online"] = {
                date: minutes
                for date, minutes in playtime_data[user_id]["daily_online"].items()
                if date >= two_weeks_ago
            }

    save_playtime_data(playtime_data)

@bot.event
async def on_presence_update(before, after):
    global start_times, online_start_times, paused_online_times, playtime_data, activity_data, user_mapping
    user_id = str(after.id)
    current_time = datetime.now(VN_TIMEZONE)
    current_date = current_time.date().isoformat()

    game_active = False
    for activity in after.activities:
        if isinstance(activity, discord.Game) or isinstance(activity, discord.Activity):
            activity_name = str(activity.name).lower()
            activity_text = f"{activity.name} {activity.state or ''} {activity.details or ''}".lower()
            if any(keyword in activity_name for keyword in ["gta5vn.net", "gta5vn", "gta v", "gta 5", "fivem"]) or \
               any(keyword in activity_text for keyword in ["gta5vn.net", "gta5vn", "gta v", "gta 5", "fivem"]):
                game_active = True
                break

    if game_active and user_id not in user_mapping:
        guild_id = str(after.guild.id) if after.guild else None
        if guild_id:
            user_mapping[user_id] = {"guild_id": guild_id}
            save_user_mapping(user_mapping)
            channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel:
                await channel.send(f"Người chơi {after.name} đã được tự động thêm vào danh sách.")

    if user_id not in activity_data:
        activity_data[user_id] = {}

    if game_active:
        if user_id not in start_times:
            start_times[user_id] = current_time

    if not game_active:
        if user_id in start_times:
            start_time = start_times.pop(user_id)
            time_played = (current_time - start_time).total_seconds() / 60

            if user_id not in playtime_data:
                playtime_data[user_id] = {
                    "daily_playtime": {},
                    "daily_online": {},
                    "weekly_online": {},
                    "last_reset": current_time.isoformat()
                }

            last_reset = datetime.fromisoformat(playtime_data[user_id]["last_reset"]).astimezone(VN_TIMEZONE)
            if current_time - last_reset > timedelta(days=14):
                playtime_data[user_id] = {
                    "daily_playtime": {},
                    "daily_online": {},
                    "weekly_online": {},
                    "last_reset": current_time.isoformat()
                }

            if current_date not in playtime_data[user_id]["daily_playtime"]:
                playtime_data[user_id]["daily_playtime"][current_date] = 0
            playtime_data[user_id]["daily_playtime"][current_date] += time_played

            fourteen_days_ago = (current_time - timedelta(days=14)).date().isoformat()
            playtime_data[user_id]["daily_playtime"] = {
                date: minutes
                for date, minutes in playtime_data[user_id]["daily_playtime"].items()
                if date >= fourteen_days_ago
            }

            save_playtime_data(playtime_data)

        if user_id in activity_data:
            if activity_data[user_id].get("in_vinewood", False):
                start_time_str = activity_data[user_id].get("vinewood_start_time")
                if start_time_str:
                    start_time = datetime.fromisoformat(start_time_str).astimezone(VN_TIMEZONE)
                    time_spent_seconds = (current_time - start_time).total_seconds()
                    hours = int(time_spent_seconds // 3600)
                    minutes = int((time_spent_seconds % 3600) // 60)
                    seconds = int(time_spent_seconds % 60)
                    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
                    if channel:
                        await channel.send(
                            f"{after.name} đã rời khỏi khu vực Vinewood Park Dr sau {hours} giờ {minutes} phút {seconds} giây "
                            f"vào lúc {current_time.strftime('%H:%M:%S %Y-%m-%d')} do thoát game."
                        )
            activity_data[user_id]["in_vinewood"] = False
            activity_data[user_id]["vinewood_start_time"] = None
            save_activity_data(activity_data)

        if user_id in paused_online_times:
            del paused_online_times[user_id]

    if after.status == discord.Status.offline:
        if user_id in start_times:
            start_time = start_times.pop(user_id)
            time_played = (current_time - start_time).total_seconds() / 60

            if user_id not in playtime_data:
                playtime_data[user_id] = {
                    "daily_playtime": {},
                    "daily_online": {},
                    "weekly_online": {},
                    "last_reset": current_time.isoformat()
                }

            last_reset = datetime.fromisoformat(playtime_data[user_id]["last_reset"]).astimezone(VN_TIMEZONE)
            if current_time - last_reset > timedelta(days=14):
                playtime_data[user_id] = {
                    "daily_playtime": {},
                    "daily_online": {},
                    "weekly_online": {},
                    "last_reset": current_time.isoformat()
                }

            if current_date not in playtime_data[user_id]["daily_playtime"]:
                playtime_data[user_id]["daily_playtime"][current_date] = 0
            playtime_data[user_id]["daily_playtime"][current_date] += time_played

            fourteen_days_ago = (current_time - timedelta(days=14)).date().isoformat()
            playtime_data[user_id]["daily_playtime"] = {
                date: minutes
                for date, minutes in playtime_data[user_id]["daily_playtime"].items()
                if date >= fourteen_days_ago
            }

            save_playtime_data(playtime_data)

        if user_id in online_start_times:
            start_time = online_start_times[user_id]
            time_online = (current_time - start_time).total_seconds() / 60

            if user_id not in playtime_data:
                playtime_data[user_id] = {
                    "daily_playtime": {},
                    "daily_online": {},
                    "weekly_online": {},
                    "last_reset": current_time.isoformat()
                }

            last_reset = datetime.fromisoformat(playtime_data[user_id]["last_reset"]).astimezone(VN_TIMEZONE)
            if current_time - last_reset > timedelta(days=14):
                playtime_data[user_id] = {
                    "daily_playtime": {},
                    "daily_online": {},
                    "weekly_online": {},
                    "last_reset": current_time.isoformat()
                }

            # Chia thời gian on-duty theo ngày
            current_date = start_time
            while current_date.date() <= current_time.date():
                date_str = current_date.date().isoformat()
                if date_str not in playtime_data[user_id]["daily_online"]:
                    playtime_data[user_id]["daily_online"][date_str] = 0

                if current_date.date() == current_time.date():
                    end_of_period = current_time
                else:
                    end_of_period = datetime.combine(current_date.date() + timedelta(days=1), datetime.min.time(), tzinfo=VN_TIMEZONE) - timedelta(seconds=1)

                if current_date.date() == start_time.date():
                    start_of_period = start_time
                else:
                    start_of_period = datetime.combine(current_date.date(), datetime.min.time(), tzinfo=VN_TIMEZONE)

                time_in_day = (end_of_period - start_of_period).total_seconds() / 60
                playtime_data[user_id]["daily_online"][date_str] += time_in_day

                current_week_start, _ = get_week_boundaries(current_date.date())
                week_key = current_week_start.isoformat()
                if "weekly_online" not in playtime_data[user_id]:
                    playtime_data[user_id]["weekly_online"] = {}
                if week_key not in playtime_data[user_id]["weekly_online"]:
                    playtime_data[user_id]["weekly_online"][week_key] = 0
                playtime_data[user_id]["weekly_online"][week_key] += time_in_day

                current_date = current_date + timedelta(days=1)

            fourteen_days_ago = (current_time - timedelta(days=14)).date().isoformat()
            playtime_data[user_id]["daily_online"] = {
                date: minutes
                for date, minutes in playtime_data[user_id]["daily_online"].items()
                if date >= fourteen_days_ago
            }

            two_weeks_ago = (current_time - timedelta(days=14)).date().isoformat()
            playtime_data[user_id]["weekly_online"] = {
                week: minutes
                for week, minutes in playtime_data[user_id]["weekly_online"].items()
                if week >= two_weeks_ago
            }

            save_playtime_data(playtime_data)
            del online_start_times[user_id]

        if user_id in activity_data:
            if activity_data[user_id].get("in_vinewood", False):
                start_time_str = activity_data[user_id].get("vinewood_start_time")
                if start_time_str:
                    start_time = datetime.fromisoformat(start_time_str).astimezone(VN_TIMEZONE)
                    time_spent_seconds = (current_time - start_time).total_seconds()
                    hours = int(time_spent_seconds // 3600)
                    minutes = int((time_spent_seconds % 3600) // 60)
                    seconds = int(time_spent_seconds % 60)
                    channel = bot.get_channel(NOTIFICATION_CHANNEL_ID)
                    if channel:
                        await channel.send(
                            f"{after.name} đã rời khỏi khu vực Vinewood Park Dr sau {hours} giờ {minutes} phút {seconds} giây "
                            f"vào lúc {current_time.strftime('%H:%M:%S %Y-%m-%d')} do offline."
                        )
            activity_data[user_id]["in_vinewood"] = False
            activity_data[user_id]["vinewood_start_time"] = None
            save_activity_data(activity_data)

        if user_id in paused_online_times:
            del paused_online_times[user_id]

@bot.command()
async def help(ctx):
    if not ctx.guild:
        await ctx.send("Lệnh !help chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    # Kiểm tra xem người dùng có phải là admin không
    is_admin = has_admin_role(ctx.author)

    # Lấy thời gian hiện tại theo múi giờ Việt Nam
    current_time = datetime.now(VN_TIMEZONE)
    formatted_time = current_time.strftime('%H:%M:%S %d/%m/%Y')

    # Tạo embed cho menu help
    embed = discord.Embed(
        title="📋 **Hướng Dẫn Sử Dụng Bot**",
        description="Danh sách các lệnh có sẵn trong bot. Hãy đọc kỹ để sử dụng đúng cách!",
        color=discord.Color.green() if not is_admin else discord.Color.gold()
    )

    # Phần dành cho tất cả người dùng
    embed.add_field(
        name="🔹 **Lệnh Dành Cho Tất Cả Người Dùng**",
        value=(
            "Dưới đây là các lệnh mà mọi người có thể sử dụng:\n\n"
            "➡️ **!onduty**\n"
            "Bắt đầu trạng thái on-duty để tính thời gian online. Chỉ cần gõ lệnh để bắt đầu.\n\n"
            "➡️ **!offduty**\n"
            "Dừng trạng thái on-duty và lưu thời gian online của bạn.\n\n"
            "➡️ **!playtime [@user]**\n"
            "Xem thời gian chơi GTA5VN.NET và thời gian online (on-duty) của bạn hoặc người được tag. Người dùng thường chỉ xem được tuần hiện tại.\n\n"
            "➡️ **!checktime [@user]**\n"
            "Xem tổng thời gian on-duty trong tuần hiện tại (Thứ 2 đến Chủ Nhật) của bạn hoặc người được tag.\n\n"
            "➡️ **!checkdays [ngày/tháng] hoặc [ngày/tháng-ngày/tháng]**\n"
            "Xem thời gian on-duty trong một ngày (ví dụ: !checkdays 25/3) hoặc trong khoảng thời gian (ví dụ: !checkdays 25/3-30/3).\n\n"
            "➡️ **!help**\n"
            "Hiển thị menu hướng dẫn này."
        ),
        inline=False
    )

    # Phần dành riêng cho admin
    if is_admin:
        embed.add_field(
            name="🔸 **Lệnh Dành Riêng Cho Admin**",
            value=(
                "Dưới đây là các lệnh chỉ admin mới có thể sử dụng:\n\n"
                "➡️ **!checkstatus [@user]**\n"
                "Kiểm tra trạng thái on-duty/off-duty của bạn hoặc người được tag. Nếu đang on-duty, hiển thị thời gian đã on-duty.\n\n"
                "➡️ **!lichsu**\n"
                "Hiển thị lịch sử on-duty của tất cả người chơi trong tuần trước (từ Thứ 2 đến Chủ Nhật).\n\n"
                "➡️ **!checkreg**\n"
                "Hiển thị lịch sử on-duty của tất cả người chơi trong tuần hiện tại (từ Thứ 2 đến Chủ Nhật).\n\n"
                "➡️ **!checkduty**\n"
                "Hiển thị danh sách tất cả người chơi đang ở trạng thái on-duty.\n\n"
                "➡️ **!checkoff**\n"
                "Hiển thị danh sách tất cả người chơi đang ở trạng thái off-duty.\n\n"
                "➡️ **!doffduty @user**\n"
                "Tắt trạng thái on-duty của người dùng được tag (chỉ dành cho admin)."
            ),
            inline=False
        )

    # Footer của embed với thời gian hiện tại
    embed.set_footer(text=f"Bot được tạo bởi Thowm2005 | Thời gian hiện tại: {formatted_time}")
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/1354932216643190784/1354932353486819430/lapd-code3.gif?ex=67e71696&is=67e5c516&hm=2064572238be861f176127fbd23e557915c6811c3182e30e405be8134383d9e8&=")  # Thêm hình ảnh thumbnail (có thể thay đổi URL)

    await ctx.send(embed=embed)
@bot.command()
async def onduty(ctx):
    if not ctx.guild:
        await ctx.send("Lệnh !onduty chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    user_id = str(ctx.author.id)
    current_time = datetime.now(VN_TIMEZONE)

    if user_id in online_start_times:
        start_time = online_start_times[user_id]
        time_online = (current_time - start_time).total_seconds() / 60
        hours = int(time_online // 60)
        mins = int(time_online % 60)
        await ctx.send(f"Bạn đã ở trạng thái on-duty từ {start_time.strftime('%H:%M:%S %Y-%m-%d')}. Thời gian đã on-duty: {hours} giờ {mins} phút. Vui lòng dùng !offduty để dừng.")
        return

    if user_id not in user_mapping:
        guild_id = str(ctx.guild.id)
        user_mapping[user_id] = {"guild_id": guild_id}
        save_user_mapping(user_mapping)

    online_start_times[user_id] = current_time
    await ctx.send(f"{ctx.author.display_name} đã bắt đầu trạng thái on-duty lúc {current_time.strftime('%H:%M:%S %Y-%m-%d')}.")

@bot.command()
async def offduty(ctx):
    if not ctx.guild:
        await ctx.send("Lệnh !offduty chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    user_id = str(ctx.author.id)
    current_time = datetime.now(VN_TIMEZONE)

    if user_id not in online_start_times:
        await ctx.send("Bạn hiện không ở trạng thái on-duty.")
        return

    start_time = online_start_times[user_id]
    time_online = (current_time - start_time).total_seconds() / 60

    if user_id not in playtime_data:
        playtime_data[user_id] = {
            "daily_playtime": {},
            "daily_online": {},
            "weekly_online": {},
            "last_reset": current_time.isoformat()
        }

    last_reset = datetime.fromisoformat(playtime_data[user_id]["last_reset"]).astimezone(VN_TIMEZONE)
    if current_time - last_reset > timedelta(days=14):
        playtime_data[user_id] = {
            "daily_playtime": {},
            "daily_online": {},
            "weekly_online": {},
            "last_reset": current_time.isoformat()
        }

    # Chia thời gian on-duty theo ngày
    current_date = start_time
    while current_date.date() <= current_time.date():
        date_str = current_date.date().isoformat()
        if date_str not in playtime_data[user_id]["daily_online"]:
            playtime_data[user_id]["daily_online"][date_str] = 0

        if current_date.date() == current_time.date():
            end_of_period = current_time
        else:
            end_of_period = datetime.combine(current_date.date() + timedelta(days=1), datetime.min.time(), tzinfo=VN_TIMEZONE) - timedelta(seconds=1)

        if current_date.date() == start_time.date():
            start_of_period = start_time
        else:
            start_of_period = datetime.combine(current_date.date(), datetime.min.time(), tzinfo=VN_TIMEZONE)

        time_in_day = (end_of_period - start_of_period).total_seconds() / 60
        playtime_data[user_id]["daily_online"][date_str] += time_in_day

        current_week_start, _ = get_week_boundaries(current_date.date())
        week_key = current_week_start.isoformat()
        if "weekly_online" not in playtime_data[user_id]:
            playtime_data[user_id]["weekly_online"] = {}
        if week_key not in playtime_data[user_id]["weekly_online"]:
            playtime_data[user_id]["weekly_online"][week_key] = 0
        playtime_data[user_id]["weekly_online"][week_key] += time_in_day

        current_date = current_date + timedelta(days=1)

    fourteen_days_ago = (current_time - timedelta(days=14)).date().isoformat()
    playtime_data[user_id]["daily_online"] = {
        date: minutes
        for date, minutes in playtime_data[user_id]["daily_online"].items()
        if date >= fourteen_days_ago
    }

    two_weeks_ago = (current_time - timedelta(days=14)).date().isoformat()
    playtime_data[user_id]["weekly_online"] = {
        week: minutes
        for week, minutes in playtime_data[user_id]["weekly_online"].items()
        if week >= two_weeks_ago
    }

    save_playtime_data(playtime_data)
    del online_start_times[user_id]

    await ctx.send(f"{ctx.author.display_name} đã dừng trạng thái on-duty. Thời gian online: {int(time_online // 60)} giờ {int(time_online % 60)} phút.")

@bot.command()
async def doffduty(ctx, member: discord.Member):
    if not ctx.guild:
        await ctx.send("Lệnh !doffduty chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    if not has_admin_role(ctx.author):
        await ctx.send("Bạn không có quyền sử dụng lệnh này. Lệnh này chỉ dành cho admin.")
        return

    user_id = str(member.id)
    current_time = datetime.now(VN_TIMEZONE)

    if user_id not in online_start_times:
        await ctx.send(f"{member.display_name} hiện không ở trạng thái on-duty.")
        return

    start_time = online_start_times[user_id]
    time_online = (current_time - start_time).total_seconds() / 60

    if user_id not in playtime_data:
        playtime_data[user_id] = {
            "daily_playtime": {},
            "daily_online": {},
            "weekly_online": {},
            "last_reset": current_time.isoformat()
        }

    last_reset = datetime.fromisoformat(playtime_data[user_id]["last_reset"]).astimezone(VN_TIMEZONE)
    if current_time - last_reset > timedelta(days=14):
        playtime_data[user_id] = {
            "daily_playtime": {},
            "daily_online": {},
            "weekly_online": {},
            "last_reset": current_time.isoformat()
        }

    # Chia thời gian on-duty theo ngày
    current_date = start_time
    while current_date.date() <= current_time.date():
        date_str = current_date.date().isoformat()
        if date_str not in playtime_data[user_id]["daily_online"]:
            playtime_data[user_id]["daily_online"][date_str] = 0

        if current_date.date() == current_time.date():
            end_of_period = current_time
        else:
            end_of_period = datetime.combine(current_date.date() + timedelta(days=1), datetime.min.time(), tzinfo=VN_TIMEZONE) - timedelta(seconds=1)

        if current_date.date() == start_time.date():
            start_of_period = start_time
        else:
            start_of_period = datetime.combine(current_date.date(), datetime.min.time(), tzinfo=VN_TIMEZONE)

        time_in_day = (end_of_period - start_of_period).total_seconds() / 60
        playtime_data[user_id]["daily_online"][date_str] += time_in_day

        current_week_start, _ = get_week_boundaries(current_date.date())
        week_key = current_week_start.isoformat()
        if "weekly_online" not in playtime_data[user_id]:
            playtime_data[user_id]["weekly_online"] = {}
        if week_key not in playtime_data[user_id]["weekly_online"]:
            playtime_data[user_id]["weekly_online"][week_key] = 0
        playtime_data[user_id]["weekly_online"][week_key] += time_in_day

        current_date = current_date + timedelta(days=1)

    fourteen_days_ago = (current_time - timedelta(days=14)).date().isoformat()
    playtime_data[user_id]["daily_online"] = {
        date: minutes
        for date, minutes in playtime_data[user_id]["daily_online"].items()
        if date >= fourteen_days_ago
    }

    two_weeks_ago = (current_time - timedelta(days=14)).date().isoformat()
    playtime_data[user_id]["weekly_online"] = {
        week: minutes
        for week, minutes in playtime_data[user_id]["weekly_online"].items()
        if week >= two_weeks_ago
    }

    save_playtime_data(playtime_data)
    del online_start_times[user_id]

    await ctx.send(f"{member.display_name} đã bị admin {ctx.author.display_name} tắt trạng thái on-duty. Thời gian online: {int(time_online // 60)} giờ {int(time_online % 60)} phút.")

@bot.command()
async def checkstatus(ctx, member: discord.Member = None):
    if not ctx.guild:
        await ctx.send("Lệnh !checkstatus chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    if not has_admin_role(ctx.author):
        await ctx.send("Bạn không có quyền sử dụng lệnh này. Lệnh này chỉ dành cho admin.")
        return

    member = member or ctx.author
    target_user_id = str(member.id)

    current_time = datetime.now(VN_TIMEZONE)

    if target_user_id in online_start_times:
        start_time = online_start_times[target_user_id]
        time_online = (current_time - start_time).total_seconds() / 60
        hours = int(time_online // 60)
        mins = int(time_online % 60)
        await ctx.send(f"{member.display_name} đang ở trạng thái **on-duty** từ {start_time.strftime('%H:%M:%S %Y-%m-%d')}. Thời gian đã on-duty: {hours} giờ {mins} phút.")
    else:
        await ctx.send(f"{member.display_name} hiện đang ở trạng thái **off-duty**.")

@bot.command()
async def playtime(ctx, member: discord.Member = None):
    if not ctx.guild:
        await ctx.send("Lệnh !playtime chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    member = member or ctx.author
    target_user_id = str(member.id)

    if target_user_id not in playtime_data:
        await ctx.send(f"{member.display_name} chưa chơi GTA5VN.NET hoặc chưa ở trạng thái on-duty trong 2 tuần qua.")
        return

    current_time = datetime.now(VN_TIMEZONE)
    current_date = current_time.date()

    current_week_start, current_week_end = get_week_boundaries(current_date)
    previous_week_start = current_week_start - timedelta(days=7)
    previous_week_end = current_week_end - timedelta(days=7)

    has_admin = has_admin_role(ctx.author)
    weeks_to_show = 2 if has_admin else 1

    summary = f"Thống kê thời gian của {member.display_name}:\n"

    for week_offset in range(weeks_to_show):
        week_start = current_week_start - timedelta(days=7 * week_offset)
        week_end = current_week_end - timedelta(days=7 * week_offset)
        week_start_str = week_start.isoformat()
        week_end_str = week_end.isoformat()

        total_playtime = 0
        playtime_summary = f"\nThời gian chơi GTA5VN.NET từ {week_start_str} đến {week_end_str}:\n"
        if "daily_playtime" in playtime_data[target_user_id]:
            for date, minutes in playtime_data[target_user_id]["daily_playtime"].items():
                if week_start_str <= date <= week_end_str:
                    total_playtime += minutes
                    hours = minutes // 60
                    mins = minutes % 60
                    playtime_summary += f"- {date}: {int(hours)} giờ {int(mins)} phút\n"

        if total_playtime == 0:
            playtime_summary += "Chưa có dữ liệu chơi game.\n"
        else:
            total_hours = total_playtime // 60
            total_mins = total_playtime % 60
            playtime_summary += f"\nTổng thời gian chơi: {int(total_hours)} giờ {int(total_mins)} phút\n"

        summary += playtime_summary

    for week_offset in range(weeks_to_show):
        week_start = current_week_start - timedelta(days=7 * week_offset)
        week_end = current_week_end - timedelta(days=7 * week_offset)
        week_start_str = week_start.isoformat()
        week_end_str = week_end.isoformat()

        total_online = 0
        online_summary = f"\nThời gian online (on-duty) từ {week_start_str} đến {week_end_str}:\n"
        if "daily_online" in playtime_data[target_user_id]:
            for date, minutes in playtime_data[target_user_id]["daily_online"].items():
                if week_start_str <= date <= week_end_str:
                    total_online += minutes
                    hours = minutes // 60
                    mins = minutes % 60
                    online_summary += f"- {date}: {int(hours)} giờ {int(mins)} phút\n"

        if total_online == 0:
            online_summary += "Chưa có dữ liệu online.\n"
        else:
            total_online_hours = total_online // 60
            total_online_mins = total_online % 60
            online_summary += f"\nTổng thời gian online: {int(total_online_hours)} giờ {int(total_online_mins)} phút\n"

        summary += online_summary

    await ctx.send(summary)

@bot.command()
async def checktime(ctx, member: discord.Member = None):
    if not ctx.guild:
        await ctx.send("Lệnh !checktime chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    member = member or ctx.author
    target_user_id = str(member.id)

    if target_user_id not in playtime_data or "weekly_online" not in playtime_data[target_user_id]:
        await ctx.send(f"{member.display_name} chưa có dữ liệu on-duty nào được ghi nhận trong tuần hiện tại.")
        return

    current_time = datetime.now(VN_TIMEZONE)
    current_date = current_time.date()

    current_week_start, current_week_end = get_week_boundaries(current_date)
    week_key = current_week_start.isoformat()

    total_online = playtime_data[target_user_id]["weekly_online"].get(week_key, 0)

    hours = int(total_online // 60)
    mins = int(total_online % 60)

    await ctx.send(f"Tổng thời gian on-duty của {member.display_name} trong tuần hiện tại (từ {current_week_start} đến {current_week_end}): {hours}h {mins}m.")

@bot.command(name="checkdays")
async def checkdays(ctx, *, date_range: str):
    if not ctx.guild:
        await ctx.send("Lệnh !checkdays chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    current_time = datetime.now(VN_TIMEZONE)
    current_year = current_time.year

    if "-" in date_range:
        try:
            start_date_str, end_date_str = date_range.split("-")
            start_day, start_month = map(int, start_date_str.split("/"))
            end_day, end_month = map(int, end_date_str.split("/"))

            start_date = date(current_year, start_month, start_day)
            end_date = date(current_year, end_month, end_day)

            if start_date > end_date:
                await ctx.send("Ngày bắt đầu phải nhỏ hơn hoặc bằng ngày kết thúc. Vui lòng thử lại.")
                return

        except ValueError:
            await ctx.send("Định dạng không hợp lệ. Vui lòng sử dụng định dạng: !checkdays ngày/tháng hoặc !checkdays ngày/tháng-ngày/tháng (ví dụ: !checkdays 25/3 hoặc !checkdays 25/3-30/3).")
            return

        start_date_str = start_date.isoformat()
        end_date_str = end_date.isoformat()

        report = f"📊 **Thời gian on-duty từ {start_date.strftime('%d/%m/%Y')} đến {end_date.strftime('%d/%m/%Y')}**:\n"
        users_reported = 0

        users_to_remove = []

        for user_id, user_info in user_mapping.items():
            if not isinstance(user_info, dict):
                users_to_remove.append(user_id)
                continue

            guild_id = user_info.get("guild_id")
            if not guild_id:
                users_to_remove.append(user_id)
                continue

            guild = bot.get_guild(int(guild_id))
            if not guild:
                users_to_remove.append(user_id)
                continue

            member = guild.get_member(int(user_id))
            if not member:
                continue

            total_online = 0
            if user_id in playtime_data and "daily_online" in playtime_data[user_id]:
                for date_str, minutes in playtime_data[user_id]["daily_online"].items():
                    date_obj = datetime.fromisoformat(date_str).date()
                    if start_date <= date_obj <= end_date:
                        total_online += minutes

            if total_online > 0:
                hours = int(total_online // 60)
                mins = int(total_online % 60)
                report += f"- {member.display_name}: {hours}h {mins}m\n"
                users_reported += 1

        if users_reported == 0:
            report += f"Không có ai on-duty trong khoảng thời gian từ {start_date.strftime('%d/%m/%Y')} đến {end_date.strftime('%d/%m/%Y')}.\n"

    else:
        try:
            day, month = map(int, date_range.split("/"))
            target_date = date(current_year, month, day)
        except ValueError:
            await ctx.send("Định dạng không hợp lệ. Vui lòng sử dụng định dạng: !checkdays ngày/tháng hoặc !checkdays ngày/tháng-ngày/tháng (ví dụ: !checkdays 25/3 hoặc !checkdays 25/3-30/3).")
            return

        target_date_str = target_date.isoformat()

        report = f"📊 **Thời gian on-duty ngày {target_date.strftime('%d/%m/%Y')}**:\n"
        users_reported = 0

        users_to_remove = []

        for user_id, user_info in user_mapping.items():
            if not isinstance(user_info, dict):
                users_to_remove.append(user_id)
                continue

            guild_id = user_info.get("guild_id")
            if not guild_id:
                users_to_remove.append(user_id)
                continue

            guild = bot.get_guild(int(guild_id))
            if not guild:
                users_to_remove.append(user_id)
                continue

            member = guild.get_member(int(user_id))
            if not member:
                continue

            total_online = 0
            if user_id in playtime_data and "daily_online" in playtime_data[user_id]:
                total_online = playtime_data[user_id]["daily_online"].get(target_date_str, 0)

            if total_online > 0:
                hours = int(total_online // 60)
                mins = int(total_online % 60)
                report += f"- {member.display_name}: {hours}h {mins}m\n"
                users_reported += 1

        if users_reported == 0:
            report += f"Không có ai on-duty trong ngày {target_date.strftime('%d/%m/%Y')}.\n"

    await ctx.send(report)

    for user_id in users_to_remove:
        if user_id in user_mapping:
            del user_mapping[user_id]
    if users_to_remove:
        save_user_mapping(user_mapping)

@bot.command(name="lichsu")
async def lichsu_onduty(ctx):
    if not ctx.guild:
        await ctx.send("Lệnh !lichsu chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    if not has_admin_role(ctx.author):
        await ctx.send("Bạn không có quyền sử dụng lệnh này. Lệnh này chỉ dành cho admin.")
        return

    current_time = datetime.now(VN_TIMEZONE)
    current_date = current_time.date()

    current_week_start, _ = get_week_boundaries(current_date)
    last_week_start = current_week_start - timedelta(days=7)
    last_week_end = last_week_start + timedelta(days=6)
    last_week_key = last_week_start.isoformat()

    report = f"📊 **Lịch sử on-duty tuần trước (từ {last_week_start} đến {last_week_end})**:\n"
    users_reported = 0

    users_to_remove = []

    for user_id, user_info in user_mapping.items():
        if not isinstance(user_info, dict):
            users_to_remove.append(user_id)
            continue

        guild_id = user_info.get("guild_id")
        if not guild_id:
            users_to_remove.append(user_id)
            continue

        guild = bot.get_guild(int(guild_id))
        if not guild:
            users_to_remove.append(user_id)
            continue

        member = guild.get_member(int(user_id))
        if not member:
            continue

        total_online = 0
        if user_id in playtime_data and "weekly_online" in playtime_data[user_id]:
            total_online = playtime_data[user_id]["weekly_online"].get(last_week_key, 0)

        if total_online > 0:
            hours = int(total_online // 60)
            mins = int(total_online % 60)
            report += f"- {member.display_name}: {hours}h {mins}m/1 tuần\n"
            users_reported += 1

    if users_reported == 0:
        report += "Không có ai on-duty trong tuần trước.\n"

    await ctx.send(report)

    for user_id in users_to_remove:
        if user_id in user_mapping:
            del user_mapping[user_id]
    if users_to_remove:
        save_user_mapping(user_mapping)

@bot.command(name="checkreg")
async def checkreg(ctx):
    if not ctx.guild:
        await ctx.send("Lệnh !checkreg chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    if not has_admin_role(ctx.author):
        await ctx.send("Bạn không có quyền sử dụng lệnh này. Lệnh này chỉ dành cho admin.")
        return

    current_time = datetime.now(VN_TIMEZONE)
    current_date = current_time.date()

    current_week_start, current_week_end = get_week_boundaries(current_date)
    week_key = current_week_start.isoformat()

    report = f"📊 **Lịch sử on-duty tuần hiện tại (từ {current_week_start} đến {current_week_end})**:\n"
    users_reported = 0

    users_to_remove = []

    for user_id, user_info in user_mapping.items():
        if not isinstance(user_info, dict):
            users_to_remove.append(user_id)
            continue

        guild_id = user_info.get("guild_id")
        if not guild_id:
            users_to_remove.append(user_id)
            continue

        guild = bot.get_guild(int(guild_id))
        if not guild:
            users_to_remove.append(user_id)
            continue

        member = guild.get_member(int(user_id))
        if not member:
            continue

        total_online = 0
        if user_id in playtime_data and "weekly_online" in playtime_data[user_id]:
            total_online = playtime_data[user_id]["weekly_online"].get(week_key, 0)

        if total_online > 0:
            hours = int(total_online // 60)
            mins = int(total_online % 60)
            report += f"- {member.display_name}: {hours}h {mins}m\n"
            users_reported += 1

    if users_reported == 0:
        report += "Không có ai on-duty trong tuần hiện tại.\n"

    await ctx.send(report)

    for user_id in users_to_remove:
        if user_id in user_mapping:
            del user_mapping[user_id]
    if users_to_remove:
        save_user_mapping(user_mapping)

@bot.command(name="checkduty")
async def checkduty(ctx):
    if not ctx.guild:
        await ctx.send("Lệnh !checkduty chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    if not has_admin_role(ctx.author):
        await ctx.send("Bạn không có quyền sử dụng lệnh này. Lệnh này chỉ dành cho admin.")
        return

    current_time = datetime.now(VN_TIMEZONE)
    report = "📊 **Danh sách người chơi đang on-duty**:\n"
    users_reported = 0

    users_to_remove = []

    for user_id, user_info in user_mapping.items():
        if not isinstance(user_info, dict):
            users_to_remove.append(user_id)
            continue

        guild_id = user_info.get("guild_id")
        if not guild_id:
            users_to_remove.append(user_id)
            continue

        guild = bot.get_guild(int(guild_id))
        if not guild:
            users_to_remove.append(user_id)
            continue

        member = guild.get_member(int(user_id))
        if not member:
            continue

        if user_id in online_start_times:
            start_time = online_start_times[user_id]
            time_online = (current_time - start_time).total_seconds() / 60
            hours = int(time_online // 60)
            mins = int(time_online % 60)
            report += f"- {member.display_name}: {hours}h {mins}m (bắt đầu từ {start_time.strftime('%H:%M:%S %Y-%m-%d')})\n"
            users_reported += 1

    if users_reported == 0:
        report += "Không có ai đang on-duty.\n"

    await ctx.send(report)

    for user_id in users_to_remove:
        if user_id in user_mapping:
            del user_mapping[user_id]
    if users_to_remove:
        save_user_mapping(user_mapping)

@bot.command(name="checkoff")
async def checkoff(ctx):
    if not ctx.guild:
        await ctx.send("Lệnh !checkoff chỉ có thể được sử dụng trong server, không hỗ trợ trong DM.")
        return

    if not has_admin_role(ctx.author):
        await ctx.send("Bạn không có quyền sử dụng lệnh này. Lệnh này chỉ dành cho admin.")
        return

    report = "📊 **Danh sách người chơi đang off-duty**:\n"
    users_reported = 0

    users_to_remove = []

    for user_id, user_info in user_mapping.items():
        if not isinstance(user_info, dict):
            users_to_remove.append(user_id)
            continue

        guild_id = user_info.get("guild_id")
        if not guild_id:
            users_to_remove.append(user_id)
            continue

        guild = bot.get_guild(int(guild_id))
        if not guild:
            users_to_remove.append(user_id)
            continue

        member = guild.get_member(int(user_id))
        if not member:
            continue

        if user_id not in online_start_times:
            report += f"- {member.display_name}\n"
            users_reported += 1

    if users_reported == 0:
        report += "Không có ai đang off-duty.\n"

    await ctx.send(report)

    for user_id in users_to_remove:
        if user_id in user_mapping:
            del user_mapping[user_id]
    if users_to_remove:
        save_user_mapping(user_mapping)

bot.run("MTE0MDk5NTc0MjExOTUxMDExNw.GgxtR5.qeWGlPE6m5r3VLAlwcs5uecCWZmakRDDGH4wms")
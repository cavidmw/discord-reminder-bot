import os
import sqlite3
import asyncio
import threading
from datetime import datetime
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Baku")
TZ = ZoneInfo(TIMEZONE)
DB_FILE = "reminders.db"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

    def log_message(self, format, *args):
        return


def start_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel_id INTEGER NOT NULL,
            remind_at TEXT NOT NULL,
            message TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def add_reminder(user_id, channel_id, remind_at, message):
    conn = db()
    cur = conn.execute(
        "INSERT INTO reminders (user_id, channel_id, remind_at, message) VALUES (?, ?, ?, ?)",
        (user_id, channel_id, remind_at.isoformat(), message)
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_user_reminders(user_id):
    conn = db()
    rows = conn.execute(
        "SELECT id, remind_at, message FROM reminders WHERE user_id = ? ORDER BY remind_at ASC",
        (user_id,)
    ).fetchall()
    conn.close()
    return rows


def get_reminder(reminder_id, user_id):
    conn = db()
    row = conn.execute(
        "SELECT id, user_id, channel_id, remind_at, message FROM reminders WHERE id = ? AND user_id = ?",
        (reminder_id, user_id)
    ).fetchone()
    conn.close()
    return row


def delete_reminder(reminder_id, user_id):
    conn = db()
    cur = conn.execute(
        "DELETE FROM reminders WHERE id = ? AND user_id = ?",
        (reminder_id, user_id)
    )
    conn.commit()
    deleted = cur.rowcount
    conn.close()
    return deleted > 0


def update_reminder(reminder_id, user_id, remind_at, message):
    conn = db()
    cur = conn.execute(
        "UPDATE reminders SET remind_at = ?, message = ? WHERE id = ? AND user_id = ?",
        (remind_at.isoformat(), message, reminder_id, user_id)
    )
    conn.commit()
    updated = cur.rowcount
    conn.close()
    return updated > 0


class TimerModal(discord.ui.Modal, title="Yeni Hatırlatıcı"):
    tarih = discord.ui.TextInput(
        label="Tarih",
        placeholder="Örnek: 2026-05-01",
        required=True,
        max_length=10
    )

    saat = discord.ui.TextInput(
        label="Saat",
        placeholder="Örnek: 18:30",
        required=True,
        max_length=5
    )

    mesaj = discord.ui.TextInput(
        label="Mesaj",
        placeholder="Örnek: Video paylaş",
        required=True,
        max_length=500,
        style=discord.TextStyle.paragraph
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            remind_time = datetime.strptime(
                f"{self.tarih.value} {self.saat.value}",
                "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)
        except ValueError:
            await interaction.response.send_message(
                "Format yanlış. Tarih `2026-05-01`, saat `18:30` şeklinde olmalı.",
                ephemeral=True
            )
            return

        if remind_time <= datetime.now(TZ):
            await interaction.response.send_message(
                "Geçmiş zamana hatırlatıcı kurulmaz.",
                ephemeral=True
            )
            return

        rid = add_reminder(
            interaction.user.id,
            interaction.channel.id,
            remind_time,
            str(self.mesaj.value)
        )

        embed = discord.Embed(
            title="⏰ Hatırlatıcı Kuruldu",
            description=f"**Tarih:** {remind_time.strftime('%d.%m.%Y %H:%M')}\n**Mesaj:** {self.mesaj.value}",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"ID: {rid}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


class EditTimerModal(discord.ui.Modal):
    def __init__(self, reminder_id: int, old_date: str, old_time: str, old_message: str):
        super().__init__(title=f"Hatırlatıcı Düzenle #{reminder_id}")
        self.reminder_id = reminder_id

        self.tarih = discord.ui.TextInput(
            label="Yeni Tarih",
            default=old_date,
            placeholder="Örnek: 2026-05-01",
            required=True,
            max_length=10
        )

        self.saat = discord.ui.TextInput(
            label="Yeni Saat",
            default=old_time,
            placeholder="Örnek: 18:30",
            required=True,
            max_length=5
        )

        self.mesaj = discord.ui.TextInput(
            label="Yeni Mesaj",
            default=old_message[:500],
            placeholder="Örnek: Video paylaş",
            required=True,
            max_length=500,
            style=discord.TextStyle.paragraph
        )

        self.add_item(self.tarih)
        self.add_item(self.saat)
        self.add_item(self.mesaj)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            remind_time = datetime.strptime(
                f"{self.tarih.value} {self.saat.value}",
                "%Y-%m-%d %H:%M"
            ).replace(tzinfo=TZ)
        except ValueError:
            await interaction.response.send_message(
                "Format yanlış. Tarih `2026-05-01`, saat `18:30` şeklinde olmalı.",
                ephemeral=True
            )
            return

        if remind_time <= datetime.now(TZ):
            await interaction.response.send_message(
                "Geçmiş zamana ayarlayamazsın.",
                ephemeral=True
            )
            return

        ok = update_reminder(
            self.reminder_id,
            interaction.user.id,
            remind_time,
            str(self.mesaj.value)
        )

        if not ok:
            await interaction.response.send_message("Bu hatırlatıcı bulunamadı.", ephemeral=True)
            return

        embed = discord.Embed(
            title="✏️ Hatırlatıcı Güncellendi",
            description=f"**Tarih:** {remind_time.strftime('%d.%m.%Y %H:%M')}\n**Mesaj:** {self.mesaj.value}",
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"ID: {self.reminder_id}")

        await interaction.response.send_message(embed=embed, ephemeral=True)


class ReminderButtons(discord.ui.View):
    def __init__(self, reminder_id: int):
        super().__init__(timeout=300)
        self.reminder_id = reminder_id

    @discord.ui.button(label="Düzenle", emoji="✏️", style=discord.ButtonStyle.primary)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        row = get_reminder(self.reminder_id, interaction.user.id)

        if not row:
            await interaction.response.send_message("Bu hatırlatıcı artıq yoxdur.", ephemeral=True)
            return

        rid, user_id, channel_id, remind_at, message = row
        dt = datetime.fromisoformat(remind_at).astimezone(TZ)

        modal = EditTimerModal(
            reminder_id=rid,
            old_date=dt.strftime("%Y-%m-%d"),
            old_time=dt.strftime("%H:%M"),
            old_message=message
        )
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Sil", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        ok = delete_reminder(self.reminder_id, interaction.user.id)

        if not ok:
            await interaction.response.send_message("Bu hatırlatıcı tapılmadı.", ephemeral=True)
            return

        await interaction.response.edit_message(
            content=f"🗑️ Hatırlatıcı `#{self.reminder_id}` silindi.",
            embed=None,
            view=None
        )


@bot.event
async def on_ready():
    db()
    print(f"Bot giriş yaptı: {bot.user}")

    try:
        synced = await bot.tree.sync()
        print(f"Slash komutları yüklendi: {len(synced)}")
    except Exception as e:
        print("Slash sync hatası:", e)

    if not hasattr(bot, "reminder_started"):
        bot.reminder_started = True
        bot.loop.create_task(reminder_loop())


@bot.tree.command(name="timer", description="Yeni hatırlatıcı oluşturur.")
async def timer(interaction: discord.Interaction):
    await interaction.response.send_modal(TimerModal())


@bot.tree.command(name="timerler", description="Tüm hatırlatıcılarını gösterir.")
async def timerler(interaction: discord.Interaction):
    rows = get_user_reminders(interaction.user.id)

    if not rows:
        await interaction.response.send_message("Aktif hatırlatıcın yok.", ephemeral=True)
        return

    await interaction.response.send_message(
        f"Toplam **{len(rows)}** hatırlatıcın var. Aşağıda yönetebilirsin:",
        ephemeral=True
    )

    for rid, remind_at, message in rows[:10]:
        dt = datetime.fromisoformat(remind_at).astimezone(TZ)

        embed = discord.Embed(
            title=f"⏰ Hatırlatıcı #{rid}",
            description=f"**Tarih:** {dt.strftime('%d.%m.%Y %H:%M')}\n**Mesaj:** {message}",
            color=discord.Color.blurple()
        )

        await interaction.followup.send(
            embed=embed,
            view=ReminderButtons(rid),
            ephemeral=True
        )

    if len(rows) > 10:
        await interaction.followup.send(
            "Şimdilik ilk 10 hatırlatıcı gösterildi. Sonra sayfalama da ekleriz.",
            ephemeral=True
        )


@bot.tree.command(name="hatirlat", description="Eski sistem: tarih ve saat yazarak hatırlatıcı kurar.")
@app_commands.describe(
    tarih="Örnek: 2026-05-01",
    saat="Örnek: 18:30",
    mesaj="Hatırlatma mesajı"
)
async def hatirlat(interaction: discord.Interaction, tarih: str, saat: str, mesaj: str):
    try:
        remind_time = datetime.strptime(f"{tarih} {saat}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    except ValueError:
        await interaction.response.send_message(
            "Format yanlış. Örnek: `/hatirlat tarih:2026-05-01 saat:18:30 mesaj:video yükle`",
            ephemeral=True
        )
        return

    if remind_time <= datetime.now(TZ):
        await interaction.response.send_message("Geçmiş zamana hatırlatma kurulmaz.", ephemeral=True)
        return

    rid = add_reminder(interaction.user.id, interaction.channel.id, remind_time, mesaj)

    await interaction.response.send_message(
        f"Tamamdır. Seni **{remind_time.strftime('%d.%m.%Y %H:%M')}** tarihinde uyaracağım.\nMesaj: `{mesaj}`\nID: `#{rid}`",
        ephemeral=True
    )


async def reminder_loop():
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            now = datetime.now(TZ).isoformat()
            conn = db()
            rows = conn.execute(
                "SELECT id, user_id, channel_id, message FROM reminders WHERE remind_at <= ?",
                (now,)
            ).fetchall()

            for rid, user_id, channel_id, message in rows:
                channel = bot.get_channel(channel_id)
                if channel:
                    await channel.send(f"<@{user_id}> ⏰ Hatırlatma: **{message}**")
                conn.execute("DELETE FROM reminders WHERE id = ?", (rid,))

            conn.commit()
            conn.close()

        except Exception as e:
            print("Reminder loop hatası:", e)

        await asyncio.sleep(30)


if not TOKEN:
    print("DISCORD_TOKEN yok. Render Environment kısmına ekle.")
else:
    threading.Thread(target=start_web_server, daemon=True).start()
    bot.run(TOKEN)
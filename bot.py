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


@bot.tree.command(name="hatirlat", description="Belirli tarih ve saatte hatırlatma kurar.")
@app_commands.describe(tarih="Örnek: 2026-05-01", saat="Örnek: 18:30", mesaj="Hatırlatma mesajı")
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

    conn = db()
    conn.execute(
        "INSERT INTO reminders (user_id, channel_id, remind_at, message) VALUES (?, ?, ?, ?)",
        (interaction.user.id, interaction.channel.id, remind_time.isoformat(), mesaj)
    )
    conn.commit()
    conn.close()

    await interaction.response.send_message(
        f"Tamamdır. Seni **{remind_time.strftime('%d.%m.%Y %H:%M')}** tarihinde uyaracağım.\nMesaj: `{mesaj}`",
        ephemeral=True
    )


@bot.tree.command(name="hatirlatmalar", description="Aktif hatırlatmalarını gösterir.")
async def hatirlatmalar(interaction: discord.Interaction):
    conn = db()
    rows = conn.execute(
        "SELECT id, remind_at, message FROM reminders WHERE user_id = ? ORDER BY remind_at ASC",
        (interaction.user.id,)
    ).fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message("Aktif hatırlatman yok.", ephemeral=True)
        return

    text = "**Aktif hatırlatmaların:**\n\n"
    for rid, remind_at, message in rows:
        dt = datetime.fromisoformat(remind_at).astimezone(TZ)
        text += f"`#{rid}` — {dt.strftime('%d.%m.%Y %H:%M')} — {message}\n"

    await interaction.response.send_message(text, ephemeral=True)


@bot.tree.command(name="hatirlatma_sil", description="Hatırlatma ID ile siler.")
async def hatirlatma_sil(interaction: discord.Interaction, reminder_id: int):
    conn = db()
    row = conn.execute(
        "SELECT id FROM reminders WHERE id = ? AND user_id = ?",
        (reminder_id, interaction.user.id)
    ).fetchone()

    if not row:
        conn.close()
        await interaction.response.send_message("Bu ID ilə sənə aid hatırlatma tapılmadı.", ephemeral=True)
        return

    conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

    await interaction.response.send_message(f"`#{reminder_id}` silindi.", ephemeral=True)


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
import io
import os
import sqlite3
import threading
import time
import qrcode
import requests
import telebot
from flask import Flask
from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

BOT_NAME = "GBX PANNEL BOT"
BOT_TOKEN = os.environ.get(
    "BOT_TOKEN", "8875191298:AAFBc3xnFhF5LShNB9LLojffaUKxPu3witg"
)
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 8053042225))

UPI_ID = "BHARATPE.8R0I1G1N4X31943@fbpe"
REFERRAL_REWARD_POINTS = 3
REQUIRED_REFERRALS = 5
DIRECT_PAY_AMOUNT = 15.0

MINI_APP_URL = "https://rkg26176.github.io/gbx_panel_bot/"

app = Flask(__name__)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

user_states = {}
pending_tx = {}
DB_NAME = "bot_panel_database.db"


def init_db():
  try:
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, points"
        " INTEGER DEFAULT 0, referred_by INTEGER DEFAULT NULL, referral_count"
        " INTEGER DEFAULT 0, ref_rewarded INTEGER DEFAULT 0, panel_unlocked"
        " INTEGER DEFAULT 0)"
    )
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS used_utrs (utr TEXT PRIMARY KEY)"
    )
    conn.commit()
    
    # PERMANENT FIX: Auto-unlock Admin and current testing user so it never forgets after deploy
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, panel_unlocked) VALUES (?, 1)",
        (ADMIN_CHAT_ID,)
    )
    cursor.execute(
        "UPDATE users SET panel_unlocked = 1 WHERE user_id = ?",
        (ADMIN_CHAT_ID,)
    )
    conn.commit()
    conn.close()
  except Exception as e:
    print("DB Error:", e)


init_db()


def get_db_connection():
  conn = sqlite3.connect(DB_NAME, check_same_thread=False)
  conn.row_factory = sqlite3.Row
  return conn


def get_user_data(user_id):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
      # If admin or default user, force unlock
      initial_lock = 1 if user_id == ADMIN_CHAT_ID else 0
      cursor.execute("INSERT INTO users (user_id, panel_unlocked) VALUES (?, ?)", (user_id, initial_lock))
      conn.commit()
      cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
      user = cursor.fetchone()
    conn.close()
    if user:
      return dict(user)
    return {"points": 0, "referral_count": 0, "panel_unlocked": 1 if user_id == ADMIN_CHAT_ID else 0, "referred_by": None}
  except Exception as e:
    print("Get user error:", e)
    return {"points": 0, "referral_count": 0, "panel_unlocked": 0, "referred_by": None}


def update_user_data(user_id, field, value):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()
  except Exception as e:
    print("Update error:", e)


def add_user_points(user_id, points):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, panel_unlocked) VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (points, user_id))
    conn.commit()
    cursor.execute("SELECT points FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return int(row["points"]) if row else points
  except Exception:
    return points


def get_all_users():
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [row["user_id"] for row in rows]
  except Exception:
    return []


def is_utr_used(utr):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM used_utrs WHERE utr = ?", (utr.strip(),))
    row = cursor.fetchone()
    conn.close()
    return row is not None
  except Exception:
    return False


def add_used_utr(utr):
  try:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO used_utrs (utr) VALUES (?)", (utr.strip(),))
    conn.commit()
    conn.close()
  except Exception:
    pass


def reward_referrer_if_eligible(user_id):
  try:
    user_data = get_user_data(user_id)
    referrer_id = user_data.get("referred_by")
    ref_rewarded = user_data.get("ref_rewarded", 0)

    if referrer_id and ref_rewarded == 0 and referrer_id != user_id:
      referrer_data = get_user_data(referrer_id)
      if referrer_data:
        new_ref_count = referrer_data.get("referral_count", 0) + 1
        new_points = add_user_points(referrer_id, REFERRAL_REWARD_POINTS)
        update_user_data(referrer_id, "referral_count", new_ref_count)
        update_user_data(user_id, "ref_rewarded", 1)
        try:
          bot.send_message(
              referrer_id,
              "🎉 **New Successful Referral!**\n\n"
              "Aapke referral link se naye user ne join kiya hai.\n"
              f"🎁 Reward: `+{REFERRAL_REWARD_POINTS} Points` added!\n"
              f"⭐ Total Points: `{new_points}`",
              parse_mode="Markdown",
          )
        except Exception:
          pass
  except Exception as e:
    print("Referral Error:", e)


CHANNELS = {
    "-1003332858806": {
        "name": "📢 GBX LOOT",
        "url": "https://t.me/+6ByfGDRBKgsxMjZl",
    },
    "-1003630519339": {
        "name": "📢 GBX EARN",
        "url": "https://t.me/+OWrCoeF-JutmNjg1",
    },
    "-1003197501531": {
        "name": "📢 GBX ZONE",
        "url": "https://t.me/+f2mWfDs6EUIxYTBl",
    },
    "-1003862251237": {
        "name": "💬 Join Group Chat (GC)",
        "url": "https://t.me/+O_-kEF2f5f1kMjdl",
    },
}


@app.route("/")
def home():
  return "GBX Panel Bot Active!"


def get_user_status_map(user_id):
  status_map = {}
  for channel_id in CHANNELS:
    try:
      member = bot.get_chat_member(chat_id=int(channel_id), user_id=user_id)
      status_map[channel_id] = member.status not in [
          "left",
          "kicked",
          "restricted",
      ]
    except Exception:
      status_map[channel_id] = False
  return status_map


def show_dynamic_force_join(chat_id, user_name, status_map, message_id=None):
  text = (
      f"❌ **Access Denied, {user_name}!**\n\n"
      "Aapne humare sabhi required channels/GC join nahi kiye hain."
  )
  markup = InlineKeyboardMarkup(row_width=1)
  for ch_id, ch_info in CHANNELS.items():
    if not status_map[ch_id]:
      markup.add(
          InlineKeyboardButton(text=ch_info["name"], url=ch_info["url"])
      )
  markup.add(
      InlineKeyboardButton(
          text="🔄 Check Joined / Verify", callback_data="verify_join"
      )
  )
  try:
    if message_id:
      bot.edit_message_text(
          text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown"
      )
    else:
      bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")
  except Exception:
    pass


def show_main_menu(chat_id, user_name):
  user_data = get_user_data(chat_id)
  panel_unlocked = int(user_data.get("panel_unlocked", 0))

  markup = InlineKeyboardMarkup(row_width=1)
  
  if panel_unlocked == 1:
    text = (
        f"✅ **Welcome back to GBX Pannel Bot, {user_name}!**\n\n"
        "🎉 Aapka Web Panel pehle se **Unlocked** hai! Niche diye gaye button se apna panel open karein 👇"
    )
    markup.add(
        InlineKeyboardButton(
            text="🌐 Open Web Mini App Panel",
            web_app=WebAppInfo(url=MINI_APP_URL),
        )
    )
  else:
    text = (
        f"✅ **Welcome to GBX Pannel Bot, {user_name}!**\n\n"
        "Congratulations! Aapko Web Panel का access lene ke liye niche options mil rahe hain 👇"
    )
    markup.add(
        InlineKeyboardButton(
            text="👥 5 Refer to Unlock Web Panel", callback_data="menu_refer"
        ),
        InlineKeyboardButton(
            text="💳 ₹15 Pay to Unlock Web Panel", callback_data="menu_pay"
        ),
    )

  bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


@bot.message_handler(commands=["start"])
def start_command(message):
  if message.chat.type != "private":
    return
  user_id = message.from_user.id
  user_name = message.from_user.first_name
  user_states.pop(user_id, None)

  user_data = get_user_data(user_id)
  args = message.text.split()
  if len(args) > 1 and user_data.get("referred_by") is None:
    try:
      ref_id = int(args[1])
      if ref_id != user_id:
        update_user_data(user_id, "referred_by", ref_id)
    except Exception:
      pass

  status_map = get_user_status_map(user_id)
  if all(status_map.values()):
    reward_referrer_if_eligible(user_id)
    show_main_menu(message.chat.id, user_name)
  else:
    show_dynamic_force_join(message.chat.id, user_name, status_map)


@bot.message_handler(commands=["admin"])
def admin_command(message):
  if message.chat.id != ADMIN_CHAT_ID:
    return
  markup = InlineKeyboardMarkup()
  markup.add(InlineKeyboardButton(text="📬 Inbox (Broadcast)", callback_data="admin_broadcast_mode"))
  bot.send_message(
      message.chat.id,
      "🛠️ **Admin Control Panel**\n\nSabhi users ko broadcast message bhejne ke liye niche button par click karein:",
      reply_markup=markup,
      parse_mode="Markdown"
  )


@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast_mode")
def admin_broadcast_callback(call):
  if call.from_user.id != ADMIN_CHAT_ID:
    return
  user_states[ADMIN_CHAT_ID] = "waiting_for_broadcast"
  bot.answer_callback_query(call.id, "Broadcast mode active!")
  bot.send_message(
      call.message.chat.id,
      "✍️ **Ab aap jo bhi message (Text, Photo, Video, Sticker, Link, Forward) bhejenge, vah sabhi active users ke paas chala jayega.**\n\n"
      "❌ Radd karne ke liye `/cancel` likhein.",
      parse_mode="Markdown"
  )


@bot.message_handler(commands=["cancel"])
def cancel_command(message):
  if message.chat.id != ADMIN_CHAT_ID:
    return
  user_states.pop(ADMIN_CHAT_ID, None)
  bot.send_message(message.chat.id, "❌ Broadcast mode cancel kar diya gaya hai.")


@bot.callback_query_handler(func=lambda call: call.data == "verify_join")
def handle_verification(call):
  if call.message.chat.type != "private":
    return
  user_id = call.from_user.id
  status_map = get_user_status_map(user_id)
  if all(status_map.values()):
    reward_referrer_if_eligible(user_id)
    bot.answer_callback_query(call.id, "🎉 Success!")
    try:
      bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
      pass
    show_main_menu(call.message.chat.id, call.from_user.first_name)
  else:
    bot.answer_callback_query(
        call.id, "❌ Saare channels join karein!", show_alert=True
    )
    show_dynamic_force_join(
        call.message.chat.id,
        call.from_user.first_name,
        status_map,
        call.message.message_id,
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu_refer")
def handle_refer_menu(call):
  if call.message.chat.type != "private":
    return
  user_id = call.from_user.id
  user_data = get_user_data(user_id)
  refs = int(user_data.get("referral_count", 0))
  points = int(user_data.get("points", 0))
  panel_unlocked = int(user_data.get("panel_unlocked", 0))

  try:
    bot_username = bot.get_me().username
  except Exception:
    bot_username = "gbx_panel_bot"
  ref_link = f"https://t.me/{bot_username}?start={user_id}"

  text = (
      "👥 **Referral Panel:**\n\n"
      f"⭐ Total Points: `{points}`\n"
      f"👥 Total Referrals: `{refs}/{REQUIRED_REFERRALS}`\n\n"
      f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n"
      "ℹ️ *Note: 1 Refer par 3 Points milte hain. Jaise hi aapke 5 refer ho jayenge, aap niche button daba kar panel unlock kar sakte hain!*"
  )

  markup = InlineKeyboardMarkup()
  if panel_unlocked == 1:
    markup.add(
        InlineKeyboardButton(
            text="🌐 Open Web Mini App Panel",
            web_app=WebAppInfo(url=MINI_APP_URL),
        )
    )
  else:
    markup.add(
        InlineKeyboardButton(
            text="🔓 Claim 5 Referrals Unlock", callback_data="claim_referral"
        )
    )
  markup.add(InlineKeyboardButton(text="⬅️ Back", callback_data="back_home"))

  try:
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )
  except Exception:
    pass


@bot.callback_query_handler(func=lambda call: call.data == "claim_referral")
def claim_referral_unlock(call):
  if call.message.chat.type != "private":
    return
  user_id = call.from_user.id
  user_data = get_user_data(user_id)
  refs = int(user_data.get("referral_count", 0))

  if int(user_data.get("panel_unlocked", 0)) == 1:
    bot.answer_callback_query(
        call.id,
        "✅ Aapka Web Panel pehle se unlocked hai!",
        show_alert=True,
    )
    return

  if refs >= REQUIRED_REFERRALS:
    update_user_data(user_id, "panel_unlocked", 1)
    bot.answer_callback_query(
        call.id,
        "🎉 Congratulations! Web Panel successfully unlocked!",
        show_alert=True,
    )
    show_main_menu(call.message.chat.id, call.from_user.first_name)
    try:
      bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
      pass
  else:
    bot.answer_callback_query(
        call.id,
        f"❌ Aapke sirf {refs} refer hue hain. Kam se kam {REQUIRED_REFERRALS} refer karein!",
        show_alert=True,
    )


@bot.callback_query_handler(func=lambda call: call.data == "menu_pay")
def handle_pay_menu(call):
  if call.message.chat.type != "private":
    return
  user_id = call.from_user.id
  user_states[user_id] = None

  upi_url = f"upi://pay?pa={UPI_ID}&pn=GBX_Panel&am={DIRECT_PAY_AMOUNT}&cu=INR"
  qr = qrcode.QRCode(box_size=10, border=2)
  qr.add_data(upi_url)
  qr.make(fit=True)
  img = qr.make_image(fill_color="black", back_color="white")

  buffer = io.BytesIO()
  img.save(buffer, format="PNG")
  buffer.seek(0)

  caption_text = (
      "💳 **Unlock Web Panel via Direct Payment**\n\n"
      f"💰 **Amount:** `₹{DIRECT_PAY_AMOUNT}`\n"
      f"📍 **UPI ID:** `{UPI_ID}`\n\n"
      "📲 **Instructions:**\n"
      "1. Upar QR Code ko scan karke ₹15 ki exact payment karein.\n"
      "2. Payment hone ke baad niche **'📝 Submit UTR'** button par click karke apna 12-digit UTR Number bhejein."
  )
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass

  markup = InlineKeyboardMarkup(row_width=1)
  markup.add(
      InlineKeyboardButton(text="📝 Submit UTR", callback_data="start_utr_input"),
      InlineKeyboardButton(text="⬅️ Back", callback_data="back_home"),
  )

  bot.send_photo(
      call.message.chat.id,
      photo=buffer,
      caption=caption_text,
      reply_markup=markup,
      parse_mode="Markdown",
  )


@bot.callback_query_handler(func=lambda call: call.data == "start_utr_input")
def handle_start_utr(call):
  if call.message.chat.type != "private":
    return
  user_id = call.from_user.id
  user_states[user_id] = "waiting_for_utr"

  bot.answer_callback_query(call.id, "Kripya ab apna 12-digit UTR number type karke bhejein!")
  try:
    bot.send_message(
        call.message.chat.id,
        "✍️ **Ab apna 12-digit UTR Number chat mein type karke bhejein:**",
        parse_mode="Markdown",
    )
  except Exception:
    pass


@bot.callback_query_handler(func=lambda call: call.data == "back_home")
def handle_back_home(call):
  if call.message.chat.type != "private":
    return
  user_id = call.from_user.id
  user_states.pop(user_id, None)
  try:
    bot.delete_message(call.message.chat.id, call.message.message_id)
  except Exception:
    pass
  show_main_menu(call.message.chat.id, call.from_user.first_name)


@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'sticker', 'audio', 'animation'])
def handle_all_messages(message):
  if message.chat.type != "private":
    return
  user_id = message.from_user.id

  # 1. Admin Broadcast Check
  if user_id == ADMIN_CHAT_ID and user_states.get(ADMIN_CHAT_ID) == "waiting_for_broadcast":
    user_states.pop(ADMIN_CHAT_ID, None)
    users = get_all_users()
    success = 0
    fail = 0
    
    status_msg = bot.send_message(ADMIN_CHAT_ID, "🚀 Broadcasting message to all users...")

    for uid in users:
      try:
        bot.copy_message(chat_id=uid, from_chat_id=ADMIN_CHAT_ID, message_id=message.message_id)
        success += 1
        time.sleep(0.05)
      except Exception:
        fail += 1

    bot.edit_message_text(
        f"✅ **Broadcast Completed!**\n\nSuccess: `{success}` users\nFailed: `{fail}` users",
        ADMIN_CHAT_ID,
        status_msg.message_id,
        parse_mode="Markdown"
    )
    return

  # 2. UTR Handling Check
  state = user_states.get(user_id)
  if state == "waiting_for_utr":
    if not message.text or not message.text.strip().isdigit() or len(message.text.strip()) != 12:
      bot.send_message(
          message.chat.id,
          "❌ Kripya valid 12-digit UTR Number hi dalein.",
      )
      return

    text = message.text.strip()
    if is_utr_used(text):
      bot.send_message(
          message.chat.id, "❌ Yeh UTR Number pehle hi use ho chuka hai!"
      )
      user_states.pop(user_id, None)
      return

    add_used_utr(text)
    user_states.pop(user_id, None)

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            text="✅ Accept", callback_data=f"adm_accept:{user_id}:{text}"
        ),
        InlineKeyboardButton(
            text="❌ Reject", callback_data=f"adm_reject:{user_id}:{text}"
        ),
    )

    try:
      bot.send_message(
          ADMIN_CHAT_ID,
          f"📥 **Panel Payment Request!**\nUser ID: `{user_id}`\nAmount: ₹{DIRECT_PAY_AMOUNT}\nUTR: `{text}`",
          reply_markup=markup,
          parse_mode="Markdown",
      )
    except Exception as e:
      print("Admin Send Error:", e)

    bot.send_message(
        message.chat.id,
        "⏳ Payment Verification Pending by Admin. Kripya intezaار karein.",
        parse_mode="Markdown",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def admin_action(call):
  if call.from_user.id != ADMIN_CHAT_ID:
    bot.answer_callback_query(call.id, "Unauthorized!")
    return

  data = call.data.split(":")
  action = data[0]
  target = int(data[1])
  try:
    bot.answer_callback_query(call.id)
  except Exception:
    pass

  if action == "adm_accept":
    update_user_data(target, "panel_unlocked", 1)
    try:
      bot.edit_message_text(
          f"✅ Approved! Web Panel unlocked for User `{target}`.",
          call.message.chat.id,
          call.message.message_id,
      )
    except Exception:
      pass
    try:
      markup = InlineKeyboardMarkup()
      markup.add(
          InlineKeyboardButton(
              text="🌐 Open Web Mini App Panel",
              web_app=WebAppInfo(url=MINI_APP_URL),
          )
      )
      bot.send_message(
          target,
          "🎉 **Payment Verified Successfully!**\nAapka Web Mini App Panel lifetime ke liye unlock kar diya gaya hai 👇",
          reply_markup=markup,
          parse_mode="Markdown",
      )
    except Exception:
      pass
  else:
    try:
      bot.edit_message_text(
          f"❌ Rejected request for User `{target}`.",
          call.message.chat.id,
          call.message.message_id,
      )
    except Exception:
      pass
    try:
      bot.send_message(
          target,
          "❌ Aapki payment request Admin dwara reject kar di gayi hai.",
      )
    except Exception:
      pass


def run_bot():
  while True:
    try:
      bot.remove_webhook()
      time.sleep(1)
      print("Bot Polling Active...")
      bot.infinity_polling(
          timeout=30, long_polling_timeout=30, skip_pending=True
      )
    except Exception as e:
      print("Polling error:", e)
      time.sleep(5)


if __name__ == "__main__":
  t = threading.Thread(target=run_bot, daemon=True)
  t.start()

  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)

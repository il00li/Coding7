import os, json, time, requests
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# 🛠️ إعدادات عامة
TOKEN = os.getenv("8110119856:AAEKyEiIlpHP2e-xOQym0YHkGEBLRgyG_wA")
GEMINI = os.getenv("AIzaSyAEULfP5zi5irv4yRhFugmdsjBoLk7kGsE")
ADMIN_ID = 7251748706  # ← ضع معرفك هنا
VIP_DAYS = 7
REF_ACTIVATE = 10
REF_EXTEND = 2
CHANNELS = ["@yourchannel1", "@yourchannel2"]
DATA_FILE = "users.json"

# 🧱 تحميل وتخزين البيانات
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump({}, f)

def load():
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

def is_subscribed(user_id):
    for ch in CHANNELS:
        url = f"https://api.telegram.org/bot{TOKEN}/getChatMember?chat_id={ch}&user_id={user_id}"
        res = requests.get(url).json()
        s = res.get("result", {}).get("status", "")
        if s not in ["member", "administrator", "creator"]: return False
    return True

def activate_vip(uid):
    data = load()
    expiry = time.time() + VIP_DAYS * 86400
    data[uid]["vip"] = True
    data[uid]["expires"] = expiry
    save(data)

def extend_vip(uid):
    data = load()
    data[uid]["expires"] += VIP_DAYS * 86400
    data[uid]["referrals"] = []
    save(data)

def revoke_vip(uid):
    data = load()
    data[uid]["vip"] = False
    save(data)

def check_referrals(uid):
    data = load()
    user = data[uid]
    count = len(user.get("referrals", []))
    if not user.get("vip") and count >= REF_ACTIVATE:
        activate_vip(uid)
    elif user.get("vip") and count >= REF_EXTEND:
        extend_vip(uid)

def monitor_subscriptions(uid):
    data = load()
    for ref_id in data[uid].get("referrals", []):
        if not is_subscribed(int(ref_id)):
            revoke_vip(uid)
            return

# 📌 عرض لوحة التحكم
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    args = context.args
    ref = args[0] if args else None
    data = load()

    if uid not in data:
        data[uid] = {"vip": False, "expires": 0, "referrals": [], "features": {
            "build": True, "write": True, "test": True, "gemini": True
        }}
        save(data)

    if ref and ref != uid and is_subscribed(update.effective_user.id):
        data.setdefault(ref, {}).setdefault("referrals", []).append(uid)
        check_referrals(ref)
        save(data)

    if not is_subscribed(update.effective_user.id):
        text = "📌 يرجى الاشتراك أولاً:\n" + "\n".join(CHANNELS)
        await update.message.reply_text(text)
        return

    await update.message.reply_text("🎉 أهلاً بك! اختر أحد الخيارات:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔨 بناء بوت", callback_data="build")],
            [InlineKeyboardButton("✍️ كتابة كود", callback_data="write"),
             InlineKeyboardButton("🧪 اختبار كود", callback_data="test")],
            [InlineKeyboardButton("🧠 سؤال Gemini", callback_data="gemini")]
        ])
    )

# 📥 التعامل مع الخيارات
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = str(query.from_user.id)
    data = load()
    action = query.data
    user = data.get(uid, {})
    monitor_subscriptions(uid)

    if not user.get("vip") and not user.get("features", {}).get(action, True):
        await query.edit_message_text("🚫 هذه الميزة مغلقة. احصل على VIP عبر دعوة الآخرين.")
        return

    context.user_data["action"] = action
    await query.edit_message_text(f"✅ أرسل وصف المهمة: {action}")

# 🔄 استقبال النصوص وتنفيذها
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    data = load()
    user = data.get(uid, {})
    monitor_subscriptions(uid)

    if not user.get("vip") and not user.get("features", {}).get(context.user_data.get("action", ""), True):
        await update.message.reply_text("🚫 ليس لديك صلاحية لهذه الميزة.")
        return

    text = update.message.text
    mode = context.user_data.get("action")
    prompt = {"prompt": {"text": f"{mode.upper()} → {text}"}}
    res = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta2/models/gemini-pro:generateText?key={GEMINI}",
        json=prompt
    ).json()
    reply = res.get("candidates", [{}])[0].get("output", "❌ لم أتمكن من الرد.")
    await update.message.reply_text(reply)

# 🛠️ لوحة المدير
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid != ADMIN_ID:
        return
    await update.message.reply_text("⚙️ لوحة المدير:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 فتح الميزات للجميع", callback_data="admin_open")],
            [InlineKeyboardButton("🔴 إغلاق الميزات للجميع", callback_data="admin_close")]
        ])
    )

async def handle_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID: return

    mode = query.data.split("_")[1]
    data = load()
    for uid in data:
        for feat in ["build", "write", "test", "gemini"]:
            data[uid]["features"][feat] = (mode == "open")
    save(data)
    await query.edit_message_text(f"✅ تم {'فتح' if mode == 'open' else 'إغلاق'} جميع الميزات.")

# ▶️ تشغيل البوت
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(CallbackQueryHandler(handle_buttons, pattern="^(build|write|test|gemini)$"))
    app.add_handler(CallbackQueryHandler(handle_admin, pattern="^admin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    print("✅ البوت يعمل الآن...")
    app.run_polling()

if __name__ == "__main__":
    main()
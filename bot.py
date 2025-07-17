import os
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import google.generativeai as genai

# التوكنات والإعدادات
TELEGRAM_TOKEN = "8110119856:AAEKyEiIlpHP2e-xOQym0YHkGEBLRgyG_wA"
GEMINI_API_KEY = "AIzaSyAEULfP5zi5irv4yRhFugmdsjBoLk7kGsE"
ADMIN_ID = 7251748706
BOT_USERNAME = "@SEAK7_BOT"

# تهيئة Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

# إعداد قاعدة البيانات
def init_db():
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, 
                 join_date TEXT, invited_by INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS vip_members
                 (user_id INTEGER PRIMARY KEY, start_date TEXT, 
                 end_date TEXT, invites_required INTEGER DEFAULT 2)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS referrals
                 (referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  referrer_id INTEGER, referee_id INTEGER,
                  date TEXT, is_active INTEGER DEFAULT 1)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS required_channels
                 (channel_id TEXT PRIMARY KEY, channel_username TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS bot_settings
                 (id INTEGER PRIMARY KEY, 
                  free_trial_days INTEGER DEFAULT 7,
                  initial_invites_required INTEGER DEFAULT 10)''')
    
    c.execute("INSERT OR IGNORE INTO bot_settings VALUES (1, 7, 10)")
    conn.commit()
    conn.close()

init_db()

# ========== دوال المساعدة ==========
def get_setting(setting_name):
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute(f"SELECT {setting_name} FROM bot_settings WHERE id = 1")
    result = c.fetchone()[0]
    conn.close()
    return result

def register_user(user, invited_by=0):
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?, ?)",
              (user.id, user.username, user.first_name, datetime.now().isoformat(), invited_by))
    conn.commit()
    conn.close()

def check_vip_status(user_id):
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute("SELECT end_date FROM vip_members WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    
    if result and datetime.fromisoformat(result[0]) > datetime.now():
        return True
    return False

async def check_channel_subscription(user_id, bot):
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute("SELECT channel_id FROM required_channels")
    channels = c.fetchall()
    conn.close()
    
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel[0], user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except:
            return False
    return True

# ========== واجهة المستخدم ==========
def main_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("💻 كتابة كود", callback_data='write_code')],
        [InlineKeyboardButton("🧪 اختبار كود", callback_data='test_code')],
        [InlineKeyboardButton("🤖 توليد مشروع بوت", callback_data='generate_bot')],
        [InlineKeyboardButton("❓ سؤال Gemini", callback_data='ask_gemini')]
    ]
    
    if check_vip_status(user_id):
        keyboard.append([InlineKeyboardButton("👑 عضوية VIP (فعالة)", callback_data='vip_status')])
    else:
        keyboard.append([InlineKeyboardButton("💎 الحصول على VIP", callback_data='get_vip')])
    
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🛠 لوحة المدير", callback_data='admin_panel')])
    
    return InlineKeyboardMarkup(keyboard)

# ========== معالجة الأوامر ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    
    # معالجة روابط الدعوة
    invited_by = 0
    if args and args[0].startswith('ref_'):
        try:
            invited_by = int(args[0][4:])
            register_user(user, invited_by)
            
            # تسجيل الإحالة
            conn = sqlite3.connect('bot_db.sqlite')
            c = conn.cursor()
            c.execute("INSERT INTO referrals (referrer_id, referee_id, date) VALUES (?, ?, ?)",
                      (invited_by, user.id, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            
            # منح VIP إذا حقق الشروط
            check_and_grant_vip(invited_by)
            
        except ValueError:
            pass
    
    register_user(user)
    
    # التحقق من الاشتراك في القنوات
    if not await check_channel_subscription(user.id, context.bot):
        channels = get_required_channels()
        message = "❗ يجب الاشتراك في القنوات التالية لاستخدام البوت:\n"
        for channel in channels:
            message += f"- @{channel[1]}\n"
        message += "\nبعد الاشتراك اضغط /start"
        await update.message.reply_text(message)
        return
    
    welcome_msg = f"""
    🚀 مرحبًا {user.first_name} في بوت المطورين!
    
    اختر أحد الخيارات من القائمة:
    """
    await update.message.reply_text(welcome_msg, reply_markup=main_keyboard(user.id))

# ========== معالجة الأزرار ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if query.data == 'write_code':
        if not check_vip_status(user_id):
            await show_vip_required(query)
            return
        
        await query.edit_message_text("📝 أرسل وصف الكود الذي تريده مع ذكر اللغة:\nمثال: \"دالة بلغة Python لتحويل التاريخ\"")
        context.user_data['awaiting_code'] = True
    
    elif query.data == 'get_vip':
        await show_vip_options(query, user_id)
    
    # ... (بقية معالجات الأزرار)

# ========== دوال VIP ==========
def check_and_grant_vip(user_id):
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    
    # حساب عدد الدعوات النشطة
    c.execute("""SELECT COUNT(*) FROM referrals 
              WHERE referrer_id = ? AND is_active = 1""", (user_id,))
    active_refs = c.fetchone()[0]
    
    # الحصول على الإعدادات
    initial_invites = get_setting('initial_invites_required')
    trial_days = get_setting('free_trial_days')
    
    if active_refs >= initial_invites:
        # منح VIP
        start_date = datetime.now()
        end_date = start_date + timedelta(days=trial_days)
        
        c.execute("""INSERT OR REPLACE INTO vip_members 
                  VALUES (?, ?, ?, ?)""",
                  (user_id, start_date.isoformat(), 
                   end_date.isoformat(), 2))  # 2 دعوات لتمديد العضوية
        
        conn.commit()
    
    conn.close()

async def show_vip_options(query, user_id):
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND is_active = 1", (user_id,))
    ref_count = c.fetchone()[0]
    conn.close()
    
    required = get_setting('initial_invites_required')
    days = get_setting('free_trial_days')
    
    message = f"""
    🎟 نظام العضوية VIP:
    
    - عضوية مجانية {days} أيام عند دعوة {required} مستخدم
    - لديك {ref_count} من أصل {required} دعوة
    - رابط دعوتك: https://t.me/{BOT_USERNAME}?start=ref_{user_id}
    
    بعد تحقيق {required} دعوة، ستحصل على:
    - وصول كامل لجميع ميزات البوت
    - أولوية في الرد على الاستفسارات
    """
    
    keyboard = [
        [InlineKeyboardButton("🔗 مشاركة رابط الدعوة", switch_inline_query=f"انضم عبر رابط الدعوة هذا: https://t.me/{BOT_USERNAME}?start=ref_{user_id}")],
        [InlineKeyboardButton("🔙 رجوع", callback_data='main_menu')]
    ]
    
    await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup(keyboard))

# ========== لوحة المدير ==========
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 الإحصائيات", callback_data='admin_stats')],
        [InlineKeyboardButton("📢 إرسال إشعار", callback_data='admin_broadcast')],
        [InlineKeyboardButton("🛠 إدارة القنوات", callback_data='manage_channels')],
        [InlineKeyboardButton("⚙️ تعديل الإعدادات", callback_data='edit_settings')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='main_menu')]
    ]
    
    await query.edit_message_text("🛠 لوحة تحكم المدير:", reply_markup=InlineKeyboardMarkup(keyboard))

# ========== التشغيل الرئيسي ==========
def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # معالجات الرسائل
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    
    application.run_polling()

if __name__ == "__main__":
    main()
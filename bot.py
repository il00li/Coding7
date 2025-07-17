import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
import google.generativeai as genai
from datetime import datetime
import logging
import sqlite3

# ... (ابقى على جزء التوكنات والإعدادات كما هو)

# أضف هذه المتغيرات في قسم الإعدادات
REQUIRED_CHANNELS = []  # سيتم تعبئتها من قاعدة البيانات
CHANNEL_CHECK_INTERVAL = 86400  # التحقق من الاشتراك كل 24 ساعة

# أضف هذا الجدول في دالة init_db()
def init_db():
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    # ... (ابقى على الجداول الموجودة)
    c.execute('''CREATE TABLE IF NOT EXISTS required_channels
                 (channel_id TEXT PRIMARY KEY, channel_username TEXT, channel_title TEXT)''')
    conn.commit()
    conn.close()
    load_required_channels()  # تحميل القنوات المطلوبة عند التشغيل

def load_required_channels():
    global REQUIRED_CHANNELS
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute("SELECT channel_id, channel_username FROM required_channels")
    REQUIRED_CHANNELS = [{"id": row[0], "username": row[1]} for row in c.fetchall()]
    conn.close()

# أضف هذه الدوال الجديدة لإدارة القنوات
def add_required_channel(channel_id, channel_username, channel_title):
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO required_channels VALUES (?, ?, ?)", 
              (channel_id, channel_username, channel_title))
    conn.commit()
    conn.close()
    load_required_channels()

def remove_required_channel(channel_id):
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute("DELETE FROM required_channels WHERE channel_id = ?", (channel_id,))
    conn.commit()
    conn.close()
    load_required_channels()

def get_required_channels_list():
    conn = sqlite3.connect('bot_db.sqlite')
    c = conn.cursor()
    c.execute("SELECT channel_id, channel_username, channel_title FROM required_channels")
    channels = c.fetchall()
    conn.close()
    return channels

# أضف هذه الدالة للتحقق من اشتراك المستخدم
async def check_user_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    if not REQUIRED_CHANNELS:
        return True
    
    try:
        for channel in REQUIRED_CHANNELS:
            member = await context.bot.get_chat_member(chat_id=channel['id'], user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        return True
    except Exception as e:
        logger.error(f"Error checking subscription: {str(e)}")
        return False

# أضف هذه الدالة لعرض قنوات الاشتراك المطلوبة
def get_subscription_message():
    if not REQUIRED_CHANNELS:
        return ""
    
    message = "❗ يجب الاشتراك في القنوات التالية لاستخدام البوت:\n"
    for channel in REQUIRED_CHANNELS:
        message += f"- @{channel['username']}\n"
    message += "\nبعد الاشتراك اضغط /start"
    return message

# عدل دالة start لتدعم التحقق من الاشتراك
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user)
    
    # التحقق من الاشتراك في القنوات المطلوبة
    is_subscribed = await check_user_subscription(update, context, user.id)
    
    if not is_subscribed:
        await update.message.reply_text(get_subscription_message())
        return
    
    # ... (ابقى على باقي الدالة كما هي)

# أضف دوال التحكم بالقنوات في لوحة المدير
async def manage_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة قناة", callback_data='add_channel')],
        [InlineKeyboardButton("➖ حذف قناة", callback_data='remove_channel')],
        [InlineKeyboardButton("📋 قائمة القنوات", callback_data='list_channels')],
        [InlineKeyboardButton("🔙 رجوع", callback_data='admin_panel')]
    ]
    await update.message.reply_text("📢 إدارة القنوات الإجبارية:", reply_markup=InlineKeyboardMarkup(keyboard))

# أضف معالجات الأزرار الجديدة
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # ... (ابقى على المعالجات الموجودة)
    
    elif query.data == 'manage_channels':
        await manage_channels(query, context)
    
    elif query.data == 'add_channel':
        await query.edit_message_text("أرسل معرف القناة أو الرابط (مثال: @channel_username أو https://t.me/channel_username)")
        context.user_data['awaiting_channel'] = True
    
    elif query.data == 'remove_channel':
        channels = get_required_channels_list()
        if not channels:
            await query.edit_message_text("لا توجد قنوات مطلوبة حالياً.")
            return
        
        keyboard = []
        for channel in channels:
            keyboard.append([InlineKeyboardButton(f"❌ {channel[2]} (@{channel[1]})", 
                                callback_data=f"remove_ch_{channel[0]}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data='manage_channels')])
        
        await query.edit_message_text("اختر القناة التي تريد حذفها:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'list_channels':
        channels = get_required_channels_list()
        if not channels:
            await query.edit_message_text("لا توجد قنوات مطلوبة حالياً.")
            return
        
        message = "📋 قائمة القنوات الإجبارية:\n\n"
        for channel in channels:
            message += f"- {channel[2]} (@{channel[1]})\n"
        
        await query.edit_message_text(message, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data='manage_channels')]
        ]))
    
    elif query.data.startswith('remove_ch_'):
        channel_id = query.data.split('_')[2]
        remove_required_channel(channel_id)
        await query.edit_message_text("✅ تم حذف القناة بنجاح", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 رجوع", callback_data='manage_channels')]
        ]))

# عدل دالة handle_message للتحقق من الاشتراك
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # التحقق من الاشتراك أولاً
    is_subscribed = await check_user_subscription(update, context, user.id)
    if not is_subscribed:
        await update.message.reply_text(get_subscription_message())
        return
    
    # ... (ابقى على باقي الدالة كما هي)

# أضف معالجة الرسائل الجديدة لإضافة القنوات
async def handle_admin_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if context.user_data.get('awaiting_channel'):
        channel_input = update.message.text
        try:
            if channel_input.startswith('https://t.me/'):
                channel_username = channel_input.split('/')[-1]
            elif channel_input.startswith('@'):
                channel_username = channel_input[1:]
            else:
                channel_username = channel_input
            
            # الحصول على معلومات القناة
            chat = await context.bot.get_chat(f"@{channel_username}")
            
            # إضافة القناة إلى القائمة المطلوبة
            add_required_channel(str(chat.id), channel_username, chat.title)
            
            await update.message.reply_text(
                f"✅ تمت إضافة القناة {chat.title} (@{channel_username}) بنجاح",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 رجوع للوحة التحكم", callback_data='admin_panel')]
                ])
            )
            context.user_data.pop('awaiting_channel', None)
            
        except Exception as e:
            await update.message.reply_text(f"❌ حدث خطأ: {str(e)}\nيرجى إرسال معرف القناة مرة أخرى")

# عدل دالة main لإضافة المعالجات الجديدة
def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # ... (ابقى على المعالجات الموجودة)
    
    # أضف معالجات جديدة
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_ID),
        handle_admin_messages
    ))
    
    # ... (ابقى على باقي الدالة)

if __name__ == "__main__":
    main()
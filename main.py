import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import time
import logging
import urllib.parse
import json
import random
from flask import Flask, request, abort
from datetime import datetime

# تهيئة نظام التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = '8324471840:AAHJrXuoAKmb0wmWMle3AnqbPt7Hj6zNQVI'
PIXABAY_API_KEY = '51444506-bffefcaf12816bd85a20222d1'
ADMIN_ID = 6689435577  # معرف المدير
WEBHOOK_URL = 'https://coding7-lpnb.onrender.com/webhook'  # تأكد من تطابق هذا مع عنوان URL الخاص بك

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN)

# قنوات الاشتراك الإجباري
REQUIRED_CHANNELS = ['@iIl337']

# قناة التحميل
UPLOAD_CHANNEL = '@GRABOT7'

# ذاكرة مؤقتة لتخزين نتائج البحث لكل مستخدم
user_data = {}
new_users = set()  # لتتبع المستخدمين الجدد
banned_users = set()  # المستخدمون المحظورون
premium_users = set()  # المستخدمون المميزون
user_referrals = {}  # نظام الدعوة: {user_id: {'invites': count, 'referrer': referrer_id}}
user_channels = {}  # القنوات الخاصة بالمستخدمين: {user_id: channel_username}
referral_links = {}  # روابط الدعوة: {user_id: referral_code}
bot_stats = {  # إحصائيات البوت
    'total_users': 0,
    'total_searches': 0,
    'total_downloads': 0,
    'start_time': datetime.now()
}

# رموز تعبيرية جديدة
NEW_EMOJIS = ['🏖️', '🍓', '🍇', '🍈', '🐢', '🪲', '🍍', '🧃', '🎋', '🧩', '🪖', '🌺', '🪷', '🏵️', '🐌', '🐝', '🦚', '🐦']

def is_valid_url(url):
    """التحقق من صحة عنوان URL"""
    try:
        result = urllib.parse.urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def set_webhook():
    """تعيين ويب هوك للبوت"""
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info("تم تعيين ويب هوك بنجاح")
    except Exception as e:
        logger.error(f"خطأ في تعيين ويب هوك: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    """معالجة التحديثات الواردة من تلجرام"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        abort(403)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # التحقق من وجود رابط دعوة
    if len(message.text.split()) > 1:
        referral_code = message.text.split()[1]
        try:
            referrer_id = int(referral_code)
            if referrer_id != user_id and referrer_id in user_referrals:
                # تخزين معلومات الدعوة مؤقتاً (سيتم التحقق لاحقاً بعد الاشتراك)
                if user_id not in user_referrals:
                    user_referrals[user_id] = {}
                user_referrals[user_id]['referrer'] = referrer_id
                user_referrals[user_id]['referral_verified'] = False  # لم يتم التحقق بعد
        except ValueError:
            pass
    
    # التحقق من الحظر
    if user_id in banned_users:
        bot.send_message(chat_id, "⛔️ حسابك محظور من استخدام البوت.")
        return
    
    # زيادة عدد المستخدمين
    if user_id not in new_users:
        new_users.add(user_id)
        bot_stats['total_users'] += 1
        notify_admin(user_id, message.from_user.username)
    
    # التحقق من الاشتراك في القنوات
    not_subscribed = check_subscription(user_id)
    
    if not_subscribed:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} تحقق من الاشتراك", callback_data="check_subscription"),
            InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} دعوة الأصدقاء", callback_data="invite_friends")
        )
        bot.send_message(chat_id, "🍓 يجب الاشتراك في القنوات التالية اولا:\n" + "\n".join(not_subscribed), reply_markup=markup)
    else:
        # التحقق من الدعوة ومنح النقطة إذا كان المستخدم جاء عن طريق دعوة
        check_and_award_referral(user_id)
        
        # دائماً إرسال رسالة جديدة عند /start
        show_main_menu(chat_id, user_id, new_message=True)

def check_and_award_referral(user_id):
    """التحقق من الدعوة ومنح النقطة للمدعو إذا اكتمل الاشتراك"""
    if user_id in user_referrals and 'referrer' in user_referrals[user_id] and not user_referrals[user_id].get('referral_verified', False):
        referrer_id = user_referrals[user_id]['referrer']
        
        # التحقق من أن المدعو قد اشترك في القنوات الإجبارية
        not_subscribed = check_subscription(user_id)
        if not not_subscribed:  # إذا كان مشتركاً في جميع القنوات
            # منح النقطة للمدعو
            if 'invites' not in user_referrals[referrer_id]:
                user_referrals[referrer_id]['invites'] = 0
            user_referrals[referrer_id]['invites'] += 1
            
            # تحديد أن هذه الدعوة تم التحقق منها
            user_referrals[user_id]['referral_verified'] = True
            
            # إشعار المدعو بعدد دعواته
            try:
                invites_count = user_referrals[referrer_id]['invites']
                bot.send_message(referrer_id, f"🎉 تمت دعوة صديق جديد! لديك الآن {invites_count} دعوات.")
                
                # منح العضوية المميزة إذا وصل عدد الدعوات إلى 10
                if invites_count >= 10 and referrer_id not in premium_users:
                    premium_users.add(referrer_id)
                    bot.send_message(referrer_id, "🎉 مبروك! لقد وصلت إلى 10 دعوات وتم ترقيتك إلى العضوية المميزة!")
            except:
                pass

@bot.message_handler(commands=['admin'])
def admin_panel(message):
    """لوحة تحكم المدير"""
    if message.from_user.id != ADMIN_ID:
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🍇 إدارة المستخدمين", callback_data="admin_users"),
        InlineKeyboardButton("🍈 الإحصائيات", callback_data="admin_stats")
    )
    markup.add(
        InlineKeyboardButton("🐢 إدارة العضويات", callback_data="admin_subscriptions"),
        InlineKeyboardButton("🪲 نقل الأعضاء", callback_data="admin_transfer_members")
    )
    markup.add(
        InlineKeyboardButton("🍍 الإشعارات", callback_data="admin_notifications"),
        InlineKeyboardButton("🧃 رجوع", callback_data="admin_back")
    )
    
    bot.send_message(ADMIN_ID, "👨‍💼 لوحة تحكم المدير:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_users")
def admin_users_panel(call):
    """لوحة إدارة المستخدمين"""
    if call.from_user.id != ADMIN_ID:
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🎋 حظر مستخدم", callback_data="admin_ban_user"),
        InlineKeyboardButton("🧩 فك حظر مستخدم", callback_data="admin_unban_user")
    )
    markup.add(InlineKeyboardButton("🪖 رجوع", callback_data="admin_back"))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="👥 إدارة المستخدمين:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_ban_user")
def admin_ban_user(call):
    """حظر مستخدم"""
    if call.from_user.id != ADMIN_ID:
        return
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="أرسل معرف المستخدم الذي تريد حظره:"
    )
    bot.register_next_step_handler(call.message, process_ban_user)

def process_ban_user(message):
    """معالجة حظر المستخدم"""
    try:
        user_id = int(message.text)
        banned_users.add(user_id)
        bot.send_message(ADMIN_ID, f"✅ تم حظر المستخدم {user_id} بنجاح")
        try:
            bot.send_message(user_id, "⛔️ حسابك محظور من استخدام البوت.")
        except:
            pass
        admin_panel(message)
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ معرف المستخدم غير صالح")
        admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_unban_user")
def admin_unban_user(call):
    """فك حظر مستخدم"""
    if call.from_user.id != ADMIN_ID:
        return
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="أرسل معرف المستخدم الذي تريد فك حظره:"
    )
    bot.register_next_step_handler(call.message, process_unban_user)

def process_unban_user(message):
    """معالجة فك حظر المستخدم"""
    try:
        user_id = int(message.text)
        if user_id in banned_users:
            banned_users.remove(user_id)
            bot.send_message(ADMIN_ID, f"✅ تم فك حظر المستخدم {user_id} بنجاح")
            try:
                bot.send_message(user_id, "✅ تم فك حظر حسابك، يمكنك الآن استخدام البوت مرة أخرى.")
            except:
                pass
        else:
            bot.send_message(ADMIN_ID, f"❌ المستخدم {user_id} غير محظور")
        admin_panel(message)
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ معرف المستخدم غير صالح")
        admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_subscriptions")
def admin_subscriptions_panel(call):
    """لوحة إدارة العضويات"""
    if call.from_user.id != ADMIN_ID:
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🌺 تفعيل العضوية", callback_data="admin_activate_sub"),
        InlineKeyboardButton("🪷 إلغاء العضوية", callback_data="admin_deactivate_sub")
    )
    markup.add(InlineKeyboardButton("🏵️ رجوع", callback_data="admin_back"))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="👑 إدارة العضويات:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_activate_sub")
def admin_activate_sub(call):
    """تفعيل العضوية للمستخدم"""
    if call.from_user.id != ADMIN_ID:
        return
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="أرسل معرف المستخدم الذي تريد تفعيل العضوية له:"
    )
    bot.register_next_step_handler(call.message, process_activate_sub)

def process_activate_sub(message):
    """معالجة تفعيل العضوية"""
    try:
        user_id = int(message.text)
        premium_users.add(user_id)
        bot.send_message(ADMIN_ID, f"✅ تم تفعيل العضوية للمستخدم {user_id} بنجاح")
        try:
            bot.send_message(user_id, "🎉 تم ترقية حسابك إلى العضوية المميزة! يمكنك الآن الاستفادة من جميع ميزات البوت.")
        except:
            pass
        admin_panel(message)
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ معرف المستخدم غير صالح")
        admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_deactivate_sub")
def admin_deactivate_sub(call):
    """إلغاء العضوية للمستخدم"""
    if call.from_user.id != ADMIN_ID:
        return
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="أرسل معرف المستخدم الذي تريد إلغاء العضوية له:"
    )
    bot.register_next_step_handler(call.message, process_deactivate_sub)

def process_deactivate_sub(message):
    """معالجة إلغاء العضوية"""
    try:
        user_id = int(message.text)
        if user_id in premium_users:
            premium_users.remove(user_id)
            bot.send_message(ADMIN_ID, f"✅ تم إلغاء العضوية للمستخدم {user_id} بنجاح")
            try:
                bot.send_message(user_id, "❌ تم إلغاء العضوية المميزة لحسابك.")
            except:
                pass
        else:
            bot.send_message(ADMIN_ID, f"❌ المستخدم {user_id} ليس لديه عضوية مميزة")
        admin_panel(message)
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ معرف المستخدم غير صالح")
        admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_stats")
def admin_stats(call):
    """عرض إحصائيات البوت للمدير"""
    if call.from_user.id != ADMIN_ID:
        return
    
    uptime = datetime.now() - bot_stats['start_time']
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    # حساب عدد المستخدمين الذين لديهم قنوات
    users_with_channels = sum(1 for uid in user_channels if user_channels[uid])
    
    # حساب إجمالي الدعوات
    total_invites = sum([user_referrals[uid].get('invites', 0) for uid in user_referrals if 'invites' in user_referrals[uid]])
    
    stats_text = f"""
📊 إحصائيات البوت:
    
👥 إجمالي المستخدمين: {bot_stats['total_users']}
🔍 إجمالي عمليات البحث: {bot_stats['total_searches']}
💾 إجمالي التحميلات: {bot_stats['total_downloads']}
⏰ وقت التشغيل: {days} أيام, {hours} ساعات, {minutes} دقائق
👑 المستخدمون المميزون: {len(premium_users)}
⛔️ المستخدمون المحظورون: {len(banned_users)}
📨 إجمالي الدعوات: {total_invites}
📢 المستخدمون بقنوات: {users_with_channels}
    """
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=stats_text,
        reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🧃 رجوع", callback_data="admin_back"))
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_transfer_members")
def admin_transfer_members(call):
    """نقل الأعضاء بين القنوات"""
    if call.from_user.id != ADMIN_ID:
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📦 نقل جميع الأعضاء", callback_data="admin_transfer_all"),
        InlineKeyboardButton("🔢 نقل عدد محدد", callback_data="admin_transfer_limit")
    )
    markup.add(InlineKeyboardButton("🧃 رجوع", callback_data="admin_back"))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="📦 نقل الأعضاء بين القنوات:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_transfer_all")
def admin_transfer_all(call):
    """نقل جميع الأعضاء"""
    if call.from_user.id != ADMIN_ID:
        return
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="أرسل معرف القناة المصدر (مثال: @channel_name):"
    )
    bot.register_next_step_handler(call.message, process_transfer_all_step1)

def process_transfer_all_step1(message):
    """الخطوة الأولى في نقل جميع الأعضاء"""
    source_channel = message.text.strip()
    if not source_channel.startswith('@'):
        bot.send_message(ADMIN_ID, "❌ يجب أن يبدأ معرف القناة بـ @")
        admin_panel(message)
        return
    
    # تخزين القناة المصدر مؤقتاً
    user_data[ADMIN_ID] = {'transfer_source': source_channel}
    
    bot.send_message(ADMIN_ID, "أرسل الآن معرف القناة الهدف (مثال: @iIl337):")
    bot.register_next_step_handler(message, process_transfer_all_step2)

def process_transfer_all_step2(message):
    """الخطوة الثانية في نقل جميع الأعضاء"""
    target_channel = message.text.strip()
    if not target_channel.startswith('@'):
        bot.send_message(ADMIN_ID, "❌ يجب أن يبدأ معرف القناة بـ @")
        admin_panel(message)
        return
    
    source_channel = user_data[ADMIN_ID].get('transfer_source', '')
    
    # هنا سيتم تنفيذ عملية النقل الفعلية
    # هذه عملية معقدة وتتطلب صلاحيات إدارية في القنوات
    bot.send_message(ADMIN_ID, f"✅ تم تهيئة نقل جميع الأعضاء من {source_channel} إلى {target_channel}\n\n⚠️ ملاحظة: هذه العملية تتطلب صلاحيات إدارية في القنوات المصدر والهدف.")
    admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_transfer_limit")
def admin_transfer_limit(call):
    """نقل عدد محدد من الأعضاء"""
    if call.from_user.id != ADMIN_ID:
        return
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="أرسل عدد الأعضاء الذي تريد نقله (مثال: 500):"
    )
    bot.register_next_step_handler(call.message, process_transfer_limit_step1)

def process_transfer_limit_step1(message):
    """الخطوة الأولى في نقل عدد محدد من الأعضاء"""
    try:
        limit = int(message.text)
        if limit <= 0:
            bot.send_message(ADMIN_ID, "❌ يجب أن يكون العدد أكبر من الصفر")
            admin_panel(message)
            return
        
        # تخزين الحد مؤقتاً في بيانات المستخدم
        user_data[ADMIN_ID] = {'transfer_limit': limit}
        
        bot.send_message(ADMIN_ID, "أرسل الآن معرف القناة المصدر (مثال: @channel_name):")
        bot.register_next_step_handler(message, process_transfer_limit_step2)
    except ValueError:
        bot.send_message(ADMIN_ID, "❌ يجب إدخال رقم صحيح")
        admin_panel(message)

def process_transfer_limit_step2(message):
    """الخطوة الثانية في نقل عدد محدد من الأعضاء"""
    source_channel = message.text.strip()
    if not source_channel.startswith('@'):
        bot.send_message(ADMIN_ID, "❌ يجب أن يبدأ معرف القناة بـ @")
        admin_panel(message)
        return
    
    # تخزين القناة المصدر مؤقتاً
    user_data[ADMIN_ID]['transfer_source'] = source_channel
    
    bot.send_message(ADMIN_ID, "أرسل الآن معرف القناة الهدف (مثال: @iIl337):")
    bot.register_next_step_handler(message, process_transfer_limit_step3)

def process_transfer_limit_step3(message):
    """الخطوة الثالثة في نقل عدد محدد من الأعضاء"""
    target_channel = message.text.strip()
    if not target_channel.startswith('@'):
        bot.send_message(ADMIN_ID, "❌ يجب أن يبدأ معرف القناة بـ @")
        admin_panel(message)
        return
    
    limit = user_data[ADMIN_ID].get('transfer_limit', 0)
    source_channel = user_data[ADMIN_ID].get('transfer_source', '')
    
    # هنا سيتم تنفيذ عملية النقل الفعلية
    bot.send_message(ADMIN_ID, f"✅ تم تهيئة نقل {limit} عضو من {source_channel} إلى {target_channel}\n\n⚠️ ملاحظة: هذه العملية تتطلب صلاحيات إدارية في القنوات المصدر والهدف.")
    admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_notifications")
def admin_notifications(call):
    """إرسال الإشعارات"""
    if call.from_user.id != ADMIN_ID:
        return
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👥 للمستخدمين فقط", callback_data="admin_notify_users"),
        InlineKeyboardButton("📢 للمستخدمين وقنواتهم", callback_data="admin_notify_all")
    )
    markup.add(InlineKeyboardButton("🧃 رجوع", callback_data="admin_back"))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="📨 إرسال الإشعارات:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data == "admin_notify_users")
def admin_notify_users(call):
    """إرسال إشعار للمستخدمين فقط"""
    if call.from_user.id != ADMIN_ID:
        return
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="أرسل الرسالة التي تريد إشعار جميع المستخدمين بها:"
    )
    bot.register_next_step_handler(call.message, process_notify_users)

def process_notify_users(message):
    """معالجة إشعار المستخدمين"""
    notification_text = message.text
    
    # إرسال الإشعار لجميع المستخدمين
    sent_count = 0
    failed_count = 0
    
    for user_id in new_users:
        if user_id in banned_users:
            continue
        
        try:
            bot.send_message(user_id, f"📨 إشعار من الإدارة:\n\n{notification_text}")
            sent_count += 1
        except Exception as e:
            failed_count += 1
            logger.error(f"فشل في إرسال إشعار للمستخدم {user_id}: {e}")
    
    bot.send_message(ADMIN_ID, f"✅ تم إرسال الإشعار إلى {sent_count} مستخدم\n❌ فشل إرسال الإشعار إلى {failed_count} مستخدم")
    admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_notify_all")
def admin_notify_all(call):
    """إرسال إشعار للمستخدمين وقنواتهم"""
    if call.from_user.id != ADMIN_ID:
        return
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="أرسل الرسالة التي تريد إشعار جميع المستخدمين وقنواتهم بها:"
    )
    bot.register_next_step_handler(call.message, process_notify_all)

def process_notify_all(message):
    """معالجة إشعار المستخدمين وقنواتهم"""
    notification_text = message.text
    
    # إرسال الإشعار لجميع المستخدمين
    user_sent = 0
    user_failed = 0
    channel_sent = 0
    channel_failed = 0
    
    for user_id in new_users:
        if user_id in banned_users:
            continue
        
        # إرسال للمستخدم
        try:
            bot.send_message(user_id, f"📨 إشعار من الإدارة:\n\n{notification_text}")
            user_sent += 1
        except Exception as e:
            user_failed += 1
            logger.error(f"فشل في إرسال إشعار للمستخدم {user_id}: {e}")
        
        # إرسال للقناة إذا كانت موجودة
        if user_id in user_channels and user_channels[user_id]:
            try:
                bot.send_message(user_channels[user_id], f"📨 إشعار من الإدارة:\n\n{notification_text}")
                channel_sent += 1
            except Exception as e:
                channel_failed += 1
                logger.error(f"فشل في إرسال إشعار للقناة {user_channels[user_id]}: {e}")
    
    bot.send_message(ADMIN_ID, f"""
✅ تم إرسال الإشعار إلى:
👥 المستخدمين: {user_sent} نجاح, {user_failed} فشل
📢 القنوات: {channel_sent} نجاح, {channel_failed} فشل
""")
    admin_panel(message)

@bot.callback_query_handler(func=lambda call: call.data == "admin_back")
def admin_back(call):
    """العودة إلى لوحة التحكم الرئيسية"""
    admin_panel(call.message)

def notify_admin(user_id, username):
    """إرسال إشعار للمدير عند انضمام مستخدم جديد"""
    try:
        username = f"@{username}" if username else "بدون معرف"
        user_status = "👑 مميز" if user_id in premium_users else "👤 عادي"
        message = "مستخدم جديد انضم للبوت:\n\n"
        message += f"ID: {user_id}\n"
        message += f"Username: {username}\n"
        message += f"الحالة: {user_status}"
        bot.send_message(ADMIN_ID, message)
    except Exception as e:
        logger.error(f"خطأ في إرسال إشعار للمدير: {e}")

def check_subscription(user_id):
    not_subscribed = []
    for channel in REQUIRED_CHANNELS:
        try:
            # الحصول على حالة المستخدم في القناة
            chat_member = bot.get_chat_member(chat_id=channel, user_id=user_id)
            if chat_member.status not in ['member', 'administrator', 'creator']:
                not_subscribed.append(channel)
        except Exception as e:
            logger.error(f"خطأ في التحقق من الاشتراك: {e}")
            not_subscribed.append(channel)
    return not_subscribed

def show_main_menu(chat_id, user_id, new_message=False):
    # إعادة ضبط بيانات المستخدم
    if user_id not in user_data:
        user_data[user_id] = {}
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} بحث جديد", callback_data="search"))
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} الإعدادات", callback_data="settings"))
    
    welcome_msg = "🎨 PIXA7_BOT\nابحث باللغة الإنجليزية عن الصور والفيديوهات عالية الجودة"
    
    # دائماً إرسال رسالة جديدة
    msg = bot.send_message(chat_id, welcome_msg, reply_markup=markup)
    user_data[user_id]['main_message_id'] = msg.message_id

@bot.callback_query_handler(func=lambda call: call.data == "check_subscription")
def verify_subscription(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    not_subscribed = check_subscription(user_id)
    
    if not_subscribed:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} تحقق من الاشتراك", callback_data="check_subscription"),
            InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} دعوة الأصدقاء", callback_data="invite_friends")
        )
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="يجب الاشتراك في القنوات التالية اولا:\n" + "\n".join(not_subscribed),
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"خطأ في تعديل رسالة الاشتراك: {e}")
    else:
        # التحقق من الدعوة ومنح النقطة إذا كان المستخدم جاء عن طريق دعوة
        check_and_award_referral(user_id)
        
        # إرسال رسالة جديدة بدلاً من تعديل الرسالة الحالية
        bot.delete_message(chat_id, call.message.message_id)
        show_main_menu(chat_id, user_id, new_message=True)

@bot.callback_query_handler(func=lambda call: call.data == "invite_friends")
def invite_friends(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # إنشاء رابط الدعوة
    referral_link = f"https://t.me/PIXA7_BOT?start={user_id}"
    
    # حساب عدد الدعوات
    invites_count = user_referrals.get(user_id, {}).get('invites', 0) if user_id in user_referrals else 0
    
    invite_text = f"""
📨 رابط الدعوة الخاص بك:

{referral_link}

📊 عدد الدعوات: {invites_count} / 10

🎁 عند دعوة 10 أشخاص، ستحصل على العضوية المميزة مجاناً!

⚠️ ملاحظة: سيتم احتساب الدعوة فقط بعد أن يشترك صديقك في القنوات المطلوبة.
    """
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رجوع", callback_data="back_to_subscription_check"))
    
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=invite_text,
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في عرض رابط الدعوة: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_subscription_check")
def back_to_subscription_check(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    not_subscribed = check_subscription(user_id)
    
    if not_subscribed:
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} تحقق من الاشتراك", callback_data="check_subscription"),
            InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} دعوة الأصدقاء", callback_data="invite_friends")
        )
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="يجب الاشتراك في القنوات التالية اولا:\n" + "\n".join(not_subscribed),
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"خطأ في العودة لفحص الاشتراك: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "search")
def show_content_types(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # التحقق من العضوية المميزة
    if user_id not in premium_users:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} ترقية إلى المميز", callback_data="upgrade_premium"))
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رجوع", callback_data="back_to_main"))
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=call.message.message_id,
                text="⛔️ هذه الميزة متاحة فقط للأعضاء المميزين",
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"خطأ في عرض رسالة العضوية: {e}")
        return
    
    # إعادة ضبط بيانات البحث
    if user_id not in user_data:
        user_data[user_id] = {}
    
    # إخفاء الرسالة السابقة
    try:
        bot.answer_callback_query(call.id)
    except:
        pass
    
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} Photos", callback_data="type_photo"),
        InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} Illustrations", callback_data="type_illustration")
    )
    markup.add(
        InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} 3D Models", callback_data="type_3d"),
        InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} Videos", callback_data="type_video")
    )
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} All", callback_data="type_all"))
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رجوع", callback_data="back_to_main"))
    
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="اختر نوع المحتوى:",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في عرض انواع المحتوى: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("type_"))
def request_search_term(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    content_type = call.data.split("_")[1]
    
    # تخزين نوع المحتوى المختار
    if user_id not in user_data:
        user_data[user_id] = {}
    user_data[user_id]['content_type'] = content_type
    
    # طلب كلمة البحث مع زر إلغاء
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} الغاء البحث", callback_data="cancel_search"))
    
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="🔍 ارسل كلمة البحث باللغة الانجليزية:",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في طلب كلمة البحث: {e}")
    
    # حفظ معرف الرسالة للاستخدام لاحقاً
    user_data[user_id]['search_message_id'] = call.message.message_id
    # تسجيل الخطوة التالية
    bot.register_next_step_handler(call.message, process_search_term, user_id)

@bot.callback_query_handler(func=lambda call: call.data == "cancel_search")
def cancel_search(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    show_main_menu(chat_id, user_id, new_message=True)

def process_search_term(message, user_id):
    chat_id = message.chat.id
    search_term = message.text
    
    # زيادة عداد عمليات البحث
    bot_stats['total_searches'] += 1
    
    # حذف رسالة إدخال المستخدم
    try:
        bot.delete_message(chat_id, message.message_id)
    except Exception as e:
        logger.error(f"خطأ في حذف رسالة المستخدم: {e}")
    
    # استرجاع نوع المحتوى
    if user_id not in user_data or 'content_type' not in user_data[user_id]:
        show_main_menu(chat_id, user_id, new_message=True)
        return
    
    content_type = user_data[user_id]['content_type']
    
    # تحديث الرسالة السابقة لإظهار حالة التحميل
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=user_data[user_id]['search_message_id'],
            text="⏳ جاري البحث في قاعدة البيانات...",
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"خطأ في عرض رسالة التحميل: {e}")
    
    # البحث في Pixabay
    results = search_pixabay(search_term, content_type)
    
    if not results or len(results) == 0:
        # عرض خيارات عند عدم وجود نتائج
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} بحث جديد", callback_data="search"))
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} الرئيسية", callback_data="back_to_main"))
        
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=user_data[user_id]['search_message_id'],
                text=f"❌ لم يتم العثور على نتائج لكلمة: {search_term}\nيرجى المحاولة بكلمات أخرى",
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"خطأ في عرض رسالة عدم وجود نتائج: {e}")
        return
    
    # حفظ النتائج
    user_data[user_id]['search_term'] = search_term
    user_data[user_id]['search_results'] = results
    user_data[user_id]['current_index'] = 0
    
    # عرض النتيجة الأولى في نفس رسالة "جاري البحث"
    show_result(chat_id, user_id, message_id=user_data[user_id]['search_message_id'])

def search_pixabay(query, content_type):
    """البحث في Pixabay حسب نوع المحتوى"""
    base_url = "https://pixabay.com/api/"
    params = {
        'key': PIXABAY_API_KEY,
        'q': query,
        'per_page': 30,
        'lang': 'en'
    }
    
    # تحديد نوع المحتوى
    if content_type == 'photo':
        params['image_type'] = 'photo'
    elif content_type == 'illustration':
        params['image_type'] = 'illustration'
    elif content_type == '3d':
        params['image_type'] = 'all'  # البحث في جميع الأنواع مع إضافة 3d للاستعلام
        params['q'] = query + ' 3d'   # إضافة 3d للاستعلام
    elif content_type == 'video':
        params['video_type'] = 'all'
        base_url = "https://pixabay.com/api/videos/"
    else:  # all
        params['image_type'] = 'all'
    
    try:
        logger.info(f"البحث في Pixabay عن: {query} ({content_type})")
        response = requests.get(base_url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # معالجة النتائج بناءً على نوع المحتوى
        if content_type == 'video':
            results = data.get('hits', [])
        else:
            results = data.get('hits', [])
        
        logger.info(f"تم العثور على {len(results)} نتيجة من Pixabay")
        return results
    except Exception as e:
        logger.error(f"خطأ في واجهة Pixabay: {e}")
        return []

def show_result(chat_id, user_id, message_id=None):
    if user_id not in user_data or 'search_results' not in user_data[user_id]:
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=user_data[user_id]['search_message_id'],
                text="انتهت جلسة البحث، ابدأ بحثاً جديداً"
            )
        except:
            pass
        return
    
    results = user_data[user_id]['search_results']
    current_index = user_data[user_id]['current_index']
    search_term = user_data[user_id].get('search_term', '')
    content_type = user_data[user_id].get('content_type', '')
    
    if current_index < 0 or current_index >= len(results):
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=user_data[user_id]['last_message_id'],
                text="نهاية النتائج"
            )
        except:
            pass
        return
    
    item = results[current_index]
    
    # بناء الرسالة
    caption = f"🔍 البحث: {search_term}\n"
    caption += f"📄 النتيجة {current_index+1} من {len(results)}\n"
    
    # بناء أزرار التنقل
    markup = InlineKeyboardMarkup(row_width=3)
    nav_buttons = []
    
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} السابق", callback_data=f"nav_prev"))
    
    nav_buttons.append(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} تحميل", callback_data="download"))
    
    if current_index < len(results) - 1:
        nav_buttons.append(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} التالي", callback_data=f"nav_next"))
    
    markup.row(*nav_buttons)
    markup.row(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} جديد", callback_data="search"))
    markup.row(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} الرئيسية", callback_data="back_to_main"))
    
    # إرسال النتيجة
    try:
        # إذا كانت النتيجة فيديو من Pixabay
        if content_type == 'video' and 'videos' in item:
            video_url = item['videos']['medium']['url']
            
            # التحقق من صحة URL
            if not is_valid_url(video_url):
                raise ValueError("رابط الفيديو غير صالح")
            
            # محاولة تعديل الرسالة الحالية
            if message_id:
                try:
                    # تعديل الوسائط والتسمية التوضيحية معاً
                    bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=message_id,
                        media=telebot.types.InputMediaVideo(
                            media=video_url,
                            caption=caption
                        ),
                        reply_markup=markup
                    )
                    # حفظ معرف الرسالة
                    user_data[user_id]['last_message_id'] = message_id
                    return
                except Exception as e:
                    logger.error(f"فشل في تعديل رسالة الفيديو: {e}")
            
            # إرسال رسالة جديدة إذا لم تنجح عملية التعديل
            msg = bot.send_video(chat_id, video_url, caption=caption, reply_markup=markup)
            user_data[user_id]['last_message_id'] = msg.message_id
        else:
            # الحصول على رابط الصورة من Pixabay
            image_url = item.get('largeImageURL', item.get('webformatURL', ''))
            
            # التحقق من صحة URL
            if not is_valid_url(image_url):
                raise ValueError("رابط الصورة غير صالح")
            
            # محاولة تعديل الرسالة الحالية
            if message_id:
                try:
                    # تعديل الوسائط والتسمية التوضيحية معاً
                    bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=message_id,
                        media=telebot.types.InputMediaPhoto(
                            media=image_url,
                            caption=caption
                        ),
                        reply_markup=markup
                    )
                    # حفظ معرف الرسالة
                    user_data[user_id]['last_message_id'] = message_id
                    return
                except Exception as e:
                    logger.error(f"فشل في تعديل رسالة الصورة: {e}")
            
            # إرسال رسالة جديدة إذا لم تنجح عملية التعديل
            msg = bot.send_photo(chat_id, image_url, caption=caption, reply_markup=markup)
            user_data[user_id]['last_message_id'] = msg.message_id
    except Exception as e:
        logger.error(f"خطأ في عرض النتيجة: {e}")
        # المحاولة مع نتيجة أخرى
        user_data[user_id]['current_index'] += 1
        if user_data[user_id]['current_index'] < len(results):
            show_result(chat_id, user_id, message_id)
        else:
            show_no_results(chat_id, user_id)

def show_no_results(chat_id, user_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} بحث جديد", callback_data="search"))
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} الرئيسية", callback_data="back_to_main"))
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=user_data[user_id]['search_message_id'],
            text="❌ لم يتم العثور على أي نتائج، يرجى المحاولة بكلمات أخرى",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في عرض رسالة عدم وجود نتائج: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith("nav_"))
def navigate_results(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    action = call.data.split("_")[1]
    
    if user_id not in user_data or 'search_results' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "انتهت جلسة البحث، ابدأ بحثاً جديداً")
        return
    
    # تحديث الفهرس
    if action == 'prev':
        user_data[user_id]['current_index'] -= 1
    elif action == 'next':
        user_data[user_id]['current_index'] += 1
    
    # حفظ معرف الرسالة الحالية (التي نضغط عليها)
    user_data[user_id]['last_message_id'] = call.message.message_id
    
    # عرض النتيجة الجديدة في نفس الرسالة
    show_result(chat_id, user_id, message_id=call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "download")
def download_content(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    if user_id not in user_data or 'search_results' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "انتهت جلسة البحث")
        return
    
    current_index = user_data[user_id]['current_index']
    item = user_data[user_id]['search_results'][current_index]
    content_type = user_data[user_id]['content_type']
    
    # زيادة عداد التحميلات
    bot_stats['total_downloads'] += 1
    
    # إرسال المحتوى إلى قناة التحميل
    try:
        # بناء الهاشتاق بناءً على نوع المحتوى
        hashtag = f"#{content_type.capitalize()}"
        username = f"@{call.from_user.username}" if call.from_user.username else "مستخدم"
        caption = f"تم التحميل بواسطة {username}\n{hashtag}\n\n@PIXA7_BOT"
        
        if content_type == 'video' and 'videos' in item:
            video_url = item['videos']['medium']['url']
            bot.send_video(UPLOAD_CHANNEL, video_url, caption=caption)
        else:
            image_url = item.get('largeImageURL', item.get('webformatURL', ''))
            bot.send_photo(UPLOAD_CHANNEL, image_url, caption=caption)
    except Exception as e:
        logger.error(f"خطأ في إرسال المحتوى إلى القناة: {e}")
    
    # إزالة أزرار التنقل
    try:
        bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=None
        )
    except Exception as e:
        logger.error(f"خطأ في ازالة الازرار: {e}")
    
    # إظهار رسالة تأكيد مع زر إرسال إلى قناتي
    markup = InlineKeyboardMarkup()
    if user_id in user_channels and user_channels[user_id]:
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} إرسال إلى قناتي", callback_data="send_to_my_channel"))
    else:
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} تعيين قناتي", callback_data="set_my_channel"))
    
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} بحث جديد", callback_data="search"))
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} الرئيسية", callback_data="back_to_main"))
    
    bot.send_message(chat_id, "✅ تم تحميل المحتوى بنجاح!\nماذا تريد أن تفعل الآن؟", reply_markup=markup)
    bot.answer_callback_query(call.id, "تم التحميل بنجاح! ✅", show_alert=False)

@bot.callback_query_handler(func=lambda call: call.data == "send_to_my_channel")
def send_to_my_channel(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    if user_id not in user_data or 'search_results' not in user_data[user_id]:
        bot.answer_callback_query(call.id, "انتهت جلسة البحث")
        return
    
    if user_id not in user_channels or not user_channels[user_id]:
        bot.answer_callback_query(call.id, "لم تقم بتعيين قناة بعد")
        return
    
    current_index = user_data[user_id]['current_index']
    item = user_data[user_id]['search_results'][current_index]
    content_type = user_data[user_id]['content_type']
    user_channel = user_channels[user_id]
    
    try:
        # بناء الهاشتاق بناءً على نوع المحتوى
        hashtag = f"#{content_type.capitalize()}"
        username = f"@{call.from_user.username}" if call.from_user.username else "مستخدم"
        caption = f"تم التحميل بواسطة {username}\n{hashtag}\n\n@PIXA7_BOT"
        
        if content_type == 'video' and 'videos' in item:
            video_url = item['videos']['medium']['url']
            bot.send_video(user_channel, video_url, caption=caption)
        else:
            image_url = item.get('largeImageURL', item.get('webformatURL', ''))
            bot.send_photo(user_channel, image_url, caption=caption)
        
        bot.answer_callback_query(call.id, f"✅ تم الإرسال إلى قناتك {user_channel}", show_alert=False)
    except Exception as e:
        logger.error(f"خطأ في إرسال المحتوى إلى قناة المستخدم: {e}")
        bot.answer_callback_query(call.id, "❌ فشل في الإرسال إلى قناتك", show_alert=False)

@bot.callback_query_handler(func=lambda call: call.data == "set_my_channel")
def set_my_channel(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.message_id,
        text="📢 أرسل معرف قناتك (يجب أن تبدأ ب @):"
    )
    bot.register_next_step_handler(call.message, process_set_channel)

def process_set_channel(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    channel_username = message.text.strip()
    
    if not channel_username.startswith('@'):
        bot.send_message(chat_id, "❌ يجب أن يبدأ معرف القناة بـ @")
        show_main_menu(chat_id, user_id, new_message=True)
        return
    
    # التحقق من أن البوت هو مدير في القناة
    try:
        chat_member = bot.get_chat_member(chat_id=channel_username, user_id=bot.get_me().id)
        if chat_member.status not in ['administrator', 'creator']:
            bot.send_message(chat_id, "❌ يجب أن أكون مسؤولاً في القناة لأتمكن من النشر فيها")
            show_main_menu(chat_id, user_id, new_message=True)
            return
    except Exception as e:
        logger.error(f"خطأ في التحقق من صلاحية البوت في القناة: {e}")
        bot.send_message(chat_id, "❌ لا يمكنني الوصول إلى القناة، تأكد من أني مسؤول فيها")
        show_main_menu(chat_id, user_id, new_message=True)
        return
    
    # حفظ القناة
    user_channels[user_id] = channel_username
    bot.send_message(chat_id, f"✅ تم تعيين قناتك بنجاح: {channel_username}")
    show_main_menu(chat_id, user_id, new_message=True)

@bot.callback_query_handler(func=lambda call: call.data == "settings")
def show_settings(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # حساب عدد الدعوات
    invites_count = user_referrals.get(user_id, {}).get('invites', 0) if user_id in user_referrals else 0
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} إحصائيات", callback_data="user_stats"))
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} عن المطور", callback_data="about_dev"))
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رابط الدعوة", callback_data="referral_link"))
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} ملحقات مجانية", url=f"https://t.me/{UPLOAD_CHANNEL[1:]}"))
    
    # زر تعيين القناة أو عرض القناة الحالية
    if user_id in user_channels and user_channels[user_id]:
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} قناتي: {user_channels[user_id]}", callback_data="change_my_channel"))
    else:
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} تعيين قناتي", callback_data="set_my_channel"))
    
    if user_id not in premium_users:
        markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} ترقية إلى المميز", callback_data="upgrade_premium"))
    
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رجوع", callback_data="back_to_main"))
    
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="⚙️ إعدادات البوت:",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في عرض الإعدادات: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "change_my_channel")
def change_my_channel(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.message_id,
        text="📢 أرسل معرف قناتك الجديدة (يجب أن تبدأ ب @):"
    )
    bot.register_next_step_handler(call.message, process_set_channel)

@bot.callback_query_handler(func=lambda call: call.data == "user_stats")
def show_user_stats(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # حساب عدد الدعوات
    invites_count = user_referrals.get(user_id, {}).get('invites', 0) if user_id in user_referrals else 0
    
    stats_text = f"""
📊 إحصائياتك الشخصية:

🔍 عمليات البحث: {user_data.get(user_id, {}).get('search_count', 0)}
💾 التحميلات: {user_data.get(user_id, {}).get('download_count', 0)}
📨 عدد الدعوات: {invites_count}
👑 حالة العضوية: {'مميز' if user_id in premium_users else 'عادي'}
📢 قناتك: {user_channels.get(user_id, 'لم يتم تعيينها بعد')}
    """
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رجوع", callback_data="settings"))
    
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=stats_text,
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في عرض إحصائيات المستخدم: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "referral_link")
def show_referral_link(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # إنشاء رابط الدعوة
    referral_link = f"https://t.me/PIXA7_BOT?start={user_id}"
    
    # حساب عدد الدعوات
    invites_count = user_referrals.get(user_id, {}).get('invites', 0) if user_id in user_referrals else 0
    
    referral_text = f"""
📨 رابط الدعوة الخاص بك:

{referral_link}

📊 عدد الدعوات: {invites_count} / 10

🎁 عند دعوة 10 أشخاص، ستحصل على العضوية المميزة مجاناً!
    """
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رجوع", callback_data="settings"))
    
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text=referral_text,
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في عرض رابط الدعوة: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "upgrade_premium")
def upgrade_premium(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رجوع", callback_data="settings"))
    
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=call.message.message_id,
            text="👑 لترقية حسابك إلى العضوية المميزة، يرجى التواصل مع المدير @OlIiIl7",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في عرض ترقية العضوية: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "about_dev")
def show_dev_info(call):
    dev_info = """
👤 عن المطور @OlIiIl7
مطور مبتدئ في عالم بوتات تيليجرام، بدأ رحلته بشغف كبير لتعلم البرمجة وصناعة أدوات ذكية تساعد المستخدمين وتضيف قيمة للمجتمعات الرقمية. يسعى لتطوير مهاراته يومًا بعد يوم من خلال التجربة، التعلم، والمشاركة في مشاريع بسيطة لكنها فعالة.

📢 القنوات المرتبطة:
@iIl337 - @GRABOT7

📞 للتواصل:
تابع الحساب @OlIiIl7
    """
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"{random.choice(NEW_EMOJIS)} رجوع", callback_data="settings"))
    
    try:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=dev_info,
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"خطأ في عرض معلومات المطور: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def return_to_main(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    # حذف الرسالة الحالية وإرسال رسالة جديدة
    bot.delete_message(chat_id, call.message.message_id)
    show_main_menu(chat_id, user_id, new_message=True)

if __name__ == '__main__':
    logger.info("بدء تشغيل البوت...")
    set_webhook()
    app.run(host='0.0.0.0', port=10000)

import logging
import os
from datetime import datetime, timedelta
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from pymongo import MongoClient

# --- إعدادات البوت والاتصال بقاعدة البيانات ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))  # تأكد أنه int
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
PORT = int(os.environ.get("PORT", "8080")) # Render provides PORT env var

# إعدادات الـ logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# الاتصال بـ MongoDB
try:
    client = MongoClient(MONGO_URI)
    db = client.telegram_bot  # اسم قاعدة البيانات
    users_collection = db.users
    settings_collection = db.settings  # لإعدادات البوت والقنوات الإجبارية
    services_collection = db.services  # لإعدادات الخدمات
    logger.info("Connected to MongoDB successfully.")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {e}")
    exit(1)

# التأكد من وجود إعدادات البوت الأولية
if not settings_collection.find_one({"_id": "bot_settings"}):
    settings_collection.insert_one(
        {
            "_id": "bot_settings",
            "vip_enabled": True,
            "required_channels": [],  # قائمة بمعرفات القنوات
        }
    )
    logger.info("Initial bot settings created in DB.")

# التأكد من وجود بعض الخدمات الافتراضية
if not services_collection.find_one({"_id": "service_1"}):
    services_collection.insert_many(
        [
            {"_id": "service_1", "name": "خدمة البحث", "is_vip": False},
            {"_id": "service_2", "name": "خدمة التحويل", "is_vip": True},
            {"_id": "service_3", "name": "خدمة الصور", "is_vip": True},
        ]
    )
    logger.info("Initial services created in DB.")


# --- وظائف مساعدة للمدير ---
def restricted_to_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("عذراً، هذا الأمر متاح للمدير فقط.")
            elif update.callback_query:
                await update.callback_query.answer("عذراً، هذا الأمر متاح للمدير فقط.", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


async def is_user_subscribed_to_channels(user_id: int, bot) -> tuple[bool, str | None]:
    settings = settings_collection.find_one({"_id": "bot_settings"})
    required_channels = settings.get("required_channels", [])

    if not required_channels:
        return True, None

    not_subscribed_channels_links = []
    for channel_id in required_channels:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                channel_info = await bot.get_chat(chat_id=channel_id)
                # Use invite link if available, otherwise just channel username
                if channel_info.invite_link:
                    not_subscribed_channels_links.append(f"[{channel_info.title or 'قناة غير معروفة'}]({channel_info.invite_link})")
                elif channel_info.username:
                     not_subscribed_channels_links.append(f"[{channel_info.title or 'قناة غير معروفة'}](https://t.me/{channel_info.username})")
                else:
                    not_subscribed_channels_links.append(f"*{channel_info.title or 'قناة غير معروفة'}*") # Fallback to just title if no link/username
        except Exception as e:
            logger.warning(f"Could not check channel {channel_id} for user {user_id}: {e}")
            # في حال حدوث خطأ، نفترض أن المستخدم ليس مشتركًا لتجنب تجاوز القناة
            # يمكن أن يحدث هذا إذا كان البوت ليس في القناة أو المعرف خاطئ
            not_subscribed_channels_links.append(f"قناة بمعرف `{channel_id}` (غير معروفة/خطأ)")


    if not_subscribed_channels_links:
        message_text = "الرجاء **الاشتراك** في القنوات التالية قبل استخدام البوت:\n\n"
        message_text += "\n".join(not_subscribed_channels_links)
        return False, message_text
    return True, None


async def check_subscription_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_subscribed, message = await is_user_subscribed_to_channels(user_id, context.bot)

    if not is_subscribed:
        if update.message:
            await update.message.reply_text(
                message, parse_mode="Markdown", disable_web_page_preview=True
            )
        elif update.callback_query:
            await update.callback_query.message.reply_text(
                message, parse_mode="Markdown", disable_web_page_preview=True
            )
            await update.callback_query.answer()
        return False
    return True


# --- وظائف واجهة المستخدم ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # هذا الشرط يعالج حالة /start إذا كان هناك payload (مثل دعوة)
    if context.args and context.args[0].startswith("invite_"):
        await handle_invited_start(update, context)
        return

    # استمر في فحص الاشتراك للقنوات الإجبارية
    if not await check_subscription_middleware(update, context):
        return

    user_id = update.effective_user.id
    user_data = users_collection.find_one({"_id": user_id})

    if not user_data:
        users_collection.insert_one(
            {
                "_id": user_id,
                "vip_end_date": None,
                "invited_users_count": 0,
                "last_invite_reset": datetime.now(),
                "invited_by_users": [] # To store IDs of users invited by this user
            }
        )
        logger.info(f"New user {user_id} added to DB.")

    keyboard = [
        [
            InlineKeyboardButton("خدمة البحث", callback_data="service_1"),
            InlineKeyboardButton("خدمة التحويل", callback_data="service_2"),
        ],
        [InlineKeyboardButton("خدمة الصور", callback_data="service_3")],
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("لوحة تحكم المدير ⚙️", callback_data="admin_panel")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("أهلاً بك! اختر خدمة:", reply_markup=reply_markup)


async def handle_service_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_subscription_middleware(update, context):
        return

    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    service_id = query.data

    service = services_collection.find_one({"_id": service_id})
    if not service:
        await query.edit_message_text("عذراً، الخدمة غير موجودة.")
        return

    settings = settings_collection.find_one({"_id": "bot_settings"})
    vip_enabled = settings.get("vip_enabled", True)

    if service["is_vip"] and vip_enabled:
        user_data = users_collection.find_one({"_id": user_id})
        is_vip_user = (
            user_data and user_data.get("vip_end_date") and user_data["vip_end_date"] > datetime.now()
        )

        if not is_vip_user:
            keyboard = [
                [InlineKeyboardButton("اشترك الآن في VIP 👑", callback_data="show_vip_options")],
                [
                    InlineKeyboardButton(
                        "ادعُ 10 أشخاص لأسبوع مجاني 🎁", callback_data="invite_for_vip"
                    )
                ],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"عذراً، خدمة '{service['name']}' هي خدمة VIP.\n\n"
                "للوصول إليها، يرجى الاشتراك أو دعوة أصدقائك.",
                reply_markup=reply_markup,
            )
            return

    # إذا كانت الخدمة مجانية أو المستخدم VIP
    await query.edit_message_text(f"تم تفعيل خدمة: *{service['name']}*. يمكنك الآن استخدامها!", parse_mode="Markdown")
    # هنا يمكنك إضافة منطق الخدمة الفعلي


async def show_vip_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("باقة أسبوعية", callback_data="vip_package_weekly")],
        [InlineKeyboardButton("باقة 15 يوم", callback_data="vip_package_15days")],
        [InlineKeyboardButton("باقة شهرية", callback_data="vip_package_monthly")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "اختر باقة VIP التي تناسبك:\n\n"
        "عند اختيار الباقة، سيتم إرسال رسالة للمدير لتفعيل اشتراكك.",
        reply_markup=reply_markup,
    )


async def handle_vip_package_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    package_data = query.data.replace("vip_package_", "")

    package_names = {
        "weekly": "أسبوعية",
        "15days": "15 يوم",
        "monthly": "شهرية",
    }
    package_name = package_names.get(package_data, "غير معروفة")

    admin_message = (
        f"طلب اشتراك VIP جديد:\n\n"
        f"المستخدم: [{user.full_name}](tg://user?id={user.id})\n"
        f"معرف المستخدم: `{user.id}`\n"
        f"الباقة المختارة: *{package_name}*\n\n"
        f"يرجى التواصل مع المستخدم لتفعيل الاشتراك."
    )
    await context.bot.send_message(
        chat_id=ADMIN_ID, text=admin_message, parse_mode="Markdown"
    )

    await query.edit_message_text(
        f"شكراً لك! لقد تم إرسال طلب الاشتراك بالباقة الـ *{package_name}* إلى المدير.\n"
        "سيتواصل معك المدير قريباً لتفعيل اشتراكك.",
        parse_mode="Markdown",
    )


async def invite_for_vip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_data = users_collection.find_one({"_id": user_id})

    # Generate an invite link
    invite_link = f"https://t.me/{context.bot.username}?start=invite_{user_id}"

    current_invited = user_data.get("invited_users_count", 0)
    remaining_invites = max(0, 10 - current_invited)

    await query.edit_message_text(
        f"للحصول على اشتراك VIP مجاني لمدة أسبوع، قم بدعوة 10 أشخاص.\n\n"
        f"عدد المدعوين الحالي: *{current_invited}*\n"
        f"المتبقي: *{remaining_invites}*\n\n"
        "شارك هذا الرابط مع أصدقائك:\n"
        f"`{invite_link}`\n\n"
        "عندما ينضم 10 أشخاص عبر رابطك، سيتم تفعيل اشتراكك تلقائياً.",
        parse_mode="Markdown",
    )


async def handle_invited_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # هذا الجزء سيتم استدعاؤه فقط إذا كان هناك payload "invite_"
    user_id = update.effective_user.id
    payload = context.args[0] if context.args else None

    if payload and payload.startswith("invite_"):
        inviter_id = int(payload.split("_")[1])

        # If user is trying to invite themselves or it's an existing user who just clicked an invite link
        if inviter_id == user_id:
            await update.message.reply_text("لا يمكنك دعوة نفسك! 😂")
            await start(update, context) # Show main menu for self-inviters
            return

        inviter_data = users_collection.find_one({"_id": inviter_id})
        user_data = users_collection.find_one({"_id": user_id})

        if not user_data: # New user
            users_collection.insert_one(
                {
                    "_id": user_id,
                    "vip_end_date": None,
                    "invited_users_count": 0,
                    "last_invite_reset": datetime.now(),
                    "invited_by_users": []
                }
            )
            user_data = users_collection.find_one({"_id": user_id}) # Refresh data

        # Check if this user has already been invited by this inviter to avoid double counting
        if inviter_id in user_data.get("invited_by_users", []):
            logger.info(f"User {user_id} already counted as invited by {inviter_id}.")
            await update.message.reply_text("مرحباً بك مجدداً!")
            await start(update, context) # Show main menu for repeat invited users
            return

        if inviter_data:
            # Add this new user's ID to the inviter's invited_by_users list (optional, for tracking)
            users_collection.update_one(
                {"_id": inviter_id},
                {"$addToSet": {"invited_by_users": user_id}}, # Add invited user ID to a set
            )
            
            users_collection.update_one(
                {"_id": inviter_id},
                {"$inc": {"invited_users_count": 1}},
            )
            updated_inviter_data = users_collection.find_one({"_id": inviter_id})
            current_invited = updated_inviter_data.get("invited_users_count", 0)

            if current_invited >= 10:
                # Activate VIP for the inviter
                vip_end_date = datetime.now() + timedelta(weeks=1)
                users_collection.update_one(
                    {"_id": inviter_id},
                    {"$set": {"vip_end_date": vip_end_date, "invited_users_count": 0, "invited_by_users": []}}, # Reset count and list after activation
                )
                await context.bot.send_message(
                    chat_id=inviter_id,
                    text="تهانينا! لقد دعوت 10 أشخاص، وتم تفعيل اشتراك VIP لك لمدة أسبوع! 🎉",
                )
                logger.info(f"User {inviter_id} got 1 week VIP via invites.")
            else:
                await context.bot.send_message(
                    chat_id=inviter_id,
                    text=f"لقد انضم شخص جديد عبر رابطك! لديك الآن *{current_invited}/10* مدعوين.",
                    parse_mode="Markdown"
                )
            
            await update.message.reply_text(f"مرحباً بك في البوت! لقد انضممت عبر رابط دعوة.")
            await start(update, context) # Show main menu for the invited user
            return
    
    # If no invite payload or invalid inviter, proceed to regular start
    await start(update, context)


# --- وظائف لوحة تحكم المدير ---
@restricted_to_admin
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query:
        await query.answer()
        message = query.message
    else:
        message = update.message

    settings = settings_collection.find_one({"_id": "bot_settings"})
    vip_status = "مفعلة ✅" if settings.get("vip_enabled", True) else "معطلة ❌"

    keyboard = [
        [
            InlineKeyboardButton(f"حالة VIP: {vip_status}", callback_data="toggle_vip_status"),
        ],
        [
            InlineKeyboardButton("إدارة الخدمات (VIP/مجاني)", callback_data="manage_services"),
        ],
        [
            InlineKeyboardButton("إدارة قنوات الاشتراك الإجباري", callback_data="manage_required_channels"),
        ],
        [
            InlineKeyboardButton("رجوع للقائمة الرئيسية", callback_data="start_menu"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.edit_text("مرحباً بك في لوحة تحكم المدير:", reply_markup=reply_markup)


@restricted_to_admin
async def toggle_vip_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    settings = settings_collection.find_one({"_id": "bot_settings"})
    current_status = settings.get("vip_enabled", True)
    new_status = not current_status
    settings_collection.update_one({"_id": "bot_settings"}, {"$set": {"vip_enabled": new_status}})

    status_text = "تم تفعيل ميزة VIP. جميع الخدمات المدفوعة أصبحت حصرية." if new_status else "تم تعطيل ميزة VIP. جميع الخدمات أصبحت مجانية."
    await query.edit_message_text(
        status_text,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("العودة للوحة المدير", callback_data="admin_panel")]]
        ),
    )


@restricted_to_admin
async def manage_services(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    services = list(services_collection.find({}))
    keyboard = []
    for service in services:
        status = "VIP 👑" if service.get("is_vip", False) else "مجاني ✅"
        keyboard.append(
            [InlineKeyboardButton(f"{service['name']} ({status})", callback_data=f"toggle_service_vip_{service['_id']}")]
        )
    keyboard.append([InlineKeyboardButton("العودة للوحة المدير", callback_data="admin_panel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("إدارة الخدمات:\nاختر خدمة لتغيير حالتها:", reply_markup=reply_markup)


@restricted_to_admin
async def toggle_service_vip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    service_id = query.data.replace("toggle_service_vip_", "")

    service = services_collection.find_one({"_id": service_id})
    if service:
        new_status = not service.get("is_vip", False)
        services_collection.update_one({"_id": service_id}, {"$set": {"is_vip": new_status}})
        status_text = "VIP 👑" if new_status else "مجاني ✅"
        await query.edit_message_text(
            f"تم تغيير حالة خدمة '{service['name']}' إلى: {status_text}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("العودة لإدارة الخدمات", callback_data="manage_services")]]
            ),
        )
    else:
        await query.edit_message_text("عذراً، الخدمة غير موجودة.")


@restricted_to_admin
async def manage_required_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    settings = settings_collection.find_one({"_id": "bot_settings"})
    required_channels = settings.get("required_channels", [])

    channels_list_text = "قنوات الاشتراك الإجباري:\n"
    if required_channels:
        for i, channel_id in enumerate(required_channels):
            try:
                chat = await context.bot.get_chat(chat_id=channel_id)
                channels_list_text += f"{i+1}. {chat.title} (`{channel_id}`)\n"
            except Exception:
                channels_list_text += f"{i+1}. قناة غير معروفة (`{channel_id}`)\n"
    else:
        channels_list_text += "لا توجد قنوات اشتراك إجباري حالياً."

    keyboard = [
        [InlineKeyboardButton("إضافة قناة", callback_data="add_channel")],
        [InlineKeyboardButton("حذف قناة", callback_data="remove_channel")],
        [InlineKeyboardButton("العودة للوحة المدير", callback_data="admin_panel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"{channels_list_text}\n\nاختر إجراء:", reply_markup=reply_markup
    )
    context.user_data["admin_state"] = None # Reset admin state


@restricted_to_admin
async def add_channel_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["admin_state"] = "waiting_for_channel_id_to_add"
    await query.edit_message_text(
        "الرجاء إرسال معرف القناة (Channel ID) أو اسم المستخدم (Username) للقناة التي ترغب في إضافتها. (مثال: `-1001234567890` أو `@channelusername`)\n\n"
        "تأكد أن البوت **مسؤول** في القناة.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("إلغاء", callback_data="manage_required_channels")]]
        )
    )

@restricted_to_admin
async def remove_channel_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    context.user_data["admin_

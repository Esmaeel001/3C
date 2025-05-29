import requests
import html
import os
import queue
import re
import threading
import time
import json
import asyncio
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, MenuButtonCommands, BotCommandScope
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

import config
from db_handler import DBHandler

# تنظیمات لاگ‌گیری
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# متغیر سراسری برای دسترسی به application از بخش‌های مختلف کد
application = None


def convert_markdown_to_html(markdown_text):
    """تبدیل نشانه‌گذاری پایه Markdown به HTML برای تلگرام."""
    # جایگزینی کاراکترهای ویژه HTML
    text = html.escape(markdown_text)

    # جایگزینی بلوک‌های کد
    text = re.sub(r'```([^`]+)```', r'<pre>\1</pre>', text)

    # جایگزینی کد درون‌خطی
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # جایگزینی متن پررنگ
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)

    # جایگزینی متن کج (ایتالیک)
    text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)

    return text


def fetch_and_update_models(context):
    """فهرست مدل‌ها را از API دریافت کرده و پایگاه داده را به‌روزرسانی می‌کند."""
    url = "https://openrouter.ai/api/v1/models"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": config.SITE_URL,
        "X-Title": config.SITE_NAME,
    }

    try:
        # از requests به جای aiohttp استفاده می‌کنیم.
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()

# دریافت دسترسی به پایگاه داده
            db = context.bot_data.get("db")
            if db:
                # ذخیره هر مدل
                saved_count = 0
                for model in data.get("data", []):
                    if db.save_model(model):
                        saved_count += 1

                logger.info(f"{saved_count} مدل از {len(data.get('data', []))} به‌روزرسانی شد")
                return True
            else:
                logger.error("عدم دسترسی به پایگاه داده برای ذخیره مدل‌ها")
        else:
            logger.error(f"خطا در دریافت مدل‌ها: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"خطا در به‌روزرسانی مدل‌ها: {e}")

    return False


def select_translation_model(db):
    """
    انتخاب مدل برای ترجمه بر اساس معیارهای مشخص:
    1. مدل باید رایگان باشد
    2. ترجیحاً نام "Gemini" در عنوان آن باشد
    3. در صورت نبود Gemini، هر مدل رایگان دیگری انتخاب می‌شود

    Args:
        db: شیء پایگاه داده برای دسترسی به مدل‌ها

    Returns:
        str: شناسه مدل برای ترجمه یا None، اگر مدل مناسبی یافت نشود
    """
    try:
        # دریافت تمام مدل‌های رایگان
        free_models = db.get_models(only_free=True)

        if not free_models:
            logger.error("هیچ مدل رایگانی برای ترجمه یافت نشد")
            return None

        # جستجوی مدل Gemini در میان مدل‌های رایگان
        gemini_models = [model for model in free_models
                         if "gemini" in model["id"].lower() or "gemini" in model["name"].lower()]

        if gemini_models:
            # اگر چند مدل Gemini وجود داشته باشد، نسخه‌های جدیدتر ترجیح داده می‌شوند.
            # مرتب‌سازی به صورت نزولی، تا نسخه‌های جدیدتر در ابتدا باشند
            # (مثلاً، gemini-pro-2.0 باید قبل از gemini-pro-1.5 باشد)
            gemini_models.sort(
                key=lambda model: model["id"] + model["name"],
                reverse=True
            )

            logger.info(f"مدل Gemini برای ترجمه انتخاب شد: {gemini_models[0]['id']}")
            return gemini_models[0]["id"]

        # اگر Gemini یافت نشد، اولین مدل رایگان انتخاب می‌شود
        logger.info(f"مدل Gemini یافت نشد، استفاده از: {free_models[0]['id']}")
        return free_models[0]["id"]

    except Exception as e:
        logger.error(f"خطا در انتخاب مدل برای ترجمه: {e}")
        return None


async def translate_model_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ترجمه توضیحات مدل مشخص شده به زبان پارسی."""
    user_id = update.effective_user.id

    # بررسی اینکه آیا کاربر ادمین است
    if str(user_id) not in config.ADMIN_IDS:
        await update.message.reply_text("⚠️ این دستور فقط برای ادمین‌ها قابل دسترسی است.")
        return

    # دریافت شناسه مدل از آرگومان‌های دستور
    args = context.args
    if not args:
        await update.message.reply_text(
            "لطفاً شناسه مدل را برای ترجمه مشخص کنید. به عنوان مثال: /translate_description meta/llama-3-8b-instruct")
        return

    model_id = args[0]

    # دریافت دسترسی به پایگاه داده
    db = context.bot_data.get("db")
    if not db:
        await update.message.reply_text("⚠️ خطا در دسترسی به پایگاه داده.")
        return

    # بررسی وجود مدل
    cursor = db.conn.cursor()
    cursor.execute("SELECT id, description FROM models WHERE id = ?", (model_id,))
    model = cursor.fetchone()

    if not model:
        await update.message.reply_text(f"⚠️ مدل با شناسه '{model_id}' در پایگاه داده یافت نشد.")
        return

    description = model[1]

    if not description:
        await update.message.reply_text(f"⚠️ مدل '{model_id}' توضیحاتی برای ترجمه ندارد.")
        return

    # اطلاع‌رسانی درباره شروع ترجمه
    message = await update.message.reply_text(f"🔄 شروع ترجمه توضیحات مدل '{model_id}'...")

    # انتخاب مدل برای ترجمه
    translation_model = select_translation_model(db)

    if not translation_model:
        await message.edit_text("⚠️ نتوانستیم مدل مناسبی برای ترجمه پیدا کنیم.")
        return

    # درخواست ترجمه از طریق مدل انتخاب‌شده
    try:
        await message.edit_text(f"🔄 در حال ترجمه توضیحات مدل '{model_id}' با استفاده از '{translation_model}'...")

        # تشکیل درخواست ترجمه
        original_prompt = f"""توضیحات زیر مدل هوش مصنوعی را از انگلیسی به پارسی ترجمه کنید. 
فرمت‌بندی و اصطلاحات فنی را حفظ کنید، اما متن را برای کاربران پارسی‌زبان قابل فهم کنید:

{description}"""

        # دریافت ترجمه
        translation = await generate_ai_response(
            original_prompt,
            translation_model,
            stream=False
        )

        # ذخیره ترجمه در پایگاه داده
        if translation:
            db.set_model_description_ru(model_id, translation)
            await message.edit_text(f"✅ ترجمه توضیحات مدل '{model_id}' تکمیل و ذخیره شد.")
        else:
            await message.edit_text(f"⚠️ نتوانستیم ترجمه‌ای برای مدل '{model_id}' دریافت کنیم.")

    except Exception as e:
        logger.error(f"خطا در ترجمه توضیحات مدل: {e}")
        await message.edit_text(f"⚠️ خطا در ترجمه توضیحات مدل: {str(e)}")


async def generate_ai_response(prompt, model_id, stream=True):
    """
    تولید پاسخ از مدل هوش مصنوعی از طریق API OpenRouter.

    Args:
        prompt: درخواست متنی
        model_id: شناسه مدل برای استفاده
        stream: آیا از انتقال جریانی استفاده شود

    Returns:
        پاسخ مدل یا None در صورت خطا
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": config.SITE_URL,
        "X-Title": config.SITE_NAME,
    }

    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": stream
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)

        if response.status_code != 200:
            logger.error(f"خطای OpenRouter API: {response.status_code} - {response.text}")
            return None

        # برای انتقال غیرجریانی، استخراج متن
        if not stream:
            response_data = response.json()

            if (response_data and 'choices' in response_data
                    and len(response_data['choices']) > 0
                    and 'message' in response_data['choices'][0]
                    and 'content' in response_data['choices'][0]['message']):

                return response_data['choices'][0]['message']['content']
            else:
                logger.error("فرمت پاسخ غیرمنتظره از OpenRouter API")
                return None
        else:
            # برای انتقال جریانی (در این تابع استفاده نمی‌شود)
            return None

    except Exception as e:
        logger.error(f"خطا در درخواست به OpenRouter API: {e}")
        return None


async def translate_descriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ترجمه توضیحات مدل‌ها به زبان پارسی با استفاده از API OpenRouter."""
    user_id = update.effective_user.id

    # بررسی اینکه آیا کاربر ادمین است
    if str(user_id) not in config.ADMIN_IDS:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    # دریافت دسترسی به پایگاه داده
    db = context.bot_data.get("db")
    if not db:
        await update.message.reply_text("خطا در دسترسی به پایگاه داده.")
        return

    # بررسی آرگومان‌های دستور
    model_id = None
    if context.args:
        model_id = context.args[0]

    # ارسال پیام درباره شروع به‌روزرسانی
    message = await update.message.reply_text("شروع ترجمه توضیحات مدل‌ها...")

    # دریافت لیست مدل‌ها برای ترجمه
    cursor = db.conn.cursor()

    if model_id:
        # ترجمه مدل خاص
        cursor.execute(
            "SELECT id, description FROM models WHERE id = ?",
            (model_id,)
        )
    else:
        # جستجوی تمام مدل‌ها با rus_description خالی
        cursor.execute(
            "SELECT id, description FROM models WHERE rus_description IS NULL OR rus_description = ''"
        )

    models_to_translate = cursor.fetchall()

    if not models_to_translate:
        await message.edit_text("هیچ مدلی برای ترجمه وجود ندارد.")
        return

    # شمارنده‌ها برای آمار
    total = len(models_to_translate)
    success = 0
    failed = 0

    # دریافت مدل اولیه برای ترجمه
    current_tr_model = select_translation_model(db)

    if not current_tr_model:
        await message.edit_text("⚠️ نتوانستیم مدل مناسبی برای ترجمه پیدا کنیم.")
        return

    # به‌روزرسانی وضعیت
    await message.edit_text(
        f"شروع ترجمه {total} توضیحات مدل.\n"
        f"مدل فعلی برای ترجمه: {current_tr_model}"
    )

    # ترجمه هر توضیح
    for i, model_data in enumerate(models_to_translate):
        current_model_id = model_data[0]
        description = model_data[1]

        if not description:
            logger.warning(f"مدل {current_model_id} فاقد توضیحات است")
            failed += 1
            continue

        # تشکیل درخواست ترجمه
        original_prompt = f"""توضیحات زیر مدل هوش مصنوعی را از انگلیسی به پارسی ترجمه کنید.
فرمت‌بندی و اصطلاحات فنی را حفظ کنید، اما متن را برای کاربران پارسی‌زبان قابل فهم کنید:

{description}"""

        try:
            # تلاش برای دریافت ترجمه
            translated = await generate_ai_response(
                original_prompt,
                current_tr_model,
                stream=False
            )

            if translated:
                logger.info(f"ترجمه برای مدل {current_model_id} دریافت شد: {translated[:50]}...")
                # به‌روزرسانی توضیحات در پایگاه داده
                if db.set_model_description_ru(current_model_id, translated):
                    success += 1
                    logger.info(f"ترجمه برای مدل {current_model_id} با موفقیت ذخیره شد")
                else:
                    failed += 1
                    logger.error(f"نتوانستیم ترجمه را برای مدل {current_model_id} ذخیره کنیم")
            else:
                failed += 1
                logger.error(f"نتوانستیم ترجمه‌ای برای مدل {current_model_id} دریافت کنیم")

                # تلاش برای دریافت مدل بعدی در صورت خطا
                next_tr_model = get_next_free_model(db, current_tr_model)
                if next_tr_model and next_tr_model != current_tr_model:
                    current_tr_model = next_tr_model
                    logger.info(f"مدل برای ترجمه تغییر کرد به: {current_tr_model}")

        except Exception as e:
            logger.error(f"خطا در ترجمه مدل {current_model_id}: {e}")
            failed += 1

        # به‌روزرسانی وضعیت هر 3 مدل یا در مدل آخر
        if (success + failed) % 3 == 0 or (success + failed) == total:
            await message.edit_text(
                f"ترجمه مدل‌ها: {success + failed}/{total}\n"
                f"✅ موفق: {success}\n"
                f"❌ خطاها: {failed}\n"
                f"مدل فعلی برای ترجمه: {current_tr_model}"
            )

        # مکث برای جلوگیری از بارگذاری بیش از حد API
        await asyncio.sleep(2)

    # گزارش نهایی
    await message.edit_text(
        f"ترجمه تکمیل شد!\n"
        f"تعداد کل مدل‌ها: {total}\n"
        f"✅ با موفقیت ترجمه شده: {success}\n"
        f"❌ خطاها: {failed}"
    )


async def translate_all_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    ترجمه توضیحات تمام مدل‌ها به زبان پارسی.
    این یک نام جایگزین برای تابع translate_descriptions است، اما بدون مشخص کردن مدل.
    """
    # بررسی اینکه آیا کاربر ادمین است
    user_id = update.effective_user.id
    if str(user_id) not in config.ADMIN_IDS:
        await update.message.reply_text("⚠️ این دستور فقط برای ادمین‌ها قابل دسترسی است.")
        return

    # فراخوانی تابع اصلی ترجمه بدون مشخص کردن مدل خاص
    await translate_descriptions(update, context)


def get_next_free_model(db, current_model_id):
    """
    دریافت مدل رایگان بعدی پس از مدل فعلی.
    اگر مدل فعلی آخرین باشد یا یافت نشود، اولین مدل رایگان موجود را برمی‌گرداند.
    """
    try:
        cursor = db.conn.cursor()

        # دریافت تمام مدل‌های رایگان
        cursor.execute("""
        SELECT id FROM models 
        WHERE (prompt_price = '0' AND completion_price = '0') 
           OR id LIKE '%:free' 
        ORDER BY id
        """)

        free_models = [row[0] for row in cursor.fetchall()]

        if not free_models:
            logger.error("هیچ مدل رایگانی در پایگاه داده موجود نیست")
            return None

        # اگر مدل فعلی در لیست باشد، مدل بعدی را پیدا می‌کنیم
        if current_model_id in free_models:
            current_index = free_models.index(current_model_id)
            next_index = (current_index + 1) % len(free_models)
            return free_models[next_index]

        # اگر مدل فعلی یافت نشد، اولین مدل را برمی‌گردانیم
        return free_models[0]

    except Exception as e:
        logger.error(f"خطا در دریافت مدل رایگان بعدی: {e}")
        # بازگشت Claude-3 Haiku به عنوان گزینه پیش‌فرض
        return "anthropic/claude-3-haiku:free"


def stream_ai_response(model_id, user_message, update_queue, chat_id, message_id, cancel_event, context):
    """
    تابع برای پردازش جریانی پاسخ از هوش مصنوعی.
    """
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": config.SITE_URL,
        "X-Title": config.SITE_NAME,
    }

    # استفاده از زمینه گفت‌وگو، در صورت ارائه
    messages = context.get("messages", [{"role": "user", "content": user_message}])

    # اگر پیام فعلی در زمینه وجود ندارد، آن را اضافه می‌کنیم
    if not messages or messages[-1]["role"] != "user" or messages[-1]["content"] != user_message:
        messages.append({"role": "user", "content": user_message})

    # تشکیل payload
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": True
    }

    # اندازه‌گیری زمان شروع درخواست
    start_time = time.time()
    # حداکثر زمان انتظار برای پاسخ (5 دقیقه)
    max_wait_time = 300

    # مقداردهی اولیه متغیرها برای ذخیره نتیجه
    full_response = ""
    last_update_time = time.time()

    # برای ردیابی تغییرات در پاسخ
    last_response_txt = ""

    # تابع برای بررسی لغو و ارسال به‌روزرسانی
    def handle_cancellation():
        if cancel_event.is_set():
            logger.info(f"تولید برای chat_id {chat_id} توسط کاربر متوقف شد")
            update_queue.put({
                "chat_id": chat_id,
                "message_id": message_id,
                "text": convert_markdown_to_html(full_response) + "\n\n[تولید توسط کاربر متوقف شد]",
                "is_final": True,
                "was_canceled": True,
                "dialog_id": context.get("current_dialog_id", None),
                "is_reload": context.get("is_reload", False),
                "user_id": context.get("user_id"),
                "model_name": context.get("model_name"),
                "model_id": context.get("model_id"),
                "user_ask": context.get("user_ask"),
                "dialog_number": context.get("dialog_number")
            })
            return True
        return False

    # تابع برای بررسی مهلت زمانی
    def check_timeout():
        current_time = time.time()
        if current_time - start_time > max_wait_time:
            logger.warning(f"مهلت پاسخ مدل ({max_wait_time} ثانیه) برای chat_id {chat_id} превыش کرد")
            update_queue.put({
                "chat_id": chat_id,
                "message_id": message_id,
                "text": convert_markdown_to_html(
                    full_response) + "\n\n[تولید به دلیل اتمام مهلت زمانی (5 دقیقه) متوقف شد]",
                "is_final": True,
                "was_canceled": True,
                "dialog_id": context.get("current_dialog_id", None),
                "is_reload": context.get("is_reload", False),
                "user_id": context.get("user_id"),
                "model_name": context.get("model_name"),
                "model_id": context.get("model_id"),
                "user_ask": context.get("user_ask"),
                "dialog_number": context.get("dialog_number")
            })
            return True
        return False

    try:
        # بررسی لغو قبل از شروع درخواست
        if handle_cancellation():
            return

        # تنظیم مهلت زمانی برای requests
        session = requests.Session()
        response = session.post(url, headers=headers, json=payload, stream=True, timeout=30)

        # بررسی وضعیت پاسخ
        if not response.ok:
            error_msg = f"خطای API: {response.status_code} - {response.text}"
            logger.error(error_msg)
            update_queue.put({
                "chat_id": chat_id,
                "message_id": message_id,
                "text": f"خطایی در درخواست به API رخ داد: {error_msg}",
                "is_final": True,
                "error": True,
                "dialog_id": context.get("current_dialog_id", None),
                "is_reload": context.get("is_reload", False)
            })
            return

        # برای بررسی پاسخ خط به خط
        line_iter = response.iter_lines()

        # بررسی لغو هر 0.1 ثانیه
        while not handle_cancellation() and not check_timeout():
            try:
                # استفاده از poll با مهلت زمانی برای بررسی مکرر لغو
                line_available = False
                line = None

                # تلاش برای دریافت خط بعدی با مهلت زمانی
                try:
                    line = next(line_iter)
                    line_available = True
                except StopIteration:
                    # پایان تکرارگر (پایان پاسخ)
                    break

                # اگر خطی در دسترس باشد، آن را پردازش می‌کنیم
                if line_available and line:
                    # رمزگشایی خط
                    line_text = line.decode('utf-8')

                    # برای اشکال‌زدایی
                    logger.debug(f"خط SSE: {line_text}")

                    # پردازش خطوط SSE
                    if line_text.startswith('data: '):
                        data = line_text[6:]
                        if data == '[DONE]':
                            break

                        try:
                            data_obj = json.loads(data)

                            # بررسی وجود انتخاب در پاسخ
                            if "choices" in data_obj and len(data_obj["choices"]) > 0:
                                choice = data_obj["choices"][0]

                                # بررسی وجود محتوا در انتخاب
                                content_updated = False
                                if "delta" in choice and "content" in choice["delta"] and choice["delta"][
                                    "content"] is not None:
                                    content_chunk = choice["delta"]["content"]
                                    full_response += content_chunk
                                    content_updated = True

                                # به‌روزرسانی پیام فقط در صورت وجود محتوای جدید
                                if content_updated:
                                    # به‌روزرسانی پیام با فاصله زمانی مشخص
                                    current_time = time.time()
                                    if current_time - last_update_time > config.STREAM_UPDATE_INTERVAL:
                                        current_response = convert_markdown_to_html(full_response)

                                        # ارسال به‌روزرسانی فقط اگر متن تغییر کرده باشد
                                        if current_response != last_response_txt:
                                            update_queue.put({
                                                "chat_id": chat_id,
                                                "message_id": message_id,
                                                "text": current_response,
                                                "is_final": False
                                            })
                                            last_response_txt = current_response
                                            last_update_time = current_time

                        except json.JSONDecodeError as e:
                            logger.error(f"خطای رمزگشایی JSON: {e} - {data}")
                else:
                    # اگر خطی وجود ندارد، مکث کوتاهی انجام می‌دهیم و لغو را بررسی می‌کنیم
                    time.sleep(0.1)

            except Exception as e:
                logger.error(f"خطا در پردازش خط پاسخ: {e}")
                # ادامه چرخه، شاید خط بعدی به درستی خوانده شود

        # بستن اتصال
        response.close()

        # بررسی لغو یا مهلت زمانی قبل از ارسال پاسخ نهایی
        if handle_cancellation() or check_timeout():
            return

    except requests.exceptions.Timeout:
        logger.error(f"مهلت زمانی در درخواست به API برای chat_id {chat_id}")
        update_queue.put({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": "سرور پاسخ نمی‌دهد. لطفاً بعداً امتحان کنید.",
            "is_final": True,
            "error": True,
            "dialog_id": context.get("current_dialog_id", None),
            "is_reload": context.get("is_reload", False)
        })
        return
    except Exception as e:
        logger.error(f"خطا در دریافت پاسخ جریانی برای chat_id {chat_id}: {e}")
        update_queue.put({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": f"خطایی رخ داد: {str(e)}",
            "is_final": True,
            "error": True,
            "dialog_id": context.get("current_dialog_id", None),
            "is_reload": context.get("is_reload", False)
        })
        return

    # تبدیل متن پاسخ نهایی برای نمایش صحیح
    formatted_response = convert_markdown_to_html(full_response)

    # بررسی نهایی لغو و مهلت زمانی
    if handle_cancellation() or check_timeout():
        return

    # ارسال به‌روزرسانی نهایی
    if formatted_response != last_response_txt:
        update_queue.put({
            "chat_id": chat_id,
            "message_id": message_id,
            "text": formatted_response,
            "is_final": True,
            "dialog_id": context.get("current_dialog_id", None),  # انتقال شناسه گفت‌وگو
            "is_reload": context.get("is_reload", False),
            "user_id": context.get("user_id"),
            "model_name": context.get("model_name"),
            "model_id": context.get("model_id"),
            "user_ask": context.get("user_ask"),
            "dialog_number": context.get("dialog_number")
        })


async def message_updater(context):
    """وظیفه پس‌زمینه برای به‌روزرسانی پیام‌ها با پاسخ‌های هوش مصنوعی"""
    # برای ذخیره محتوای آخرین پیام هر پیام
    last_message_content = {}

    while True:
        try:
            # بررسی وجود عناصر در صف
            if not context.bot_data["update_queue"].empty():
                # دریافت داده‌ها از صف هم‌زمان
                update_data = context.bot_data["update_queue"].get_nowait()

                chat_id = update_data["chat_id"]
                message_id = update_data["message_id"]
                text = update_data["text"]
                is_final = update_data.get("is_final", False)
                error = update_data.get("error", False)
                was_canceled = update_data.get("was_canceled", False)  # پرچم لغو
                dialog_id = update_data.get("dialog_id", None)

                # ایجاد شناسه یکتا برای پیام
                msg_identifier = f"{chat_id}:{message_id}"

                # بررسی تغییر متن پیام
                current_content = {
                    "text": text,
                    "is_final": is_final
                }

                # اگر محتوا تغییر نکرده باشد، به‌روزرسانی را رد می‌کنیم
                if msg_identifier in last_message_content and not is_final:
                    prev_content = last_message_content[msg_identifier]
                    if prev_content["text"] == text:
                        # آزادسازی وظیفه و رد به‌روزرسانی
                        context.bot_data["update_queue"].task_done()
                        continue

                # ذخیره محتوای جدید
                last_message_content[msg_identifier] = current_content

                # ایجاد صفحه‌کلیدهای مختلف بسته به وضعیت
                if is_final:
                    # برای پیام‌های نهایی، دکمه بارگذاری مجدد اضافه می‌کنیم
                    reply_markup = InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔄 بارگذاری مجدد پاسخ",
                                             callback_data=f"reload_{chat_id}_{message_id}")
                    ]])

                    # برای پیام‌های نهایی، ورودی مربوطه در last_message_content را پاک می‌کنیم
                    if msg_identifier in last_message_content:
                        del last_message_content[msg_identifier]

                    # اگر این پیام نهایی باشد، پاسخ مدل را در پایگاه داده به‌روزرسانی می‌کنیم
                    if dialog_id and "db" in context.bot_data:
                        db = context.bot_data["db"]

                        # بررسی اینکه آیا این یک بارگذاری مجدد است
                        is_reload = update_data.get("is_reload", False)

                        if is_reload:
                            # اگر بارگذاری مجدد باشد، یک رکورد جدید ایجاد می‌کنیم
                            user_id = update_data.get("user_id")
                            dialog_number = update_data.get("dialog_number")
                            model_name = update_data.get("model_name")
                            model_id = update_data.get("model_id")
                            user_ask = update_data.get("user_ask")

                            if user_id and dialog_number and model_name and model_id and user_ask:
                                # ایجاد رکورد جدید با displayed = 1
                                new_dialog_id = db.log_dialog(
                                    id_chat=chat_id,
                                    id_user=user_id,
                                    number_dialog=dialog_number,
                                    model=model_name,
                                    model_id=model_id,
                                    user_ask=user_ask,
                                    model_answer=text,
                                    displayed=1
                                )
                                logger.info(f"رکورد جدید برای پاسخ بارگذاری مجدد ایجاد شد: {new_dialog_id}")

                                # به‌روزرسانی dialog_id فعلی در زمینه کاربر
                                if user_id and hasattr(context, 'dispatcher') and context.dispatcher:
                                    user_data = context.dispatcher.user_data.get(int(user_id), {})
                                    if user_data:
                                        user_data["current_dialog_id"] = new_dialog_id
                                        logger.info(
                                            f"current_dialog_id برای کاربر {user_id} به {new_dialog_id} به‌روزرسانی شد")
                            else:
                                logger.error("داده‌های کافی برای ایجاد رکورد جدید در بارگذاری مجدد وجود ندارد")
                        else:
                            # اگر پاسخ معمولی باشد، رکورد موجود را به‌روزرسانی می‌کنیم
                            db.update_model_answer(dialog_id, text, displayed=1)
                else:
                    # برای پیام‌های ناتمام، دکمه لغو اضافه می‌کنیم
                    reply_markup = InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ توقف تولید محتوا", callback_data="cancel_stream")
                    ]])

                # اگر متن برای یک پیام تلگرام بیش از حد طولانی باشد
                if len(text) > 4096:
                    # اگر پیام نهایی باشد، آن را به بخش‌ها تقسیم می‌کنیم
                    if is_final:
                        chunks = [text[i:i + 4096] for i in range(0, len(text), 4096)]

                        # حذف پیام میانی
                        try:
                            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
                        except Exception as e:
                            logger.error(f"نتوانستیم پیام را حذف کنیم: {e}")

                        # ارسال بخش‌ها به عنوان پیام‌های جداگانه
                        for i, chunk in enumerate(chunks):
                            # اضافه کردن دکمه فقط به آخرین پیام
                            if i == len(chunks) - 1:
                                try:
                                    sent_msg = await context.bot.send_message(
                                        chat_id=chat_id,
                                        text=f"بخش {i + 1}/{len(chunks)}:\n\n{chunk}",
                                        reply_markup=reply_markup,
                                        parse_mode="HTML"  # استفاده از قالب‌بندی HTML
                                    )
                                except Exception as e:
                                    if "Can't parse entities" in str(e):
                                        logger.error(f"خطای قالب‌بندی HTML: {e}")
                                        # پاک کردن متن از تگ‌های HTML
                                        clean_chunk = re.sub(r'<[^>]*>', '', chunk)
                                        sent_msg = await context.bot.send_message(
                                            chat_id=chat_id,
                                            text=f"بخش {i + 1}/{len(chunks)}:\n\n{clean_chunk}\n\n[یادداشت: قالب‌بندی به دلیل خطاهای نشانه‌گذاری حذف شد]",
                                            reply_markup=reply_markup
                                        )
                                    else:
                                        logger.error(f"خطا در ارسال پیام: {e}")
                                        continue

                                # ذخیره شناسه آخرین پیام برای بارگذاری مجدد احتمالی
                                if str(chat_id) in context.bot_data.get("active_streams", {}):
                                    del context.bot_data["active_streams"][str(chat_id)]

                                # ذخیره اطلاعات آخرین پیام برای بارگذاری مجدد
                                if hasattr(context, 'user_data_dict') and int(chat_id) in context.user_data_dict:
                                    user_data = context.user_data_dict[int(chat_id)]
                                    if "last_message" in user_data and user_data["last_message"]["text"]:
                                        user_data["last_message"]["id"] = f"{chat_id}_{sent_msg.message_id}"
                            else:
                                try:
                                    await context.bot.send_message(
                                        chat_id=chat_id,
                                        text=f"بخش {i + 1}/{len(chunks)}:\n\n{chunk}",
                                        parse_mode="HTML"  # استفاده از قالب‌بندی HTML
                                    )
                                except Exception as e:
                                    if "Can't parse entities" in str(e):
                                        logger.error(f"خطای قالب‌بندی HTML: {e}")
                                        # پاک کردن متن از تگ‌های HTML
                                        clean_chunk = re.sub(r'<[^>]*>', '', chunk)
                                        await context.bot.send_message(
                                            chat_id=chat_id,
                                            text=f"بخش {i + 1}/{len(chunks)}:\n\n{clean_chunk}\n\n[یادداشت: قالب‌بندی به دلیل خطاهای نشانه‌گذاری حذف شد]"
                                        )
                                    else:
                                        logger.error(f"خطا در ارسال پیام: {e}")
                                        continue
                    else:
                        # برای پیام ناتمام، فقط اولین بخش را نمایش می‌دهیم
                        text_truncated = text[:4093] + "..."
                        try:
                            await context.bot.edit_message_text(
                                text=text_truncated,
                                chat_id=chat_id,
                                message_id=message_id,
                                reply_markup=reply_markup,
                                parse_mode="HTML"  # استفاده از قالب‌بندی HTML
                            )
                        except Exception as e:
                            if "Can't parse entities" in str(e):
                                logger.error(f"خطای قالب‌بندی HTML: {e}")
                                # پاک کردن متن از تگ‌های HTML
                                clean_text = re.sub(r'<[^>]*>', '', text_truncated)
                                try:
                                    await context.bot.edit_message_text(
                                        text=f"{clean_text}\n\n[یادداشت: قالب‌بندی به دلیل خطاهای نشانه‌گذاری حذف شد]",
                                        chat_id=chat_id,
                                        message_id=message_id,
                                        reply_markup=reply_markup
                                    )
                                except Exception as inner_e:
                                    logger.error(f"نتوانستیم حتی متن پاک‌شده را ارسال کنیم: {inner_e}")
                            elif "Message is not modified" in str(e):
                                # این طبیعی است، فقط نادیده می‌گیریم
                                logger.debug("پیام تغییر نکرده است، به‌روزرسانی را رد می‌کنیم")
                            else:
                                logger.error(f"خطا در به‌روزرسانی پیام: {e}")
                else:
                    # به‌روزرسانی پیام
                    try:
                        await context.bot.edit_message_text(
                            text=text,
                            chat_id=chat_id,
                            message_id=message_id,
                            reply_markup=reply_markup,
                            parse_mode="HTML"  # استفاده از قالب‌بندی HTML
                        )

                        # اگر پیام نهایی باشد
                        if is_final:
                            # حذف از جریان‌های فعال
                            if str(chat_id) in context.bot_data.get("active_streams", {}):
                                del context.bot_data["active_streams"][str(chat_id)]

                            # به‌روزرسانی شناسه آخرین پیام برای بارگذاری مجدد
                            try:
                                # دریافت user_id از update_data در صورت وجود
                                user_id = update_data.get("user_id")

                                # اگر user_id مشخص نشده باشد، تلاش برای یافتن کاربر از طریق chat_id
                                if not user_id and hasattr(context, 'user_data_dict'):
                                    # در PTB v20، زمینه ممکن است شامل user_data_dict برای دسترسی به داده‌های کاربر باشد
                                    if int(chat_id) in context.user_data_dict:
                                        user_data = context.user_data_dict[int(chat_id)]
                                        if "last_message" in user_data and user_data["last_message"]["text"]:
                                            user_data["last_message"]["id"] = f"{chat_id}_{message_id}"
                            except Exception as e:
                                logger.error(f"خطا در به‌روزرسانی شناسه آخرین پیام: {e}")
                    except Exception as e:
                        if "Can't parse entities" in str(e):
                            logger.error(f"خطای قالب‌بندی HTML: {e}")
                            # تلاش برای ارسال پیام بدون قالب‌بندی HTML در صورت خطا
                            try:
                                # پاک کردن متن از تگ‌های HTML
                                clean_text = re.sub(r'<[^>]*>', '', text)
                                await context.bot.edit_message_text(
                                    text=f"{clean_text}\n\n[یادداشت: قالب‌بندی به دلیل خطاهای نشانه‌گذاری حذف شد]",
                                    chat_id=chat_id,
                                    message_id=message_id,
                                    reply_markup=reply_markup
                                )

                                # اگر پیام نهایی باشد، از جریان‌های فعال حذف می‌کنیم
                                if is_final and str(chat_id) in context.bot_data.get("active_streams", {}):
                                    del context.bot_data["active_streams"][str(chat_id)]
                            except Exception as inner_e:
                                logger.error(f"نتوانستیم حتی متن پاک‌شده را ارسال کنیم: {inner_e}")
                        elif "Message is not modified" in str(e):
                            # این طبیعی است، فقط نادیده می‌گیریم
                            logger.debug("پیام تغییر نکرده است، به‌روزرسانی را رد می‌کنیم")
                        else:
                            logger.error(f"خطا در به‌روزرسانی پیام: {e}")

                # علامت‌گذاری وظیفه به عنوان انجام‌شده برای صف هم‌زمان
                context.bot_data["update_queue"].task_done()

        except queue.Empty:
            # اگر صف خالی باشد، ادامه می‌دهیم
            pass
        except Exception as e:
            logger.error(f"خطا در پردازشگر پیام‌ها: {e}")

        # مکث کوتاه برای جلوگیری از بار زیاد روی CPU
        await asyncio.sleep(0.1)


async def process_ai_request(context, chat_id, user_message, is_reload=False):
    """پردازش درخواست به مدل هوش مصنوعی و ارسال پاسخ."""
    if "selected_model" not in context.user_data:
        await context.bot.send_message(
            chat_id=chat_id,
            text="لطفاً ابتدا با استفاده از دستور /select_model یک مدل انتخاب کنید"
        )
        return

    model_id = context.user_data["selected_model"]
    user_id = None

    # دریافت شناسه کاربر
    if hasattr(context, 'user_data_dict') and int(chat_id) in context.user_data_dict:
        user_data = context.user_data_dict[int(chat_id)]
        if 'id' in user_data:
            user_id = user_data['id']

    if not user_id:
        # استفاده از chat_id به عنوان user_id در صورت عدم یافتن
        user_id = chat_id

    # دریافت شماره گفت‌وگوی فعلی
    dialog_number = context.user_data.get("current_dialog", 1)

    # آماده‌سازی زمینه گفت‌وگو
    db = context.bot_data.get("db")
    if db:
        messages, context_usage_percent = prepare_context(db, user_id, dialog_number, model_id, user_message)

        # گرد کردن درصد به عدد صحیح
        context_usage_percent = round(context_usage_percent)

        # اطلاع‌رسانی به کاربر درباره میزان پر شدن زمینه
        if context_usage_percent > 70:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ توجه: زمینه مدل به میزان {context_usage_percent}% پر شده است."
            )
    else:
        # اگر دسترسی به پایگاه داده وجود نداشته باشد، فقط از پیام فعلی استفاده می‌کنیم
        messages = [{"role": "user", "content": user_message}]
        context_usage_percent = 0

    # ارسال نشانگر تایپ
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # پیام اولیه با دکمه لغو
    cancel_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ توقف تولید محتوا", callback_data="cancel_stream")
    ]])

    initial_message = await context.bot.send_message(
        chat_id=chat_id,
        text="در حال تولید پاسخ...",
        reply_markup=cancel_keyboard
    )

    # ذخیره اطلاعات آخرین پیام برای بارگذاری مجدد
    context.user_data["last_message"] = {
        "id": f"{chat_id}_{initial_message.message_id}",
        "text": user_message
    }

    # مقداردهی اولیه صف به‌روزرسانی‌ها، در صورت عدم وجود
    if "update_queue" not in context.bot_data:
        # استفاده از صف هم‌زمان استاندارد
        context.bot_data["update_queue"] = queue.Queue()
        # راه‌اندازی وظیفه پس‌زمینه برای به‌روزرسانی پیام‌ها
        asyncio.create_task(message_updater(context))

    # مقداردهی اولیه دیکشنری جریان‌های فعال، در صورت عدم وجود
    if "active_streams" not in context.bot_data:
        context.bot_data["active_streams"] = {}

    # ایجاد رویداد برای لغو جریان
    cancel_event = threading.Event()
    context.bot_data["active_streams"][str(chat_id)] = cancel_event

    # انتقال شناسه گفت‌وگوی فعلی به زمینه برای تابع جریانی
    thread_context = {
        "is_reload": is_reload,  # پرچم بارگذاری مجدد
        "messages": messages,  # زمینه گفت‌وگو
        "context_usage_percent": context_usage_percent  # درصد پر شدن زمینه
    }

    if "current_dialog_id" in context.user_data:
        thread_context["current_dialog_id"] = context.user_data["current_dialog_id"]

    # افزودن اطلاعات اضافی برای بارگذاری مجدد
    if is_reload and "current_dialog_info" in context.user_data:
        thread_context.update(context.user_data["current_dialog_info"])

    # راه‌اندازی جریان برای پردازش جریانی
    threading.Thread(
        target=stream_ai_response,
        args=(model_id, user_message, context.bot_data["update_queue"], chat_id,
              initial_message.message_id, cancel_event, thread_context)
    ).start()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازشگر پیام‌های متنی."""
    user_message = update.message.text
    user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = user.id

    # ثبت کاربر و پیام او
    db = context.bot_data.get("db")
    if db:
        # ثبت یا به‌روزرسانی کاربر
        db.register_user(
            id_chat=chat_id,
            id_user=user_id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username
        )

        # دریافت یا ایجاد شماره گفت‌وگوی فعلی
        if "current_dialog" not in context.user_data:
            context.user_data["current_dialog"] = db.get_next_dialog_number(user_id)

        # بررسی وجود مدل انتخاب‌شده
        if "selected_model" in context.user_data:
            model_id = context.user_data["selected_model"]

            # بررسی اینکه آیا کاربر اجازه استفاده از این مدل را دارد
            is_admin = str(user_id) in config.ADMIN_IDS

            # بررسی رایگان بودن مدل
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT is_free FROM models WHERE id = ?",
                (model_id,)
            )
            result = cursor.fetchone()

            is_free_model = True  # به طور پیش‌فرض مدل را رایگان در نظر می‌گیریم
            if result is not None:
                is_free_model = bool(result[0])

            # اگر مدل پولی باشد و کاربر ادمین نباشد، خطا اعلام می‌کنیم
            if not is_free_model and not is_admin:
                await update.message.reply_text(
                    "⚠️ شما به این مدل دسترسی ندارید. لطفاً یک مدل رایگان با استفاده از دستور /select_model انتخاب کنید"
                )
                return

            # یافتن نام مدل برای ثبت
            models = await get_available_models(context, user_id)
            model_name = model_id
            for model in models:
                if model["id"] == model_id:
                    model_name = model["name"]
                    break

            # آماده‌سازی زمینه گفت‌وگو برای ارزیابی میزان پر شدن
            messages, context_usage_percent = prepare_context(db, user_id, context.user_data["current_dialog"],
                                                              model_id, user_message)

            # اگر زمینه بیش از 90% پر شده باشد، پیشنهاد شروع گفت‌وگوی جدید می‌دهیم
            if context_usage_percent > 90:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 شروع گفت‌وگوی جدید", callback_data="new_dialog")]
                ])
                await update.message.reply_text(
                    f"⚠️ توجه: زمینه مدل به میزان {round(context_usage_percent)}% پر شده است.\n"
                    f"توصیه می‌شود برای عملکرد بهتر، گفت‌وگوی جدیدی شروع کنید.",
                    reply_markup=keyboard
                )
                # ادامه اجرا - کاربر می‌تواند توصیه را نادیده بگیرد

            # ثبت درخواست کاربر (بدون پاسخ مدل در این مرحله)
            dialog_id = db.log_dialog(
                id_chat=chat_id,
                id_user=user_id,
                number_dialog=context.user_data["current_dialog"],
                model=model_name,
                model_id=model_id,
                user_ask=user_message,
                displayed=1  # درخواست جدید همیشه نمایش داده می‌شود
            )

            # ذخیره شناسه گفت‌وگو برای به‌روزرسانی‌های بعدی
            if dialog_id:
                context.user_data["current_dialog_id"] = dialog_id

                # ذخیره اطلاعات اضافی برای بارگذاری مجدد
                context.user_data["current_dialog_info"] = {
                    "user_id": user_id,
                    "dialog_number": context.user_data["current_dialog"],
                    "model_name": model_name,
                    "model_id": model_id,
                    "user_ask": user_message
                }
        else:
            # اگر مدل انتخاب نشده باشد، پیام ارسال می‌کنیم
            await update.message.reply_text(
                "لطفاً ابتدا با استفاده از دستور /select_model یک مدل انتخاب کنید"
            )
            return

    # پردازش درخواست و ارسال پاسخ
    await process_ai_request(
        context,
        update.message.chat_id,
        user_message
    )


async def new_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """شروع یک گفت‌وگوی جدید."""
    user_id = update.effective_user.id

    # دریافت دسترسی به پایگاه داده
    db = context.bot_data.get("db")
    if db:
        # اگر گفت‌وگوی فعلی وجود دارد، آن را به عنوان کامل شده علامت‌گذاری می‌کنیم
        if "current_dialog" in context.user_data:
            db.mark_last_message(user_id, context.user_data["current_dialog"])

        # ایجاد گفت‌وگوی جدید
        context.user_data["current_dialog"] = db.get_next_dialog_number(user_id)

        await update.message.reply_text(
            f"گفت‌وگوی جدید شروع شد (شماره {context.user_data['current_dialog']}). "
            f"تاریخچه گفت‌وگوی قبلی استفاده نخواهد شد."
        )
    else:
        await update.message.reply_text("خطا در دسترسی به پایگاه داده.")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازشگر کلیک‌های روی دکمه‌ها."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    is_admin = str(user_id) in config.ADMIN_IDS

    if data.startswith("model_"):
        # استخراج شناسه مدل
        model_id = data[6:]

        # بررسی اینکه آیا کاربر اجازه استفاده از این مدل را دارد
        db = context.bot_data.get("db")
        if db:
            cursor = db.conn.cursor()
            cursor.execute("SELECT is_free FROM models WHERE id = ?", (model_id,))
            result = cursor.fetchone()

            is_free_model = True  # به طور پیش‌فرض مدل را رایگان در نظر می‌گیریم
            if result is not None:
                is_free_model = bool(result[0])

            # اگر مدل پولی باشد و کاربر ادمین نباشد، خطا اعلام می‌کنیم
            if not is_free_model and not is_admin:
                await query.edit_message_text(
                    "⚠️ شما به این مدل دسترسی ندارید. لطفاً یک مدل رایگان انتخاب کنید."
                )
                return

        # ذخیره مدل
        context.user_data["selected_model"] = model_id

        # یافتن نام مدل و توضیحات برای نمایش
        models = await get_available_models(context, user_id)
        model_name = model_id
        model_description = "بدون توضیحات"

        for model in models:
            if model["id"] == model_id:
                model_name = model["name"]
                model_description = model["description"]
                break

        # اگر گفت‌وگوی فعلی وجود دارد، آن را به عنوان کامل شده علامت‌گذاری می‌کنیم
        if db and "current_dialog" in context.user_data:
            db.mark_last_message(user_id, context.user_data["current_dialog"])
            # ایجاد گفت‌وگوی جدید هنگام انتخاب مدل جدید
            context.user_data["current_dialog"] = db.get_next_dialog_number(user_id)

        # برای ادمین‌ها اطلاعات قیمت مدل را اضافه می‌کنیم
        if is_admin and db:
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT prompt_price, completion_price, is_free FROM models WHERE id = ?",
                (model_id,)
            )
            result = cursor.fetchone()

            if result:
                prompt_price = result[0] or "0"
                completion_price = result[1] or "0"
                is_free = bool(result[2])

                pricing_info = (
                    f"اطلاعات قیمت:\n"
                    f"هزینه درخواست: {prompt_price}\n"
                    f"هزینه پاسخ: {completion_price}\n"
                    f"وضعیت: {'رایگان' if is_free else 'پولی'}\n\n"
                )
            else:
                pricing_info = ""
        else:
            pricing_info = ""

        # تشکیل پیام با نام و توضیحات مدل
        response_message = (
            f"شما مدل را انتخاب کردید: {model_name}\n\n"
            f"{pricing_info}"
            f"توضیحات مدل:\n{model_description}\n\n"
            "اکنون می‌توانید پیام خود را ارسال کنید و من آن را به مدل هوش مصنوعی انتخاب‌شده منتقل می‌کنم."
        )

        # اگر پیام بیش از حد طولانی باشد، آن را کوتاه می‌کنیم
        if len(response_message) > 4096:
            response_message = response_message[:4093] + "..."

        await query.edit_message_text(response_message)

    elif data.startswith("modelpage_"):
        # پردازش ناوبری بین صفحات
        if data == "modelpage_info":
            # فقط اطلاعات صفحه فعلی، کاری انجام نمی‌دهیم
            return

        # دریافت شماره صفحه
        page = int(data[10:])

        # ذخیره صفحه در زمینه کاربر
        context.user_data["model_page"] = page

        # دریافت فیلتر فعلی
        current_filter = context.user_data.get("model_filter", "all")

        # دریافت مدل‌ها با توجه به فیلتر
        models = await get_available_models(context, user_id)

        # اعمال فیلترها
        if current_filter == "free":
            models = [model for model in models if model.get("is_free")]
        elif current_filter == "top":
            models = [model for model in models if model.get("top_model")]

        # ساخت صفحه‌کلید برای صفحه جدید
        keyboard = build_model_keyboard(models, page)

        # تعیین متن بر اساس فیلتر
        filter_text = ""
        if current_filter == "free":
            filter_text = "(فقط مدل‌های رایگان نمایش داده شده‌اند)"
        elif current_filter == "top":
            filter_text = "(فقط مدل‌های برتر نمایش داده شده‌اند)"

        # بررسی وجود مدل انتخاب‌شده
        selected_model_text = ""
        if "selected_model" in context.user_data:
            model_id = context.user_data["selected_model"]
            model_name = model_id

            # جستجوی نام مدل انتخاب‌شده
            for model in models:
                if model["id"] == model_id:
                    model_name = model["name"]
                    break

            selected_model_text = f"مدل انتخاب‌شده فعلی: {model_name}\n\n"

        # به‌روزرسانی پیام با صفحه‌کلید جدید
        admin_info = "👑 همه مدل‌ها، از جمله مدل‌های پولی (💰) برای شما در دسترس است.\n\n" if is_admin else ""

        await query.edit_message_text(
            f"{admin_info}{selected_model_text}یک مدل هوش مصنوعی برای گفت‌وگو انتخاب کنید {filter_text}:",
            reply_markup=keyboard
        )

    elif data.startswith("modelfilt_"):
        # پردازش فیلتر کردن مدل‌ها
        filter_type = data[10:]  # free, top یا all

        # ذخیره فیلتر در زمینه کاربر
        context.user_data["model_filter"] = filter_type

        # بازنشانی صفحه به صفحه اول
        context.user_data["model_page"] = 0

        # دریافت مدل‌ها با توجه به فیلتر جدید
        models = await get_available_models(context, user_id)

        # اعمال فیلترها
        if filter_type == "free":
            models = [model for model in models if model.get("is_free")]
        elif filter_type == "top":
            models = [model for model in models if model.get("top_model")]

        # ساخت صفحه‌کلید برای صفحه جدید
        keyboard = build_model_keyboard(models, 0)

        # تعیین متن بر اساس فیلتر
        filter_text = ""
        if filter_type == "free":
            filter_text = "(فقط مدل‌های رایگان نمایش داده شده‌اند)"
        elif filter_type == "top":
            filter_text = "(فقط مدل‌های برتر نمایش داده شده‌اند)"

        # بررسی وجود مدل انتخاب‌شده
        selected_model_text = ""
        if "selected_model" in context.user_data:
            model_id = context.user_data["selected_model"]
            model_name = model_id

            # جستجوی نام مدل انتخاب‌شده
            for model in models:
                if model["id"] == model_id:
                    model_name = model["name"]
                    break

            selected_model_text = f"مدل انتخاب‌شده فعلی: {model_name}\n\n"

        # به‌روزرسانی پیام با صفحه‌کلید جدید
        admin_info = "👑 همه مدل‌ها، از جمله مدل‌های پولی (💰) برای شما در دسترس است.\n\n" if is_admin else ""

        await query.edit_message_text(
            f"{admin_info}{selected_model_text}یک مدل هوش مصنوعی برای گفت‌وگو انتخاب کنید {filter_text}:",
            reply_markup=keyboard
        )

    elif data.startswith("reload_"):
        # پردازش بارگذاری مجدد پاسخ
        try:
            message_id_to_reload = int(data.split("_")[1])
            user_message = context.user_data.get("last_message", {}).get("text", "")

            if not user_message:
                await query.edit_message_text("نتوانستیم پاسخ را بارگذاری مجدد کنیم: پیام یافت نشد")
                return

            # ایجاد پیام جدید برای بارگذاری مجدد
            cancel_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ توقف تولید محتوا", callback_data="cancel_stream")
            ]])

            new_message = await context.bot.send_message(
                chat_id=chat_id,
                text="در حال تولید پاسخ جدید...",
                reply_markup=cancel_keyboard
            )

            # تنظیم پرچم بارگذاری مجدد برای به‌روزرسانی صحیح در پایگاه داده
            await process_ai_request(context, chat_id, user_message, is_reload=True)

        except Exception as e:
            logger.error(f"خطا در بارگذاری مجدد پاسخ: {e}")
            await query.edit_message_text(f"خطا در بارگذاری مجدد پاسخ: {str(e)}")

    elif data == "cancel_stream":
        # پردازش لغو جریان
        if "active_streams" in context.bot_data and str(chat_id) in context.bot_data["active_streams"]:
            cancel_event = context.bot_data["active_streams"][str(chat_id)]
            cancel_event.set()

            # تغییر دکمه به نشانگر لغو
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⏳ در حال لغو تولید...", callback_data="cancel_stream_processing")
                ]])
            )

            # انتظار کوتاه برای پردازش لغو
            asyncio.create_task(wait_for_cancel_processing(context, chat_id, query.message.message_id))

    elif data == "cancel_stream_processing":
        # پردازش فرآیند لغو - فقط به کاربر اطلاع می‌دهیم
        await query.answer("تولید در حال متوقف شدن است...")

    elif data == "cancel_stream":
        # پردازش لغو جریان
        if "active_streams" in context.bot_data and str(chat_id) in context.bot_data["active_streams"]:
            cancel_event = context.bot_data["active_streams"][str(chat_id)]
            cancel_event.set()

            # حذف دکمه‌ها برای جلوگیری از کلیک مجدد کاربر
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as e:
                logger.error(f"خطا در حذف دکمه‌ها پس از لغو: {e}")

            # ارسال اعلان لغو
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ تولید پاسخ متوقف شد."
            )

    elif data == "new_dialog":
        # ایجاد گفت‌وگوی جدید
        db = context.bot_data.get("db")
        if db:
            # اگر گفت‌وگوی فعلی وجود دارد، آن را به عنوان کامل شده علامت‌گذاری می‌کنیم
            if "current_dialog" in context.user_data:
                db.mark_last_message(user_id, context.user_data["current_dialog"])

            # ایجاد گفت‌وگوی جدید
            context.user_data["current_dialog"] = db.get_next_dialog_number(user_id)

            # به‌روزرسانی پیام با تأیید
            await query.edit_message_text(
                f"گفت‌وگوی جدید شروع شد (شماره {context.user_data['current_dialog']}). "
                f"تاریخچه گفت‌وگوی قبلی استفاده نخواهد شد."
            )
        else:
            await query.edit_message_text("خطا در دسترسی به پایگاه داده.")


async def wait_for_cancel_processing(context, chat_id, message_id, wait_time=1.5):
    """
    انتظار برای پردازش لغو تولید و به‌روزرسانی دکمه‌ها در پیام.

    Args:
        context: زمینه ربات تلگرام
        chat_id: شناسه چت
        message_id: شناسه پیام
        wait_time: زمان انتظار به ثانیه
    """
    # انتظار برای زمان مشخص‌شده برای پردازش لغو
    await asyncio.sleep(wait_time)

    # به‌روزرسانی دکمه‌ها، فقط اگر جریان هنوز فعال باشد
    if "active_streams" in context.bot_data and str(chat_id) in context.bot_data["active_streams"]:
        try:
            # حذف کامل دکمه‌ها، زیرا تولید باید متوقف شده باشد
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None
            )
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی دکمه‌ها پس از لغو: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازش دستور /start."""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id

    # بررسی اینکه آیا کاربر ادمین است
    is_admin = str(user_id) in config.ADMIN_IDS

    # پیام خوش‌آمدگویی پایه
    welcome_message = (
        f"سلام، {user.first_name}! 👋\n\n"
        f"من یک ربات هستم که به شما کمک می‌کنم با مدل‌های مختلف هوش مصنوعی از طریق OpenRouter تعامل کنید.\n\n"
        f"برای شروع، یک مدل هوش مصنوعی را با استفاده از دستور /select_model انتخاب کنید.\n"
        f"سپس کافی است یک پیام متنی برای من ارسال کنید، و من آن را به مدل انتخاب‌شده منتقل می‌کنم.\n\n"
    )

    # اطلاعات اضافی برای ادمین‌ها
    if is_admin:
        admin_message = (
            "👑 شما به عنوان ادمین وارد شده‌اید!\n"
            "دستورات اضافی و مدل‌های پولی برای شما در دسترس است:\n"
            "/update_models - به‌روزرسانی لیست مدل‌ها از API\n"
            "/translate_descriptions - ترجمه توضیحات مدل‌ها\n"
            "/translate_all - ترجمه تمام توضیحات مدل‌ها\n"
            "/set_description - تنظیم توضیحات پارسی برای مدل\n"
            "/set_top - تنظیم یا حذف وضعیت مدل برتر\n"
            "/list_models - نمایش لیست مدل‌ها در پایگاه داده\n\n"
        )
        welcome_message += admin_message

    welcome_message += f"برای اطلاعات بیشتر از دستور /help استفاده کنید."

    await update.message.reply_text(welcome_message)

    # تنظیم دستورات برای کاربر
    await set_user_commands(context, user_id, chat_id)


async def set_user_commands(context, user_id, chat_id):
    """
    تنظیم دستورات برای کاربر خاص.

    Args:
        context: زمینه ربات تلگرام
        user_id: شناسه کاربر
        chat_id: شناسه چت
    """
    # بررسی اینکه آیا کاربر ادمین است
    is_admin = str(user_id) in config.ADMIN_IDS

    # دستورات پایه برای همه کاربران
    base_commands = [
        BotCommand("start", "شروع کار با ربات"),
        BotCommand("help", "نمایش پیام راهنما"),
        BotCommand("select_model", "انتخاب مدل هوش مصنوعی"),
        BotCommand("new_dialog", "شروع گفت‌وگوی جدید")
    ]

    if is_admin:
        # دستورات اضافی برای ادمین‌ها
        admin_commands = [
            BotCommand("update_models", "به‌روزرسانی لیست مدل‌ها"),
            BotCommand("translate_descriptions", "ترجمه توضیحات مدل‌ها"),
            BotCommand("translate_all", "ترجمه تمام توضیحات"),
            BotCommand("set_description", "تنظیم توضیحات مدل"),
            BotCommand("set_top", "تنظیم مدل برتر"),
            BotCommand("list_models", "نمایش لیست مدل‌ها")
        ]
        # ترکیب دستورات پایه و ادمین
        commands = base_commands + admin_commands
    else:
        commands = base_commands

    try:
        # تلاش برای تنظیم دستورات برای چت خاص
        try:
            # روش اول: استفاده از دیکشنری برای scope
            await context.bot.set_my_commands(
                commands=commands,
                scope={"type": "chat", "chat_id": chat_id}
            )
            logger.info(f"دستورات برای چت {chat_id} تنظیم شدند")
        except Exception as e1:
            logger.warning(f"نتوانستیم دستورات را تنظیم کنیم (روش اول): {e1}")

            try:
                # روش دوم: استفاده از روش بدون scope
                await context.bot.delete_my_commands()  # حذف دستورات قبلی
                await context.bot.set_my_commands(commands=commands)
                logger.info(f"دستورات به صورت جهانی تنظیم شدند (روش دوم)")
            except Exception as e2:
                logger.error(f"نتوانستیم دستورات را تنظیم کنیم (روش دوم): {e2}")

    except Exception as e:
        logger.error(f"خطا در تنظیم دستورات: {e}")


def build_model_keyboard(models, page=0, page_size=8):
    """
    ایجاد صفحه‌کلید با مدل‌ها با پشتیبانی از صفحه‌بندی.

    Args:
        models: لیست مدل‌ها
        page: صفحه فعلی (شروع از 0)
        page_size: تعداد مدل‌ها در هر صفحه

    Returns:
        InlineKeyboardMarkup: صفحه‌کلید با مدل‌ها و دکمه‌های ناوبری
    """
    # محاسبه تعداد کل صفحات
    total_pages = (len(models) + page_size - 1) // page_size

    # بررسی صحت شماره صفحه
    if page >= total_pages:
        page = total_pages - 1
    if page < 0:
        page = 0

    # دریافت مدل‌ها برای صفحه فعلی
    start = page * page_size
    end = min(start + page_size, len(models))
    current_models = models[start:end]

    # ایجاد دکمه‌ها برای مدل‌ها
    keyboard = []
    for model in current_models:
        # افزودن ایموجی برای مدل‌های برتر و پولی
        top_mark = "⭐️ " if model.get("top_model") else ""
        free_mark = "🆓 " if model.get("is_free") else "💰 "

        button_text = f"{top_mark}{free_mark}{model['name']}"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"model_{model['id']}")])

    # افزودن دکمه‌های ناوبری
    nav_buttons = []

    # دکمه "صفحه قبلی"
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ بازگشت", callback_data=f"modelpage_{page - 1}"))

    # نشانگر صفحه
    nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="modelpage_info"))

    # دکمه "صفحه بعدی"
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("جلو ▶️", callback_data=f"modelpage_{page + 1}"))

    # افزودن ردیف ناوبری
    if total_pages > 1:  # فقط در صورت وجود چند صفحه نمایش داده می‌شود
        keyboard.append(nav_buttons)

    # افزودن گزینه‌های فیلتر
    filter_buttons = [
        InlineKeyboardButton("🆓 رایگان", callback_data="modelfilt_free"),
        InlineKeyboardButton("⭐️ برتر", callback_data="modelfilt_top"),
        InlineKeyboardButton("🔄 همه", callback_data="modelfilt_all"),
    ]
    keyboard.append(filter_buttons)

    return InlineKeyboardMarkup(keyboard)


async def set_bot_commands(context, is_admin=False, chat_id=None):
    """
    تنظیم دستورات منوی در دسترس بر اساس وضعیت کاربر.

    Args:
        context: زمینه ربات تلگرام
        is_admin: آیا کاربر ادمین است
        chat_id: شناسه چت برای تنظیم دستورات (None = جهانی)
    """
    # دستورات پایه برای همه کاربران
    base_commands = [
        BotCommand("start", "شروع کار با ربات"),
        BotCommand("help", "نمایش پیام راهنما"),
        BotCommand("select_model", "انتخاب مدل هوش مصنوعی"),
        BotCommand("new_dialog", "شروع گفت‌وگوی جدید")
    ]

    if is_admin:
        # دستورات اضافی برای ادمین‌ها
        admin_commands = [
            BotCommand("update_models", "به‌روزرسانی لیست مدل‌ها"),
            BotCommand("translate_descriptions", "ترجمه توضیحات مدل‌ها"),
            BotCommand("translate_all", "ترجمه تمام توضیحات"),
            BotCommand("set_description", "تنظیم توضیحات مدل"),
            BotCommand("set_top", "تنظیم مدل برتر"),
            BotCommand("list_models", "نمایش لیست مدل‌ها")
        ]
        # ترکیب دستورات پایه و ادمین
        commands = base_commands + admin_commands
    else:
        commands = base_commands

    try:
        if chat_id:
            # تلاش برای تنظیم دستورات برای چت خاص
            try:
                # تلاش برای استفاده از scope به عنوان دیکشنری
                await context.bot.set_my_commands(
                    commands=commands,
                    scope={"type": "chat", "chat_id": chat_id}
                )
            except Exception as e:
                logger.warning(f"نتوانستیم دستورات را برای چت {chat_id} تنظیم کنیم: {e}")
                # تنظیم جهانی به عنوان گزینه جایگزین
                await context.bot.set_my_commands(commands=commands)
        else:
            # تنظیم جهانی دستورات
            await context.bot.set_my_commands(commands=commands)
    except Exception as e:
        logger.error(f"خطا در تنظیم دستورات: {e}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """پردازش دستور /help."""
    help_message = (
        "📚 *نحوه استفاده از ربات:*\n\n"
        "1️⃣ با استفاده از دستور /select_model یک مدل هوش مصنوعی انتخاب کنید\n"
        "2️⃣ پیام متنی که می‌خواهید به مدل منتقل شود را ارسال کنید\n"
        "3️⃣ منتظر پاسخ مدل بمانید\n\n"
        "📋 *دستورات در دسترس:*\n"
        "/start - شروع کار با ربات\n"
        "/help - نمایش این پیام راهنما\n"
        "/select_model - انتخاب مدل هوش مصنوعی برای گفت‌وگو\n"
        "/new_dialog - شروع گفت‌وگوی جدید (بازنشانی زمینه)\n\n"
        "💬 *درباره زمینه گفت‌وگو:*\n"
        "ربات تاریخچه گفت‌وگوی شما را ذخیره کرده و به مدل منتقل می‌کند. "
        "این امکان را فراهم می‌کند که گفت‌وگوی مداوم داشته باشید، جایی که مدل پیام‌های قبلی را به خاطر می‌آورد. "
        "اگر زمینه بیش از 90% پر شود، توصیه می‌شود با استفاده از دستور /new_dialog گفت‌وگوی جدیدی شروع کنید.\n\n"
        "💡 *نکته:* همیشه می‌توانید تولید پاسخ را با کلیک روی دکمه 'توقف تولید محتوا' متوقف کنید."
    )

    await update.message.reply_text(help_message)


async def get_available_models(context, user_id):
    """
    دریافت لیست مدل‌های در دسترس بر اساس وضعیت کاربر.

    Args:
        context: زمینه ربات تلگرام
        user_id: شناسه کاربر

    Returns:
        لیست مدل‌های در دسترس
    """
    # بررسی اینکه آیا کاربر ادمین است
    is_admin = str(user_id) in config.ADMIN_IDS

    # دریافت دسترسی به پایگاه داده
    db = context.bot_data.get("db")
    if db:
        if is_admin:
            # برای ادمین‌ها همه مدل‌ها را برمی‌گردانیم
            return db.get_models()
        else:
            # برای کاربران عادی فقط مدل‌های رایگان را برمی‌گردانیم
            return db.get_models(only_free=True)

    # اگر نتوانستیم از پایگاه داده دریافت کنیم، لیست پیش‌فرض مدل‌های رایگان را برمی‌گردانیم
    return []


async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش لیست مدل‌های در دسترس برای انتخاب."""
    user_id = update.effective_user.id

    # دریافت صفحه از زمینه یا استفاده از 0
    page = context.user_data.get("model_page", 0)

    # دریافت فیلتر فعلی از زمینه یا استفاده از "all"
    current_filter = context.user_data.get("model_filter", "all")

    # دریافت مدل‌ها بر اساس وضعیت کاربر و فیلتر
    models = await get_available_models(context, user_id)

    # اعمال فیلترها
    if current_filter == "free":
        models = [model for model in models if model.get("is_free")]
    elif current_filter == "top":
        models = [model for model in models if model.get("top_model")]

    # ساخت صفحه‌کلید با صفحه‌بندی
    keyboard = build_model_keyboard(models, page)

    # بررسی وجود مدل انتخاب‌شده
    selected_model_text = ""
    if "selected_model" in context.user_data:
        model_id = context.user_data["selected_model"]
        model_name = model_id

        # جستجوی نام مدل انتخاب‌شده
        for model in models:
            if model["id"] == model_id:
                model_name = model["name"]
                break

        selected_model_text = f"مدل انتخاب‌شده فعلی: {model_name}\n\n"

    # تعیین متن بر اساس فیلتر
    filter_text = ""
    if current_filter == "free":
        filter_text = "(فقط مدل‌های رایگان نمایش داده شده‌اند)"
    elif current_filter == "top":
        filter_text = "(فقط مدل‌های برتر نمایش داده شده‌اند)"

    # اطلاعات اضافی برای ادمین‌ها
    if str(user_id) in config.ADMIN_IDS:
        admin_info = "👑 همه مدل‌ها، از جمله مدل‌های پولی (💰) برای شما در دسترس است.\n\n"
    else:
        admin_info = ""

    # ارسال پیام با صفحه‌کلید داخلی
    await update.message.reply_text(
        f"{admin_info}{selected_model_text}یک مدل هوش مصنوعی برای گفت‌وگو انتخاب کنید {filter_text}:",
        reply_markup=keyboard
    )


async def update_models_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """به‌روزرسانی لیست مدل‌ها از API."""
    user_id = update.effective_user.id

    # بررسی اینکه آیا کاربر ادمین است
    if str(user_id) not in config.ADMIN_IDS:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    # ارسال پیام درباره شروع به‌روزرسانی
    message = await update.message.reply_text("در حال به‌روزرسانی لیست مدل‌ها...")

    # اجرای به‌روزرسانی در یک جریان جداگانه برای جلوگیری از مسدود شدن ربات
    def run_update():
        return fetch_and_update_models(context)

    # اجرا در جریان جداگانه
    success = await context.application.loop.run_in_executor(None, run_update)

    if success:
        await message.edit_text("لیست مدل‌ها با موفقیت به‌روزرسانی شد!")
    else:
        await message.edit_text("خطایی در به‌روزرسانی مدل‌ها رخ داد. جزئیات در لاگ‌ها.")


async def set_model_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تنظیم توضیحات پارسی برای مدل."""
    user_id = update.effective_user.id

    # بررسی اینکه آیا کاربر ادمین است
    if str(user_id) not in config.ADMIN_IDS:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    # بررسی آرگومان‌های دستور
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "از فرمت زیر استفاده کنید: /set_description model_id توضیحات مدل به پارسی"
        )
        return

    model_id = context.args[0]
    description = " ".join(context.args[1:])

    # دریافت دسترسی به پایگاه داده
    db = context.bot_data.get("db")
    if db:
        if db.update_model_description(model_id, description):
            await update.message.reply_text(f"توضیحات مدل {model_id} با موفقیت به‌روزرسانی شد!")
        else:
            await update.message.reply_text(f"خطایی در به‌روزرسانی توضیحات مدل {model_id} رخ داد.")
    else:
        await update.message.reply_text("خطا در دسترسی به پایگاه داده.")


async def set_top_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تنظیم یا حذف برچسب 'top_model' برای مدل."""
    user_id = update.effective_user.id

    # بررسی اینکه آیا کاربر ادمین است
    if str(user_id) not in config.ADMIN_IDS:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    # بررسی آرگومان‌های دستور
    if not context.args:
        await update.message.reply_text(
            "از فرمت زیر استفاده کنید: /set_top model_id [0|1]"
        )
        return

    model_id = context.args[0]
    top_status = True

    # اگر آرگومان دوم مشخص شده باشد، از آن به عنوان وضعیت استفاده می‌کنیم
    if len(context.args) > 1:
        top_status = context.args[1] != "0"

    # دریافت دسترسی به پایگاه داده
    db = context.bot_data.get("db")
    if db:
        # اگر وضعیت top_model را تنظیم می‌کنیم، ابتدا آن را برای همه مدل‌ها پاک می‌کنیم
        if top_status:
            db.clear_top_models()

        if db.update_model_description(model_id, None, top_status):
            status_text = "به" if top_status else "از"
            await update.message.reply_text(f"مدل {model_id} {status_text} مدل‌های برتر اضافه شد!")
        else:
            await update.message.reply_text(f"خطایی در به‌روزرسانی وضعیت مدل {model_id} رخ داد.")
    else:
        await update.message.reply_text("خطا در دسترسی به پایگاه داده.")


async def list_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش لیست مدل‌ها در پایگاه داده."""
    user_id = update.effective_user.id

    # بررسی اینکه آیا کاربر ادمین است
    if str(user_id) not in config.ADMIN_IDS:
        await update.message.reply_text("شما اجازه استفاده از این دستور را ندارید.")
        return

    # دریافت آرگومان‌های دستور (در صورت وجود)
    filter_type = "all"
    if context.args and context.args[0] in ["free", "top", "all"]:
        filter_type = context.args[0]

    # دریافت دسترسی به پایگاه داده
    db = context.bot_data.get("db")
    if db:
        only_free = (filter_type == "free")
        only_top = (filter_type == "top")

        models = db.get_models(only_free=only_free, only_top=only_top)

        if not models:
            await update.message.reply_text("لیست مدل‌ها خالی است.")
            return

        # تشکیل پیام با لیست مدل‌ها
        message = f"لیست مدل‌ها ({filter_type}):\n\n"

        for i, model in enumerate(models, 1):
            top_mark = "⭐️ " if model["top_model"] else ""
            free_mark = "🆓 " if model["is_free"] else ""

            model_info = (
                f"{i}. {top_mark}{free_mark}{model['name']}\n"
                f"شناسه: {model['id']}\n"
                f"توضیحات: {model['description'] or 'بدون توضیحات'}\n\n"
            )

            # اگر پیام بیش از حد طولانی شود، آن را ارسال کرده و پیام جدیدی شروع می‌کنیم
            if len(message + model_info) > 4000:
                await update.message.reply_text(message)
                message = model_info
            else:
                message += model_info

        # ارسال بخش باقی‌مانده پیام
        if message:
            await update.message.reply_text(message)
    else:
        await update.message.reply_text("خطا در دسترسی به پایگاه داده.")


def estimate_tokens(text):
    """
    تخمین تعداد توکن‌ها در متن.
    این یک روش ساده است: برای متن انگلیسی ~4 کاراکتر به ازای هر توکن،
    برای متن پارسی ~2 کاراکتر به ازای هر توکن.

    Args:
        text: متن برای تخمین

    Returns:
        تعداد تقریبی توکن‌ها
    """
    if not text:
        return 0

    # تعیین اینکه کدام کاراکترها غالب هستند - لاتین یا پارسی
    latin_chars = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    persian_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')

    # اگر کاراکترهای پارسی بیشتر باشند، به عنوان متن پارسی محاسبه می‌کنیم
    if persian_chars > latin_chars:
        tokens = len(text) / 2
    else:
        tokens = len(text) / 4

    # افزودن 5 توکن برای نقش و سایر متادیتاها
    tokens += 5

    return int(tokens)


def prepare_context(db, user_id, dialog_number, model_id, current_message, max_context_size=None):
    """
    آماده‌سازی زمینه گفت‌وگو با توجه به محدودیت‌های مدل.

    Args:
        db: نمونه DBHandler
        user_id: شناسه کاربر
        dialog_number: شماره گفت‌وگو
        model_id: شناسه مدل
        current_message: پیام فعلی کاربر
        max_context_size: حداکثر اندازه زمینه (اگر None باشد، از پایگاه داده گرفته می‌شود)

    Returns:
        (messages, context_usage_percent): لیست پیام‌ها برای زمینه و درصد پر شدن زمینه
    """
    # دریافت محدودیت زمینه برای مدل
    context_limit = max_context_size
    if not context_limit:
        cursor = db.conn.cursor()
        cursor.execute("SELECT context_length FROM models WHERE id = ?", (model_id,))
        result = cursor.fetchone()
        if result and result[0]:
            context_limit = result[0]
        else:
            # اگر در پایگاه داده یافت نشد، از مقدار پیش‌فرض استفاده می‌کنیم
            context_limit = 4096

    # دریافت تاریخچه گفت‌وگو
    history = db.get_dialog_history(user_id, dialog_number)

    # افزودن پیام فعلی
    messages = history + [{"role": "user", "content": current_message}]

    # تخمین تعداد کل توکن‌ها
    token_count = 0
    for message in messages:
        token_count += estimate_tokens(message["content"])

    # اگر از محدودیت فراتر رفت، پیام‌های قدیمی را حذف می‌کنیم تا در حد مجاز قرار بگیریم
    while token_count > context_limit * 0.95 and len(messages) > 1:
        # حذف قدیمی‌ترین پیام‌ها
        removed_message = messages.pop(0)
        token_count -= estimate_tokens(removed_message["content"])

    # محاسبه درصد پر شدن زمینه
    context_usage_percent = (token_count / context_limit) * 100

    return messages, context_usage_percent


async def post_init(application: Application) -> None:
    """
    پس از مقداردهی اولیه برنامه، اما قبل از پردازش به‌روزرسانی‌ها اجرا می‌شود.
    دستورات پایه را برای همه کاربران تنظیم می‌کند.
    """
    # تنظیم دستورات پایه برای همه کاربران
    base_commands = [
        BotCommand("start", "شروع کار با ربات"),
        BotCommand("help", "نمایش پیام راهنما"),
        BotCommand("select_model", "انتخاب مدل هوش مصنوعی"),
        BotCommand("new_dialog", "شروع گفت‌وگوی جدید")
    ]

    try:
        # تنظیم جهانی دستورات پایه
        await application.bot.set_my_commands(commands=base_commands)
        logger.info("دستورات پایه با موفقیت تنظیم شدند")
    except Exception as e:
        logger.error(f"خطا در تنظیم دستورات پایه: {e}")


def main() -> None:
    """راه‌اندازی ربات."""
    # ایجاد پردازشگر به‌روزرسانی‌ها
    global application
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # مقداردهی اولیه پایگاه داده
    db = DBHandler(config.DB_PATH)
    application.bot_data["db"] = db

    # به‌روزرسانی مدل‌ها در هنگام راه‌اندازی در یک جریان جداگانه
    def update_models_at_startup():
        fetch_and_update_models(application)

    threading.Thread(target=update_models_at_startup).start()

    # افزودن پردازشگرهای دستورات
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("select_model", select_model))
    application.add_handler(CommandHandler("new_dialog", new_dialog))

    # دستورات برای مدیریت مدل‌ها (فقط برای ادمین‌ها)
    application.add_handler(CommandHandler("update_models", update_models_command))
    application.add_handler(CommandHandler("set_description", set_model_description))
    application.add_handler(CommandHandler("set_top", set_top_model))
    application.add_handler(CommandHandler("list_models", list_models))
    application.add_handler(CommandHandler("translate_descriptions", translate_descriptions))
    application.add_handler(CommandHandler("translate_all", translate_all_models))

    # افزودن پردازشگر دکمه‌های داخلی
    application.add_handler(CallbackQueryHandler(button_callback))

    # افزودن پردازشگر پیام‌های متنی
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # راه‌اندازی ربات
    application.run_polling()


if __name__ == "__main__":
    main()
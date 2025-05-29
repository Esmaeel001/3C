# config.py

# توکن‌ها و کلیدهای API
TELEGRAM_BOT_TOKEN = "123"
OPENROUTER_API_KEY = "213"

DB_PATH = r"data/openrouter_bot.db"

# تنظیمات وب‌سایت برای اوپن‌روتر
SITE_URL = "https://github.com/user-is-absinthe/openrouter-telegram-bot"
SITE_NAME = "OpenRouter Telegram Bot"

# تنظیمات به‌روزرسانی پیام‌ها
STREAM_UPDATE_INTERVAL = 1.5  # فاصله زمانی به‌روزرسانی پیام‌ها در ثانیه هنگام انتقال جریان

# افزودن فیلد برای شناسه‌های مدیران (لیست رشته‌ها)
ADMIN_IDS = ["1", "2", "3"]
# ADMIN_IDS = ["شناسه_مدیر_شما_2"]
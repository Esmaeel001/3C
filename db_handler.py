import os
import sqlite3
import logging
from datetime import datetime

# تنظیم لاگ‌گیری
logger = logging.getLogger(__name__)

class DBHandler:
    def __init__(self, db_path):
        """آغاز اتصال به پایگاه داده."""
        self.db_path = db_path
        self.conn = None

        # ایجاد پوشه برای پایگاه داده اگر وجود نداشته باشد
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # اتصال به پایگاه داده
        self.connect()

        # ایجاد جدول‌های مورد نیاز اگر وجود نداشته باشند
        self.create_tables()

        # به‌روزرسانی طرح پایگاه داده در صورت نیاز
        self.update_schema()

    def connect(self):
        """اتصال به پایگاه داده SQLite."""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.execute("PRAGMA foreign_keys = ON")
        except Exception as e:
            logger.error(f"خطا در اتصال به پایگاه داده: {e}")

    def create_tables(self):
        """ایجاد جدول‌های مورد نیاز."""
        try:
            cursor = self.conn.cursor()

            # ایجاد جدول کاربران
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                id_chat INTEGER NOT NULL,
                id_user INTEGER NOT NULL,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                register_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                is_premium INTEGER DEFAULT 0,
                UNIQUE(id_chat, id_user)
            )
            ''')

            # ایجاد جدول گفت‌وگوها با ستون displayed
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS dialogs (
                id INTEGER PRIMARY KEY,
                id_chat INTEGER NOT NULL,
                id_user INTEGER NOT NULL,
                number_dialog INTEGER NOT NULL,
                model TEXT,
                model_id TEXT,
                user_ask TEXT,
                model_answer TEXT,
                ask_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                displayed INTEGER DEFAULT 1,
                FOREIGN KEY (id_chat, id_user) REFERENCES users (id_chat, id_user)
            )
            ''')

            # ایجاد جدول مدل‌ها
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS models (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created INTEGER,
                description TEXT,
                rus_description TEXT,
                context_length INTEGER,
                modality TEXT,
                tokenizer TEXT,
                instruct_type TEXT,
                prompt_price TEXT,
                completion_price TEXT,
                image_price TEXT,
                request_price TEXT,
                provider_context_length INTEGER,
                is_moderated INTEGER,
                is_free INTEGER,
                top_model INTEGER DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            ''')

            self.conn.commit()
        except Exception as e:
            logger.error(f"خطا در ایجاد جدول‌ها: {e}")

    def update_schema(self):
        """به‌روزرسانی طرح پایگاه داده در صورت نیاز."""
        try:
            cursor = self.conn.cursor()

            # بررسی وجود ستون 'displayed' در جدول 'dialogs'
            cursor.execute("PRAGMA table_info(dialogs)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'displayed' not in columns:
                logger.info("افزودن ستون 'displayed' به جدول 'dialogs'")
                cursor.execute("ALTER TABLE dialogs ADD COLUMN displayed INTEGER DEFAULT 1")
                self.conn.commit()

                # تنظیم مقدار پیش‌فرض برای رکوردهای موجود
                cursor.execute("UPDATE dialogs SET displayed = 1 WHERE displayed IS NULL")
                self.conn.commit()

            # بررسی وجود جدول 'models'
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='models'")
            if not cursor.fetchone():
                logger.info("ایجاد جدول 'models'")
                cursor.execute('''
                CREATE TABLE models (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created INTEGER,
                    description TEXT,
                    rus_description TEXT,
                    context_length INTEGER,
                    modality TEXT,
                    tokenizer TEXT,
                    instruct_type TEXT,
                    prompt_price TEXT,
                    completion_price TEXT,
                    image_price TEXT,
                    request_price TEXT,
                    provider_context_length INTEGER,
                    is_moderated INTEGER,
                    is_free INTEGER,
                    top_model INTEGER DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                ''')
                self.conn.commit()

            # بررسی وجود ستون 'is_premium' در جدول 'users'
            cursor.execute("PRAGMA table_info(users)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'is_premium' not in columns:
                logger.info("افزودن ستون 'is_premium' به جدول 'users'")
                cursor.execute("ALTER TABLE users ADD COLUMN is_premium INTEGER DEFAULT 0")
                self.conn.commit()

                # تنظیم مقدار پیش‌فرض برای رکوردهای موجود
                cursor.execute("UPDATE users SET is_premium = 0 WHERE is_premium IS NULL")
                self.conn.commit()

        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی طرح پایگاه داده: {e}")

    def close(self):
        """بستن اتصال به پایگاه داده."""
        if self.conn:
            self.conn.close()

    def register_user(self, id_chat, id_user, first_name, last_name, username, is_premium=None):
        """ثبت کاربر یا به‌روزرسانی اطلاعات او."""
        try:
            cursor = self.conn.cursor()

            # بررسی وجود کاربر
            cursor.execute("SELECT id, is_premium FROM users WHERE id_chat = ? AND id_user = ?", (id_chat, id_user))
            result = cursor.fetchone()

            if result:
                # به‌روزرسانی کاربر موجود
                # اگر is_premium مشخص نشده باشد، مقدار فعلی حفظ می‌شود
                current_premium = result[1] if is_premium is None else is_premium

                cursor.execute(
                    "UPDATE users SET first_name = ?, last_name = ?, username = ?, is_premium = ? WHERE id_chat = ? AND id_user = ?",
                    (first_name, last_name, username, current_premium, id_chat, id_user)
                )
            else:
                # ثبت کاربر جدید
                # به طور پیش‌فرض غیرپرمیوم
                premium_status = 0 if is_premium is None else (1 if is_premium else 0)

                cursor.execute(
                    "INSERT INTO users (id_chat, id_user, first_name, last_name, username, is_premium) VALUES (?, ?, ?, ?, ?, ?)",
                    (id_chat, id_user, first_name, last_name, username, premium_status)
                )

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"خطا در ثبت کاربر: {e}")
            return False

    def log_dialog(self, id_chat, id_user, number_dialog, model, model_id, user_ask, model_answer=None, displayed=1):
        """ثبت گفت‌وگو."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "INSERT INTO dialogs (id_chat, id_user, number_dialog, model, model_id, user_ask, model_answer, displayed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (id_chat, id_user, number_dialog, model, model_id, user_ask, model_answer, displayed)
            )
            self.conn.commit()
            return cursor.lastrowid  # بازگشت شناسه رکورد درج‌شده
        except Exception as e:
            logger.error(f"خطا در ثبت گفت‌وگو: {e}")
            return None

    def update_model_answer(self, dialog_id, model_answer, displayed=1):
        """به‌روزرسانی پاسخ مدل در رکورد گفت‌وگوی موجود."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE dialogs SET model_answer = ?, displayed = ? WHERE id = ?",
                (model_answer, displayed, dialog_id)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی پاسخ مدل: {e}")

    def get_next_dialog_number(self, id_user):
        """دریافت شماره گفت‌وگوی بعدی برای کاربر."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT MAX(number_dialog) FROM dialogs WHERE id_user = ?",
                (id_user,)
            )
            result = cursor.fetchone()[0]

            # اگر این اولین گفت‌وگوی کاربر باشد
            if result is None:
                return 1

            # در غیر این صورت شماره گفت‌وگو را یک واحد افزایش می‌دهیم
            return result + 1
        except Exception as e:
            logger.error(f"خطا در دریافت شماره گفت‌وگو: {e}")
            return 1  # در صورت خطا، 1 را برمی‌گردانیم

    def mark_last_message(self, id_user, number_dialog):
        """علامت‌گذاری تکمیل شدن گفت‌وگوی فعلی."""
        try:
            cursor = self.conn.cursor()
            # عملیات صوری برای علامت‌گذاری تکمیل گفت‌وگو
            # در آینده می‌توان ستون خاصی به جدول اضافه کرد
            cursor.execute(
                "SELECT MAX(id) FROM dialogs WHERE id_user = ? AND number_dialog = ?",
                (id_user, number_dialog)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"خطا در علامت‌گذاری تکمیل گفت‌وگو: {e}")

    def mark_previous_answers_as_inactive(self, dialog_id):
        """علامت‌گذاری پاسخ قبلی مدل به عنوان غیرقابل نمایش."""
        try:
            cursor = self.conn.cursor()
            # فقط پاسخ فعلی را به عنوان غیرقابل نمایش به‌روزرسانی می‌کنیم
            cursor.execute(
                "UPDATE dialogs SET displayed = 0 WHERE id = ?",
                (dialog_id,)
            )
            self.conn.commit()
            logger.info(f"پاسخ {dialog_id} به عنوان غیرفعال علامت‌گذاری شد")
            return True
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی وضعیت پاسخ: {e}")
            return False

    # متدهای مربوط به کار با مدل‌ها
    def save_model(self, model_data):
        """ذخیره یا به‌روزرسانی اطلاعات مدل در پایگاه داده."""
        try:
            # استخراج داده‌ها از JSON
            model_id = model_data.get("id")
            name = model_data.get("name")
            created = model_data.get("created")
            description = model_data.get("description")
            context_length = model_data.get("context_length")

            # استخراج داده‌ها از ساختارهای تودرتو
            architecture = model_data.get("architecture", {})
            modality = architecture.get("modality")
            tokenizer = architecture.get("tokenizer")
            instruct_type = architecture.get("instruct_type")

            pricing = model_data.get("pricing", {})
            prompt_price = pricing.get("prompt")
            completion_price = pricing.get("completion")
            image_price = pricing.get("image")
            request_price = pricing.get("request")

            top_provider = model_data.get("top_provider", {})
            provider_context_length = top_provider.get("context_length")
            is_moderated = 1 if top_provider.get("is_moderated") else 0

            # بررسی اینکه آیا مدل رایگان است
            is_free = 1 if model_id.endswith(":free") or (prompt_price == "0" and completion_price == "0") else 0

            cursor = self.conn.cursor()

            # بررسی وجود مدل در پایگاه داده
            cursor.execute("SELECT id, rus_description, top_model FROM models WHERE id = ?", (model_id,))
            existing = cursor.fetchone()

            if existing:
                # حفظ مقادیر فعلی rus_description و top_model
                rus_description = existing[1]
                top_model = existing[2]

                # به‌روزرسانی رکورد موجود، با حفظ rus_description و top_model
                cursor.execute("""
                UPDATE models SET 
                    name = ?, 
                    created = ?, 
                    description = ?,
                    context_length = ?,
                    modality = ?,
                    tokenizer = ?,
                    instruct_type = ?,
                    prompt_price = ?,
                    completion_price = ?,
                    image_price = ?,
                    request_price = ?,
                    provider_context_length = ?,
                    is_moderated = ?,
                    is_free = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """, (
                    name, created, description, context_length, modality, tokenizer,
                    instruct_type, prompt_price, completion_price, image_price,
                    request_price, provider_context_length, is_moderated, is_free,
                    model_id
                ))
            else:
                # افزودن رکورد جدید
                cursor.execute("""
                INSERT INTO models (
                    id, name, created, description, rus_description,
                    context_length, modality, tokenizer, instruct_type,
                    prompt_price, completion_price, image_price, request_price,
                    provider_context_length, is_moderated, is_free, top_model
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    model_id, name, created, description, context_length, modality, tokenizer,
                    instruct_type, prompt_price, completion_price, image_price,
                    request_price, provider_context_length, is_moderated, is_free
                ))

            self.conn.commit()
            return True

        except Exception as e:
            logger.error(f"خطا در ذخیره مدل {model_data.get('id')}: {e}")
            return False

    def get_models(self, only_free=False, only_top=False):
        """دریافت لیست مدل‌ها از پایگاه داده با امکان فیلتر کردن."""
        try:
            cursor = self.conn.cursor()

            query = "SELECT id, name, description, rus_description, context_length, is_free, top_model FROM models"
            conditions = []
            params = []

            if only_free:
                conditions.append("is_free = 1")

            if only_top:
                conditions.append("top_model = 1")

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # مرتب‌سازی: ابتدا مدل‌های برتر، سپس بر اساس نام
            query += " ORDER BY top_model DESC, name ASC"

            cursor.execute(query, params)

            models = []
            for row in cursor.fetchall():
                model = {
                    "id": row[0],
                    "name": row[1],
                    "description": row[3] if row[3] else row[2],  # استفاده از rus_description در صورت وجود
                    "context_length": row[4],
                    "is_free": bool(row[5]),
                    "top_model": bool(row[6])
                }
                models.append(model)

            return models

        except Exception as e:
            logger.error(f"خطا در دریافت لیست مدل‌ها: {e}")
            return []

    def set_model_description_ru(self, model_id, rus_description):
        """به‌روزرسانی توضیحات فارسی مدل."""
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE models SET rus_description = ? WHERE id = ?",
                (rus_description, model_id)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی توضیحات فارسی مدل {model_id}: {e}")
            return False

    def update_model_description(self, model_id, rus_description, top_model=None):
        """به‌روزرسانی توضیحات فارسی و/یا وضعیت مدل برتر."""
        try:
            cursor = self.conn.cursor()

            # تشکیل درخواست بسته به آنچه به‌روزرسانی می‌شود
            if top_model is not None:
                cursor.execute(
                    "UPDATE models SET rus_description = ?, top_model = ? WHERE id = ?",
                    (rus_description, 1 if top_model else 0, model_id)
                )
            else:
                cursor.execute(
                    "UPDATE models SET rus_description = ? WHERE id = ?",
                    (rus_description, model_id)
                )

            self.conn.commit()
            return True

        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی توضیحات مدل {model_id}: {e}")
            return False

    def clear_top_models(self):
        """بازنشانی وضعیت مدل برتر برای همه مدل‌ها."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE models SET top_model = 0")
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"خطا در بازنشانی وضعیت مدل‌های برتر: {e}")
            return False

    def get_models_for_translation(self, model_id=None):
        """
        دریافت لیست مدل‌ها برای ترجمه.

        Args:
            model_id: شناسه مدل خاص یا None برای همه مدل‌های بدون توضیحات فارسی

        Returns:
            لیست تاپل‌های (id, description) مدل‌ها برای ترجمه
        """
        try:
            cursor = self.conn.cursor()

            if model_id:
                # دریافت مدل خاص
                cursor.execute(
                    "SELECT id, description FROM models WHERE id = ?",
                    (model_id,)
                )
            else:
                # دریافت همه مدل‌ها با توضیحات فارسی خالی
                cursor.execute(
                    "SELECT id, description FROM models WHERE rus_description IS NULL OR rus_description = ''"
                )

            return cursor.fetchall()

        except Exception as e:
            logger.error(f"خطا در دریافت مدل‌ها برای ترجمه: {e}")
            return []

    def get_dialog_history(self, id_user, number_dialog, limit=None):
        """
        دریافت تاریخچه گفت‌وگوی کاربر.

        Args:
            id_user: شناسه کاربر
            number_dialog: شماره گفت‌وگو
            limit: حداکثر تعداد پیام‌ها برای بازگشت (None = همه پیام‌ها)

        Returns:
            لیست دیکشنری‌های حاوی پیام‌های گفت‌وگو [{"role": "user/assistant", "content": "..."}]
        """
        try:
            cursor = self.conn.cursor()

            query = """
            SELECT user_ask, model_answer 
            FROM dialogs 
            WHERE id_user = ? AND number_dialog = ? AND displayed = 1 
            ORDER BY id ASC
            """

            params = [id_user, number_dialog]

            if limit:
                query += " LIMIT ?"
                params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            history = []
            for row in rows:
                # افزودن پیام کاربر
                if row[0]:  # user_ask
                    history.append({
                        "role": "user",
                        "content": row[0]
                    })

                # افزودن پاسخ مدل
                if row[1]:  # model_answer
                    history.append({
                        "role": "assistant",
                        "content": row[1]
                    })

            return history

        except Exception as e:
            logger.error(f"خطا در دریافت تاریخچه گفت‌وگو: {e}")
            return []

    def set_premium_status(self, user_id, is_premium=True):
        """
        تنظیم یا حذف وضعیت پرمیوم کاربر.

        Args:
            user_id: شناسه کاربر
            is_premium: True برای تنظیم پرمیوم، False برای حذف

        Returns:
            bool: True در صورت به‌روزرسانی موفق، False در صورت خطا
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "UPDATE users SET is_premium = ? WHERE id_user = ?",
                (1 if is_premium else 0, user_id)
            )
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"خطا در به‌روزرسانی وضعیت پرمیوم کاربر {user_id}: {e}")
            return False

    def is_premium_user(self, user_id):
        """
        بررسی اینکه آیا کاربر پرمیوم است یا خیر.

        Args:
            user_id: شناسه کاربر

        Returns:
            bool: True اگر کاربر پرمیوم باشد، در غیر این صورت False
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT is_premium FROM users WHERE id_user = ?",
                (user_id,)
            )
            result = cursor.fetchone()
            if result:
                return bool(result[0])
            return False
        except Exception as e:
            logger.error(f"خطا در بررسی وضعیت پرمیوم کاربر {user_id}: {e}")
            return False

    def check_user_exists_by_id(self, user_id):
        """
        بررسی وجود کاربر با شناسه مشخص.

        Args:
            user_id: شناسه کاربر

        Returns:
            bool: True اگر کاربر وجود داشته باشد، در غیر این صورت False
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE id_user = ? LIMIT 1", (user_id,))
            return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"خطا در بررسی وجود کاربر: {e}")
            return False

    def get_user_id_by_username(self, username):
        """
        دریافت شناسه کاربر بر اساس نام کاربری.

        Args:
            username: نام کاربری (بدون علامت @)

        Returns:
            int: شناسه کاربر یا None اگر کاربر یافت نشود
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id_user FROM users WHERE username = ? LIMIT 1", (username,))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"خطا در دریافت شناسه کاربر بر اساس نام کاربری: {e}")
            return None

    def get_user_info(self, user_id):
        """
        دریافت اطلاعات کاربر بر اساس شناسه او.

        Args:
            user_id: شناسه کاربر

        Returns:
            dict: دیکشنری حاوی اطلاعات کاربر یا None اگر کاربر یافت نشود
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT first_name, last_name, username, is_premium FROM users WHERE id_user = ?",
                (user_id,)
            )
            result = cursor.fetchone()

            if result:
                return {
                    'first_name': result[0],
                    'last_name': result[1],
                    'username': result[2],
                    'is_premium': bool(result[3])
                }
            return None
        except Exception as e:
            logger.error(f"خطا در دریافت اطلاعات کاربر: {e}")
            return None
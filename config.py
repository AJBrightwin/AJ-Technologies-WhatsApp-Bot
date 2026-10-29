"""
Settings for the AJ Technologies WhatsApp bot.

Secrets come from environment variables (Render -> Environment, or a local .env file).
Business details, services and call times are set here in plain Python, so you can
change them without touching the bot logic.
"""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env', encoding='utf-8-sig')


def env(name, default=''):
    return (os.getenv(name) or default).strip()


def env_int(name, default):
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def digits(value):
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


# ---------------------------------------------------------------------------
# Meta (WhatsApp Cloud API)
# ---------------------------------------------------------------------------
META_ACCESS_TOKEN = env('META_ACCESS_TOKEN')          # permanent System User token
PHONE_NUMBER_ID = env('PHONE_NUMBER_ID')              # WhatsApp -> API Setup -> Phone number ID
VERIFY_TOKEN = env('VERIFY_TOKEN')                    # optional: if set, Meta's verify word must match it
APP_SECRET = env('APP_SECRET')                        # Meta app -> Settings -> Basic -> App secret
GRAPH_VERSION = env('WA_GRAPH_VERSION', 'v23.0')
GRAPH_BASE = env('WA_GRAPH_BASE', 'https://graph.facebook.com').rstrip('/')

# Your own WhatsApp number: gets the alerts and reminders (country code, digits only)
ADMIN_WA_NUMBER = digits(env('ADMIN_WA_NUMBER', '919092631501'))
# Approved "utility" template used for alerts when you have not messaged the bot in 24 hours
ADMIN_TEMPLATE_NAME = env('ADMIN_TEMPLATE_NAME', 'aj_admin_alert')
ADMIN_TEMPLATE_LANG = env('ADMIN_TEMPLATE_LANG', 'en')

# ---------------------------------------------------------------------------
# Database (same Supabase database as the website and the dashboard)
# ---------------------------------------------------------------------------
DATABASE_URL = env('DATABASE_URL')
DATABASE_SSL = env('DATABASE_SSL', 'true').lower() == 'true'

# ---------------------------------------------------------------------------
# OpenAI (answers questions, understands any language, voice notes)
# ---------------------------------------------------------------------------
OPENAI_API_KEY = env('OPENAI_API_KEY')
OPENAI_MODEL = env('OPENAI_MODEL', 'gpt-4o-mini')
OPENAI_TRANSCRIBE_MODEL = env('OPENAI_TRANSCRIBE_MODEL', 'whisper-1')

# ---------------------------------------------------------------------------
# Jobs (reminders, follow-ups, broadcasts)
# ---------------------------------------------------------------------------
CRON_SECRET = env('CRON_SECRET')                      # protects /cron/tick (for an uptime pinger)
RUN_WORKER = env('RUN_WORKER', 'true').lower() == 'true'
WORKER_SECONDS = max(10, env_int('WORKER_SECONDS', 20))
ENQUIRY_REMINDER_HOURS = env_int('ENQUIRY_REMINDER_HOURS', 20)   # remind you if still "New"
CALL_REMINDER_MINUTES = env_int('CALL_REMINDER_MINUTES', 60)     # remind you before a booked call
NUDGE_AFTER_HOURS = env_int('NUDGE_AFTER_HOURS', 22)             # remind a customer who stopped halfway
BROADCAST_PER_TICK = max(1, env_int('BROADCAST_PER_TICK', 20))

# Every schedule below uses India time (Asia/Kolkata), whatever time zone the server or database is in.
TZ = ZoneInfo('Asia/Kolkata')

# ---------------------------------------------------------------------------
# Upgrade v2: scheduled messages (India time)
# ---------------------------------------------------------------------------
DAILY_SUMMARY_AT = env('DAILY_SUMMARY_AT', '09:00')   # daily summary to AJ
WEEKLY_REPORT_WEEKDAY = env_int('WEEKLY_REPORT_WEEKDAY', 0)   # 0 = Monday, sent with the daily summary
FOLLOWUP_AFTER_DAYS = env_int('FOLLOWUP_AFTER_DAYS', 7)       # enquiry still New / Quoted after this many days
FOLLOWUP_MAX_AGE_DAYS = env_int('FOLLOWUP_MAX_AGE_DAYS', 30)  # never follow up enquiries older than this
FOLLOWUP_HOURS = (10, 19)                                      # only send follow-ups between 10 AM and 7 PM
RENEWAL_HOURS = (10, 19)                                       # renewal reminders between 10 AM and 7 PM
ACK_WEBSITE_ENQUIRIES = env('ACK_WEBSITE_ENQUIRIES', 'true').lower() == 'true'
ACK_HOURS = (7, 22)                                            # "thank you" for website enquiries: 7 AM to 10 PM
ACK_MAX_AGE_HOURS = 12                                         # skip it if the enquiry is older than this

# Approved Meta templates for messages the bot starts (customer has not written in 24 hours)
TPL_ENQUIRY_RECEIVED = env('TPL_ENQUIRY_RECEIVED', 'enquiry_received')
TPL_LEAD_FOLLOWUP = env('TPL_LEAD_FOLLOWUP', 'lead_followup')
TPL_PROJECT_UPDATE = env('TPL_PROJECT_UPDATE', 'project_update')
TPL_RENEWAL_REMINDER = env('TPL_RENEWAL_REMINDER', 'renewal_reminder')
TPL_TICKET_UPDATE = env('TPL_TICKET_UPDATE', 'ticket_update')
TPL_LANG = env('TPL_LANG', 'en')
TPL_LANG_TA = env('TPL_LANG_TA', '')                 # e.g. "ta" if you also approved Tamil versions

# ---------------------------------------------------------------------------
# Upgrade v3: AI conversation, files to AJ, subscription reminders
# ---------------------------------------------------------------------------
# true = customers chat with the AI in their own words (menus only when they ask, or if OpenAI is down)
AI_CONVERSATION = env('AI_CONVERSATION', 'true').lower() == 'true'
# Approved template with a DOCUMENT header, used to send a customer's file to AJ when his 24 hours are closed
TPL_ADMIN_FILE = env('TPL_ADMIN_FILE', 'aj_file_alert')
# Your own subscriptions (Render, Supabase, Meta, OpenAI, domain ...): reminder every day at this time (India time),
# starting this many days before the renewal date, until you tell the bot it is renewed
SUBS_ALERT_AT = env('SUBS_ALERT_AT', '12:00')
SUBS_ALERT_DAYS = env_int('SUBS_ALERT_DAYS', 7)

# ---------------------------------------------------------------------------
# Business details (used in replies and by the AI)
# ---------------------------------------------------------------------------
BOT_NAME = 'AJ Technologies Assistant'
VERSION = 'v3.2'                                      # shown at /health, so you can see which code Render runs
OWNER_NAME = env('OWNER_NAME', 'A.J. Brightwin')      # Founder, CEO and Owner (the bot says this when asked)
COMPANY = 'AJ Technologies'
TAGLINE = 'We Build, You Grow'
SITE_URL = env('SITE_URL', 'https://ajtechnologiesltd.com').rstrip('/')
DASHBOARD_URL = env('DASHBOARD_URL', 'https://admin.ajtechnologiesltd.com').rstrip('/')
PORTFOLIO_URL = f'{SITE_URL}/portfolio/'
CONTACT_URL = f'{SITE_URL}/contact/'
PRIVACY_URL = f'{SITE_URL}/privacy-policy/'
TERMS_URL = f'{SITE_URL}/terms-and-conditions/'
DELIVERY_URL = f'{SITE_URL}/service-delivery-policy/'
PHONE_DISPLAY = '+91 90926 31501'
EMAIL = 'ajtechnologieslimited@gmail.com'
LOCATION = 'Thoothukudi, Tamil Nadu, India'
INSTAGRAM = 'https://www.instagram.com/aj_technologies_ltd_/'
YOUTUBE = 'https://www.youtube.com/@AJ_Technologies'
GOOGLE_REVIEW_URL = env('GOOGLE_REVIEW_URL')          # optional: your Google review link
SUPABASE_URL = env('SUPABASE_URL', 'https://idmzhpvqafsbppahkcum.supabase.co').rstrip('/')
IMAGE_BUCKET = env('SUPABASE_STORAGE_BUCKET', 'project-images')

# Services shown in the bot menu: code -> English name (Tamil + details live in texts.py)
SERVICES = [
    ('web', 'Business Websites'),
    ('shop', 'E-commerce Stores'),
    ('landing', 'Landing Pages'),
    ('redesign', 'Website Redesign'),
    ('saas', 'Web Apps & SaaS'),
    ('app', 'Mobile Apps'),
    ('mkt', 'Digital Marketing & SEO'),
    ('wa', 'WhatsApp Business'),
    ('care', 'Domain, Hosting & AMC'),
]

# Services the customer can choose in an enquiry (same as the website contact form)
ENQUIRY_SERVICES = [
    ('web', 'Business Websites'),
    ('shop', 'E-commerce Stores'),
    ('saas', 'Web Apps & SaaS'),
    ('app', 'Mobile Apps'),
    ('mkt', 'Marketing'),
    ('other', 'Something else'),
]

# Call booking: days ahead to offer, days you take calls (0 = Monday ... 6 = Sunday) and times
CALL_DAYS_AHEAD = 7
CALL_WEEKDAYS = {0, 1, 2, 3, 4, 5}                    # Monday to Saturday
CALL_SLOTS = ['10:00', '11:00', '12:00', '14:00', '15:00', '16:00', '17:00', '18:00', '19:00']
CALL_MIN_NOTICE_MINUTES = 60                           # no slot sooner than this


def check():
    """Problems that stop the bot from working, as a list of plain sentences."""
    missing = [name for name in ('META_ACCESS_TOKEN', 'PHONE_NUMBER_ID', 'APP_SECRET', 'DATABASE_URL')
               if not globals()[name]]
    return [f'{name} is not set.' for name in missing]
# AJ Technologies Assistant (WhatsApp bot)

The official WhatsApp Cloud API bot for AJ Technologies. It answers customers in their own language,
collects quote requests (saved to the same Supabase table as the website), shows real portfolio projects,
books calls, collects reviews, handles STOP / START, alerts AJ, and sends offer broadcasts queued from
the admin dashboard.

## Files

| File | What it does |
|---|---|
| `app.py` | Web server: `/webhook` (Meta), `/health`, `/cron/tick` |
| `bot.py` | The conversation: menu, services, prices, quote request, portfolio, calls, reviews, language |
| `ai.py` | OpenAI: answers, understanding replies, voice notes, translation |
| `texts.py` | Everything the bot says (English, Tamil, Tanglish). Edit replies here |
| `db.py` | All database queries |
| `whatsapp.py` | Sending messages through Meta |
| `jobs.py` | Alerts and reminders to AJ, follow-ups, broadcasts |
| `config.py` | Settings: business details, services, call times |
| `supabase_whatsapp.sql` | Run once in Supabase (creates the wa_* tables) |

## Run on your computer

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      (then fill in .env)
python app.py
```

## Render

* Build command: `pip install -r requirements.txt`
* Start command: `gunicorn app:app`
* Health check path: `/health`
* Environment: every name in `.env.example`

## Meta templates

**aj_admin_alert** (Utility, English)

```
Hello AJ, you have a new update from your AJ Technologies Assistant.

{{1}}

Customer: {{2}}
Phone: {{3}}

Please open your admin dashboard to see the details.
```

**review_request** (Utility, English, quick reply button "Write a review")

```
Hello {{1}}, thank you for choosing AJ Technologies for your project. We would be grateful if you could share a short review of your experience. Tap the button below to start.
```

## Changing things

* Replies: `texts.py`
* Call days and times: `CALL_WEEKDAYS` and `CALL_SLOTS` in `config.py`
* Services in the menu: `SERVICES` in `config.py` (+ their texts in `texts.py`)

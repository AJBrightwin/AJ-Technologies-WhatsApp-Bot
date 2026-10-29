"""
AJ Technologies WhatsApp bot: the web server Meta talks to.

    GET  /            simple "running" page
    GET  /health      health check for Render (database + settings)
    GET  /webhook     Meta's one-time verification (VERIFY_TOKEN)
    POST /webhook     every incoming WhatsApp message and delivery receipt
    GET  /cron/tick   runs the reminder / broadcast jobs once (?key=CRON_SECRET)

Run on your computer:  python app.py
Run on Render:         gunicorn app:app   (settings in gunicorn.conf.py)
"""
import hashlib
import hmac
import json
import logging
import os

from flask import Flask, abort, jsonify, request

import bot
import config
import db
import jobs

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
log = logging.getLogger('bot.app')

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

log.info('AJ Technologies Assistant %s starting (AI conversation: %s)', config.VERSION, config.AI_CONVERSATION)
for problem in config.check():
    log.error('SETUP: %s Add it in Render > Environment (or in .env on your computer).', problem)
if not config.APP_SECRET:
    log.warning('SETUP: APP_SECRET is not set, so webhook signatures are not checked. Add it for safety.')
if not config.VERIFY_TOKEN:
    log.info('SETUP: VERIFY_TOKEN is not set, so any verify word typed in Meta is accepted (fine while APP_SECRET is set).')
if not config.OPENAI_API_KEY:
    log.warning('SETUP: OPENAI_API_KEY is not set. The bot works with buttons only (no AI answers, no voice notes).')


@app.get('/')
def home():
    return jsonify(ok=True, service=f'{config.BOT_NAME} (WhatsApp bot)', website=config.SITE_URL)


@app.get('/health')
def health():
    problems = config.check()
    try:
        db.ping()
        database = 'connected'
    except Exception as e:
        database = 'not reachable'
        problems.append(f'Database: {e.__class__.__name__}')
    return jsonify(ok=not problems, version=config.VERSION, ai_conversation=config.AI_CONVERSATION,
                   database=database, ai=bool(config.OPENAI_API_KEY),
                   signature_check=bool(config.APP_SECRET), problems=problems), (200 if not problems else 503)


@app.get('/webhook')
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token', '')
    challenge = request.args.get('hub.challenge', '')
    # VERIFY_TOKEN is optional: when it is empty, any word typed in Meta's "Verify token" box is accepted.
    # Messages are still protected by APP_SECRET (every message from Meta is signed with it).
    token_ok = hmac.compare_digest(token, config.VERIFY_TOKEN) if config.VERIFY_TOKEN else bool(token)
    if mode == 'subscribe' and token_ok:
        log.info('Webhook verified by Meta')
        return challenge, 200, {'Content-Type': 'text/plain'}
    log.warning('Webhook verification failed: the verify token does not match VERIFY_TOKEN')
    return 'Verification failed', 403


def signature_ok(raw):
    if not config.APP_SECRET:
        return True
    sent = request.headers.get('X-Hub-Signature-256', '')
    expected = 'sha256=' + hmac.new(config.APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, expected)


@app.post('/webhook')
def receive_webhook():
    raw = request.get_data()
    if not signature_ok(raw):
        log.warning('Webhook rejected: wrong signature (check APP_SECRET)')
        abort(403)
    try:
        payload = json.loads(raw.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return 'Bad request', 400
    if payload.get('object') == 'whatsapp_business_account':
        try:
            bot.process_payload(payload)
        except Exception:
            log.exception('Webhook processing failed')
    return 'OK', 200          # Meta only needs a quick OK; replies are sent in the background


@app.route('/cron/tick', methods=['GET', 'POST'])
def cron_tick():
    key = request.args.get('key') or request.headers.get('X-Cron-Key', '')
    if not config.CRON_SECRET or not hmac.compare_digest(key, config.CRON_SECRET):
        abort(403)
    result = jobs.tick()
    return jsonify(result), 200


jobs.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=False, use_reloader=False)
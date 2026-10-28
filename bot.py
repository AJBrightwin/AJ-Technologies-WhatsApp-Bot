"""
The conversation: menu, services, prices, quote requests (enquiries), portfolio,
call booking, reviews, language, opt-out, talking to the team and AI answers.

Where each customer is in a flow is saved in wa_contacts.state, so a restart
never loses their place.
"""
import logging
import re
import threading
from datetime import date, datetime, time as dtime, timedelta
from concurrent.futures import ThreadPoolExecutor

import ai
import config
import db
import whatsapp as wa
from texts import BUILTIN, LANG_NAMES, LANG_SET_OTHER, T, t, t_many

log = logging.getLogger('bot')

executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix='chat')
_locks = {}
_locks_guard = threading.Lock()


def _lock(wa_id):
    with _locks_guard:
        if len(_locks) > 5000:
            _locks.clear()
        return _locks.setdefault(wa_id, threading.Lock())


# ===========================================================================
# Small helpers
# ===========================================================================
def lang(c):
    return (c.get('language') or 'en') if c else 'en'


def display_name(c):
    return (c.get('name') or c.get('profile_name') or '').strip()


def friendly(c):
    name = display_name(c)
    return name.split()[0] if name else ('there' if lang(c) == 'en' else '')


def tidy(text):
    """Remove the gap left by an empty {name}: "Hi !" -> "Hi!"."""
    return re.sub(r'[ \t]+([!,.?])', r'\1', text).replace('  ', ' ')


def phone_display(number):
    d = config.digits(number)
    if len(d) == 12 and d.startswith('91'):
        return f'+91 {d[2:7]} {d[7:]}'
    return f'+{d}' if d else ''


def normalise_phone(number):
    d = config.digits(number)
    if len(d) == 10:
        d = '91' + d
    if len(d) == 11 and d.startswith('0'):
        d = '91' + d[1:]
    return d if 10 <= len(d) <= 15 else ''


def say(c, key, **values):
    return wa.send_text(c['wa_id'], tidy(t(lang(c), key, **values)))


def text_to(c, text):
    return wa.send_text(c['wa_id'], tidy(text))


def labels(c, keys):
    return t_many(lang(c), keys)


def buttons(c, body, items, header='', footer=''):
    """items: [(id, text_key or ('literal', text))]"""
    keys = [k for _, k in items if not isinstance(k, tuple)]
    resolved = iter(labels(c, keys))
    final = [(bid, k[1] if isinstance(k, tuple) else next(resolved)) for bid, k in items]
    return wa.send_buttons(c['wa_id'], tidy(body), final, header=header, footer=footer)


def set_state(c, state):
    fresh = db.update_contact(c['wa_id'], state=state or {})
    if fresh:
        c.update(fresh)


def clear_state(c):
    if c.get('state'):
        set_state(c, {})


def now_ist():
    return datetime.now(config.TZ)


CANCEL_WORDS = {'cancel', 'exit', 'quit', 'stop it', 'venaam', 'venam', 'vendam', 'வேண்டாம்', 'ரத்து',
                'cancel it', 'no thanks', 'not now'}
MENU_WORDS = {'menu', 'main menu', 'options', 'மெனு', 'help', 'start over', 'restart'}
GREETINGS = re.compile(r'^\s*(hi+|hello+|hey+|hai+|helo|hlo|vanakkam|vanakam|வணக்கம்|நமஸ்காரம்|namaste|namaskar|'
                       r'good\s*(morning|afternoon|evening)|gm)(?=[\s!.,🙏👋😊]|$)[\s!.,🙏👋😊]*'
                       r'(sir|madam|mam|anna|akka|bro|team|aj)?[\s!.,🙏👋😊]*$', re.I)
REVIEW_WORDS = {'write a review', 'review', 'leave a review', '⭐ write a review', 'review ezhudhu', '⭐ review ezhudhu',
                'விமர்சனம் எழுது', '⭐ விமர்சனம் எழுது'}
STOP_WORDS = {'stop', 'unsubscribe', 'stop offers', 'நிறுத்து'}
START_WORDS = {'start', 'subscribe', 'start offers'}


def plain(text):
    return re.sub(r'[\s!.]+$', '', (text or '').strip().lower())


# ===========================================================================
# Entry point (called from app.py for every webhook)
# ===========================================================================
def process_payload(payload):
    for entry in payload.get('entry') or []:
        for change in entry.get('changes') or []:
            value = change.get('value') or {}
            for status in value.get('statuses') or []:
                try:
                    handle_status(status)
                except Exception:
                    log.exception('Status update failed')
            profiles = {c.get('wa_id'): (c.get('profile') or {}).get('name', '') for c in value.get('contacts') or []}
            for message in value.get('messages') or []:
                wa_id = config.digits(message.get('from'))
                if wa_id:
                    executor.submit(_safe_handle, wa_id, profiles.get(message.get('from'), ''), message)
            for err in value.get('errors') or []:
                log.warning('WhatsApp webhook error: %s', err)


def handle_status(status):
    wamid = status.get('id')
    state = status.get('status')
    if not wamid or not state:
        return
    error = ''
    if status.get('errors'):
        e = status['errors'][0]
        error = f"{e.get('code', '')}: {e.get('title') or e.get('message', '')}"
        details = (e.get('error_data') or {}).get('details')
        if details:
            error += f' ({details})'
    db.update_message_status(wamid, state, error)


def _safe_handle(wa_id, profile_name, message):
    with _lock(wa_id):
        c = None
        try:
            c = handle_message(wa_id, profile_name, message)
        except Exception:
            log.exception('Could not handle message from %s', wa_id)
            try:
                c = c or db.get_contact(wa_id)
                if c and c.get('bot_enabled', True) and wa_id != config.ADMIN_WA_NUMBER:
                    say(c, 'error')
            except Exception:
                log.exception('Could not send the error reply')


def parse(message):
    """Turn a WhatsApp message into (kind, text, action_id, media)."""
    kind = message.get('type', 'unknown')
    media = {}
    text, action = '', None
    if kind == 'text':
        text = (message.get('text') or {}).get('body', '')
    elif kind == 'interactive':
        inter = message.get('interactive') or {}
        reply = inter.get('button_reply') or inter.get('list_reply') or {}
        action, text = reply.get('id'), reply.get('title', '')
    elif kind == 'button':                       # a quick-reply button on a template message
        btn = message.get('button') or {}
        action, text = btn.get('payload') or None, btn.get('text', '')
        if action and ':' not in action:         # a button without our own id: treat it like typed text
            text, action = text or action, None
    elif kind in ('image', 'audio', 'video', 'document', 'sticker'):
        m = message.get(kind) or {}
        media = {'id': m.get('id', ''), 'mime': m.get('mime_type', ''), 'filename': m.get('filename', '')}
        text = m.get('caption', '')
    elif kind == 'location':
        loc = message.get('location') or {}
        text = '📍 ' + ', '.join(str(x) for x in (loc.get('name'), loc.get('address'),
                                                 f"{loc.get('latitude')},{loc.get('longitude')}") if x)
    elif kind == 'contacts':
        names = [((x.get('name') or {}).get('formatted_name') or '') for x in message.get('contacts') or []]
        text = '👤 ' + ', '.join(n for n in names if n)
    elif kind == 'reaction':
        text = (message.get('reaction') or {}).get('emoji', '')
    elif kind == 'request_welcome':
        text = 'hi'
    return kind, (text or '').strip(), action, media


def handle_message(wa_id, profile_name, message):
    kind, text, action, media = parse(message)
    try:
        sent_at = datetime.fromtimestamp(int(message.get('timestamp')), tz=config.TZ)
    except (TypeError, ValueError):
        sent_at = db.now()
    is_admin = wa_id == config.ADMIN_WA_NUMBER
    body = text if kind not in ('audio',) else ''
    if kind == 'interactive' and text:
        body = f'[{text}]'
    c, msg_id = db.save_inbound(wa_id, profile_name, message.get('id'), kind, body, sent_at,
                                media.get('id', ''), media.get('mime', ''), media.get('filename', ''),
                                count_unread=not is_admin)
    if c is None:
        log.info('Duplicate message %s ignored', message.get('id'))
        return None
    if db.now() - sent_at > timedelta(hours=23, minutes=30):
        return c                                  # too old to reply to
    if kind == 'reaction':
        return c
    wa.mark_read_and_typing(message.get('id'))

    if is_admin:
        admin_reply(c)
        return c
    if not c.get('bot_enabled', True):
        db.update_contact(wa_id, needs_reply=True)
        return c

    # voice notes become text
    if kind == 'audio':
        text = voice_to_text(media)
        if not text:
            say(c, 'voice_fail')
            return c
        db.set_message_body(msg_id, f'🎙️ {text}')

    step = (c.get('state') or {}).get('step')
    if text and not action and step not in NAME_LIKE_STEPS:
        update_language(c, text)

    first_time = c.get('last_outbound_at') is None

    if action:
        return handle_action(c, action)
    if kind in ('image', 'document', 'video', 'sticker', 'location', 'contacts'):
        return handle_media(c, kind, text, media)
    if kind not in ('text', 'audio', 'button', 'interactive', 'request_welcome'):
        say(c, 'unsupported')
        return c
    if not text:
        return c
    return handle_text(c, text, first_time)


def voice_to_text(media):
    if not ai.enabled() or not media.get('id'):
        return ''
    data, mime = wa.download_media(media['id'], max_bytes=24 * 1024 * 1024)
    if not data:
        return ''
    try:
        return ai.transcribe(data, mime or media.get('mime', 'audio/ogg'))
    except Exception as e:
        log.warning('Transcription failed: %s', e)
        return ''


# ===========================================================================
# Language
# ===========================================================================
SCRIPTS = [('ta', '஀', '௿'), ('hi', 'ऀ', 'ॿ'), ('ml', 'ഀ', 'ൿ'),
           ('te', 'ఀ', '౿'), ('kn', 'ಀ', '೿'), ('bn', 'ঀ', '৿'),
           ('gu', '઀', '૿'), ('pa', '਀', '੿'), ('or', '଀', '୿'),
           ('ar', '؀', 'ۿ'), ('si', '඀', '෿'), ('zh', '一', '鿿')]
TANGLISH = re.compile(r'\b(enna|ennaku|enakku|venum|vennum|venuma|epdi|eppadi|irukku|iruku|sollunga|solunga|'
                      r'pannunga|panna|pannanum|romba|nandri|illa|illai|aama|aamam|ungal|unga|naan|naanga|'
                      r'evlo|evvalavu|yevlo|kudunga|theriyum|seri|sari|vanakkam|kadai|seiyanum|pannuveengala|'
                      r'mudiyuma|vendum|thevai|engal|nalla|super ah|panrom|irukinga|irukeenga)\b', re.I)
HINGLISH = re.compile(r'\b(kya|hai|hain|kaise|kitna|chahiye|mujhe|aap|apka|nahi|haan|bhai|karna|kar|'
                      r'batao|kijiye|dijiye|accha|achha|theek)\b', re.I)


# answers like "Ravi Kumar", "Sri Murugan Traders, Thoothukudi" or an email say nothing about the language
NAME_LIKE_STEPS = {'name', 'business', 'email', 'phone', 'biz', 'rating', 'day', 'time'}


def script_language(text):
    counts = {}
    for ch in text:
        for code, lo, hi in SCRIPTS:
            if lo <= ch <= hi:
                counts[code] = counts.get(code, 0) + 1
                break
    return max(counts, key=counts.get) if counts else None


def update_language(c, text):
    if c.get('language_locked'):
        return
    code = script_language(text)
    if not code:
        words = re.findall(r"[A-Za-z']+", text)
        if len(words) < 2 and not TANGLISH.search(text):
            return                                       # "ok", "yes", a name: keep the current language
        if len(TANGLISH.findall(text)) >= 1 and not HINGLISH.search(text):
            code = 'tanglish'
        elif len(HINGLISH.findall(text)) >= 2:
            code = 'hinglish'
        elif len(words) >= 3 and ai.enabled():
            try:
                code = ai.detect_language(text)
            except Exception as e:
                log.info('Language check failed: %s', e)
                code = None
        else:
            code = 'en' if len(words) >= 3 else None
    if code and code != c.get('language'):
        fresh = db.update_contact(c['wa_id'], language=code)
        if fresh:
            c.update(fresh)


LANG_CHOICES = [('en', 'English', 'English'), ('ta', 'தமிழ்', 'Tamil'), ('tanglish', 'Tanglish', 'Tamil in English letters'),
                ('hi', 'हिन्दी', 'Hindi'), ('ml', 'മലയാളം', 'Malayalam'), ('te', 'తెలుగు', 'Telugu'),
                ('kn', 'ಕನ್ನಡ', 'Kannada'), ('hinglish', 'Hinglish', 'Hindi in English letters')]


def ask_language(c):
    auto, auto_d, button = labels(c, ['lang_auto', 'lang_auto_d', 'lang_button'])
    rows = [('lang:auto', auto, auto_d)] + [(f'lang:{code}', title, desc) for code, title, desc in LANG_CHOICES]
    wa.send_list(c['wa_id'], t(lang(c), 'lang_ask'), button, rows)


def set_language(c, code):
    if code == 'auto':
        db.update_contact(c['wa_id'], language_locked=False)
        c['language_locked'] = False
        say(c, 'lang_set_auto')
    elif code in LANG_NAMES:
        fresh = db.update_contact(c['wa_id'], language=code, language_locked=True)
        c.update(fresh or {})
        if code in BUILTIN:
            say(c, 'lang_set')
        else:
            text_to(c, ai.translate(LANG_SET_OTHER.format(language=LANG_NAMES[code]), code))
    else:
        return ask_language(c)
    send_menu(c)


# ===========================================================================
# Menu and simple answers
# ===========================================================================
MENU = [('m:services', 'm_services', 'm_services_d'), ('m:prices', 'm_prices', 'm_prices_d'),
        ('m:work', 'm_work', 'm_work_d'), ('m:quote', 'm_quote', 'm_quote_d'), ('m:call', 'm_call', 'm_call_d'),
        ('m:team', 'm_team', 'm_team_d'), ('m:review', 'm_review', 'm_review_d'), ('m:lang', 'm_lang', 'm_lang_d')]


def send_menu(c, body=None):
    keys = [k for row in MENU for k in row[1:]] + ['menu_button', 'menu_section']
    got = labels(c, keys)
    rows = [(MENU[i][0], got[i * 2], got[i * 2 + 1]) for i in range(len(MENU))]
    wa.send_list(c['wa_id'], tidy(body or t(lang(c), 'menu_body')), got[-2], rows, section=got[-1],
                 footer=f'{config.COMPANY} · {config.TAGLINE}')


def welcome(c):
    send_menu(c, t(lang(c), 'welcome', name=friendly(c)))


def show_prices(c):
    buttons(c, t(lang(c), 'prices'), [('m:quote', 'b_quote'), ('m:menu', 'b_menu')])


def show_services(c, code=None):
    codes = [s for s, _ in config.SERVICES]
    if code in codes:
        body = t(lang(c), f'svc_{code}_x') + '\n\n' + t(lang(c), 'svc_all_include')
        return buttons(c, body, [('m:quote', 'b_quote'), ('m:services', 'b_more_svc'), ('m:menu', 'b_menu')])
    keys = [k for s in codes for k in (f'svc_{s}', f'svc_{s}_d')] + ['svc_button']
    got = labels(c, keys)
    rows = [(f'svc:{s}', got[i * 2], got[i * 2 + 1]) for i, s in enumerate(codes)]
    wa.send_list(c['wa_id'], t(lang(c), 'svc_intro'), got[-1], rows, footer=config.SITE_URL.replace('https://', ''))


def talk_to_team(c, reason=''):
    if c.get('needs_reply') and db.recent_alert('human_request', c['wa_id'], 12):
        return say(c, 'human_again')
    db.update_contact(c['wa_id'], needs_reply=True)
    c['needs_reply'] = True
    name = display_name(c) or 'A customer'
    db.queue_alert('human_request', f'{name} wants to talk to the team' + (f': {reason}' if reason else ''),
                   wa_id=c['wa_id'], customer_name=display_name(c), customer_phone=phone_display(c['wa_id']),
                   detail=f'Reason: {reason}' if reason else '')
    say(c, 'human')


# ===========================================================================
# Portfolio
# ===========================================================================
def project_image_url(p):
    path = (p.get('image_path') or '').strip()
    if not path:
        return ''
    url = path if path.startswith(('http://', 'https://')) else \
        f'{config.SUPABASE_URL}/storage/v1/object/public/{config.IMAGE_BUCKET}/{path}'
    return url if re.search(r'\.(jpe?g|png)(\?|$)', url, re.I) else ''   # WhatsApp images: JPG / PNG only


def project_text(c, p, field):
    if lang(c) == 'ta' and (p.get(f'{field}_ta') or '').strip():
        return p[f'{field}_ta']
    value = p.get(f'{field}_en') or ''
    return value if lang(c) in ('en', 'ta', 'tanglish') else ai.translate(value, lang(c))


def show_portfolio(c):
    projects = db.real_projects(10)
    if not projects:
        return buttons(c, t(lang(c), 'pf_none', url=config.PORTFOLIO_URL), [('m:quote', 'b_quote'), ('m:menu', 'b_menu')])
    rows = [(f'pf:{p["id"]}', project_text(c, p, 'title'), project_text(c, p, 'business_type')) for p in projects]
    body = t(lang(c), 'pf_intro') + '\n\n' + t(lang(c), 'pf_all', url=config.PORTFOLIO_URL)
    wa.send_list(c['wa_id'], body, t(lang(c), 'pf_button'), rows)


def show_project(c, project_id):
    p = db.get_project(project_id) if str(project_id).isdigit() else None
    if not p:
        return show_portfolio(c)
    live = t(lang(c), 'pf_live', url=p['live_url']) if p.get('live_url') else t(lang(c), 'pf_soon')
    caption = f"*{project_text(c, p, 'title')}*\n{project_text(c, p, 'business_type')}\n\n{project_text(c, p, 'built')}\n\n{live}"
    image = project_image_url(p)
    if image:
        _, error = wa.send_image(c['wa_id'], image, caption)
        if error:
            text_to(c, caption)
    else:
        text_to(c, caption)
    buttons(c, t(lang(c), 'pf_next'), [('m:quote', 'b_quote'), ('pf:more', 'b_more_projects'), ('m:menu', 'b_menu')])


# ===========================================================================
# Flows: shared parts
# ===========================================================================
def flow(c):
    st = c.get('state') or {}
    return st.get('flow'), st


def answer_question_mid_flow(c, text, note, image=None):
    """Answer a question asked in the middle of a flow, so the chat feels natural."""
    if not ai.enabled():
        return False
    try:
        reply, _ = ai.chat(c, db.recent_messages(c['wa_id']), lang(c), mid_flow_note=note, image=image)
    except Exception as e:
        log.warning('AI mid-flow answer failed: %s', e)
        return False
    if reply:
        text_to(c, reply)
        return True
    return False


def understand(c, step, question_key, text):
    """What did the customer mean? AI first, simple rules if the AI is unavailable."""
    if ai.enabled():
        try:
            recent = '\n'.join(f"{'Customer' if m['direction'] == 'in' else 'Bot'}: {m['body'][:200]}"
                               for m in db.recent_messages(c['wa_id'], 6)[:-1])
            got = ai.extract(step, T[question_key]['en'], text, lang(c), recent)
            if got:
                return got
        except Exception as e:
            log.warning('AI extract failed: %s', e)
    return simple_understand(step, text)


SERVICE_WORDS = [
    ('shop', r'e-?commerce|online\s*(store|shop)|store|shop|sell\s*online|ஆன்லைன்|kadai|கடை'),
    ('app', r'mobile|android|ios|apps?\b|application|ஆப்'),
    ('saas', r'saas|software|portal|web\s*app|billing|crm|erp|dashboard|booking\s*system'),
    ('mkt', r'seo|marketing|google|instagram|facebook|social|ads?\b|youtube|மார்க்கெட்'),
    ('web', r'web\s*site|website|site|landing|redesign|இணைய|web'),
]


def simple_understand(step, text):
    low = text.lower().strip()
    if plain(low) in CANCEL_WORDS:
        return {'intent': 'cancel', 'value': None, 'fields': {}}
    if '?' in low and step not in ('message', 'review_text', 'topic'):
        return {'intent': 'question', 'value': None, 'fields': {}}
    skip = plain(low) in {'skip', 'no', 'none', 'nil', 'na', 'n/a', 'illa', 'illai', 'இல்லை', 'தவிர்', '-'}
    value = None
    if step == 'name':
        if re.fullmatch(r"[^\d@?]{2,60}", text.strip()) and len(text.split()) <= 5:
            value = ' '.join(w[:1].upper() + w[1:] for w in text.split())
    elif step in ('business', 'topic', 'review_name'):
        value = '' if skip else text.strip()
    elif step == 'services':
        found = [code for code, pattern in SERVICE_WORDS if re.search(pattern, low)]
        value = found or ['other']
    elif step == 'timeline':
        if re.search(r'asap|urgent|immediate|soon|seekiram|udane|உடனே|விரைவ|now|quick', low):
            value = 'asap'
        elif re.search(r'explor|not sure|just|summa|சும்மா|later|no hurry', low):
            value = 'explore'
        elif re.search(r'[23]\s*(-|to)?\s*(months|maasam)|three|two|1\s*-\s*3', low):
            value = '3m'
        elif re.search(r'month|maasam|மாத|week|vaaram', low):
            value = '1m'
    elif step == 'method':
        if re.search(r'whats\s*app|wa\b|வாட்ஸ்', low):
            value = 'whatsapp'
        elif re.search(r'call|phone|போன்|அழைப்', low):
            value = 'call'
        elif re.search(r'e-?mail|mail|மின்னஞ்சல்', low):
            value = 'email'
    elif step == 'email':
        m = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
        value = m.group(0) if m else ('' if skip else None)
    elif step == 'phone':
        d = config.digits(text)
        value = d if len(d) >= 10 else None
    elif step in ('message', 'review_text'):
        value = '' if (skip and step == 'message') else text.strip()
    elif step == 'rating':
        m = re.search(r'[1-5]', low)
        stars = text.count('⭐') or text.count('★')
        value = int(m.group(0)) if m else (min(stars, 5) if stars else None)
    elif step in ('day', 'time'):
        value = parse_when(low)
    elif step == 'review_biz':
        value = {'business': '', 'location': ''} if skip else split_business(text)
    if value in (None, [], {}):
        return {'intent': 'other', 'value': None, 'fields': {}}
    return {'intent': 'answer', 'value': value, 'fields': {}}


def split_business(text):
    parts = [p.strip() for p in re.split(r',|\n', text) if p.strip()]
    if len(parts) >= 2:
        return {'business': ', '.join(parts[:-1]), 'location': parts[-1]}
    return {'business': text.strip(), 'location': ''}


def parse_when(low):
    today = now_ist().date()
    out = {'date': '', 'time': ''}
    if re.search(r'today|indru|inniku|இன்று', low):
        out['date'] = today.isoformat()
    elif re.search(r'day after|naalai\s*marunaal|நாளை மறுநாள்', low):
        out['date'] = (today + timedelta(days=2)).isoformat()
    elif re.search(r'tomorrow|tmrw|naalai|nalaiku|நாளை', low):
        out['date'] = (today + timedelta(days=1)).isoformat()
    else:
        days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        for i, d in enumerate(days):
            if re.search(rf'\b{d}', low):
                ahead = (i - today.weekday()) % 7 or 7
                out['date'] = (today + timedelta(days=ahead)).isoformat()
                break
    m = re.search(r'\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m|p\.m)?\b', low)
    if m and (m.group(3) or m.group(2) or 'mani' in low or 'o clock' in low):
        h, mins = int(m.group(1)), int(m.group(2) or 0)
        ampm = (m.group(3) or '').replace('.', '')
        if ampm == 'pm' and h < 12:
            h += 12
        if ampm == 'am' and h == 12:
            h = 0
        if not ampm and 1 <= h <= 7:
            h += 12                                    # "3 o'clock" for a call means 3 PM
        if 0 <= h <= 23 and 0 <= mins <= 59:
            out['time'] = f'{h:02d}:{mins:02d}'
    return out if (out['date'] or out['time']) else None


def valid_name(value):
    value = ' '.join(str(value or '').split())
    if not value or len(value) > 60 or len(value.split()) > 6 or not re.search(r'[^\W\d_]', value) or '@' in value:
        return ''
    return value


EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')


# ===========================================================================
# Enquiry (quote request) flow
# ===========================================================================
ENQ_STEPS = ['name', 'business', 'services', 'timeline', 'method', 'email', 'phone', 'message', 'confirm']
ENQ_QUESTION = {'name': 'ask_name', 'business': 'ask_business', 'services': 'ask_services', 'timeline': 'ask_timeline',
                'method': 'ask_method', 'email': 'ask_email_optional', 'phone': 'ask_phone_type',
                'message': 'ask_message', 'confirm': 'summary'}
SVC_NAMES = dict(config.ENQUIRY_SERVICES)
TIMELINES = ('asap', '1m', '3m', 'explore')
METHODS = ('whatsapp', 'call', 'email')


def start_enquiry(c, prefill=None, intro=True):
    data = {'name': c.get('name') or '', 'business': c.get('business_name') or '', 'email': c.get('email') or '',
            'services': [], 'phone': c['wa_id'], 'attachments': 0}
    done = [s for s, k in (('name', 'name'), ('business', 'business'), ('email', 'email')) if data[k]]
    state = {'flow': 'enquiry', 'data': data, 'done': done, 'started': db.now().isoformat()}
    apply_enquiry_fields(state, prefill or {})
    if intro:
        say(c, 'enq_start')
    set_state(c, state)
    ask_enquiry_step(c, state)


def apply_enquiry_fields(state, fields):
    """Use details the customer already gave (e.g. "I need an online store for my bakery, I'm Ravi")."""
    data, done = state['data'], state.setdefault('done', [])

    def mark(step):
        if step not in done:
            done.append(step)
    name = valid_name(fields.get('name'))
    if name and 'name' not in done:
        data['name'] = name
        mark('name')
    biz = str(fields.get('business_name') or '').strip()
    if biz and 'business' not in done:
        data['business'] = biz[:160]
        mark('business')
    svcs = [s for s in (fields.get('services') or []) if s in SVC_NAMES]
    if svcs and 'services' not in done:
        data['services'] = list(dict.fromkeys(data['services'] + svcs))
        mark('services')
    if fields.get('timeline') in TIMELINES and 'timeline' not in done:
        data['timeline'] = fields['timeline']
        mark('timeline')
    if fields.get('contact_method') in METHODS and 'method' not in done:
        data['method'] = fields['contact_method']
        mark('method')
    email = str(fields.get('email') or '').strip()
    if email and EMAIL_RE.match(email) and 'email' not in done:
        data['email'] = email[:254]
        mark('email')
    msg = str(fields.get('message') or '').strip()
    if msg and not data.get('message'):
        data['message'] = msg[:500]                     # still asked, so they can add more


def next_enquiry_step(state):
    data, done = state['data'], state['done']
    if data.get('method') == 'email' and not data.get('email') and 'email' in done:
        done.remove('email')
    for step in ENQ_STEPS:
        if step not in done:
            return step
    return 'confirm'


def service_rows(c, exclude=()):
    keys = [f'svc_{code}' if f'svc_{code}' in T else 'svc_other' for code, _ in config.ENQUIRY_SERVICES]
    got = labels(c, keys)
    return [(f'enq:svc:{code}', got[i], '') for i, (code, _) in enumerate(config.ENQUIRY_SERVICES) if code not in exclude]


def service_label(c, code):
    key = f'svc_{code}' if f'svc_{code}' in T else 'svc_other'
    return t(lang(c), key)


def ask_enquiry_step(c, state, step=None):
    step = step or next_enquiry_step(state)
    state['step'] = step
    set_state(c, state)
    data, L = state['data'], lang(c)
    if step == 'name':
        profile = (c.get('profile_name') or '').strip()
        if valid_name(profile):
            return buttons(c, t(L, 'ask_name_profile'), [('enq:name:profile', ('literal', f'✅ {profile}'))])
        return say(c, 'ask_name')
    if step == 'business':
        return buttons(c, t(L, 'ask_business'), [('enq:skip', 'b_skip')])
    if step == 'services':
        rows = service_rows(c, exclude=data['services'])
        return wa.send_list(c['wa_id'], t(L, 'ask_services'), t(L, 'ask_services_button'), rows)
    if step == 'timeline':
        got = labels(c, [f'tl_{x}' for x in TIMELINES])
        return wa.send_list(c['wa_id'], t(L, 'ask_timeline'), t(L, 'ask_timeline_button'),
                            [(f'enq:tl:{x}', got[i], '') for i, x in enumerate(TIMELINES)])
    if step == 'method':
        return buttons(c, t(L, 'ask_method'), [(f'enq:cm:{m}', f'cm_{m}') for m in METHODS])
    if step == 'email':
        if data.get('method') == 'email':
            return say(c, 'ask_email_required')
        return buttons(c, t(L, 'ask_email_optional'), [('enq:skip', 'b_skip')])
    if step == 'phone':
        if state.get('typing_phone'):
            return say(c, 'ask_phone_type')
        return buttons(c, t(L, 'ask_phone', phone=phone_display(data['phone'])),
                       [('enq:phone:yes', 'b_yes'), ('enq:phone:other', 'b_other_number')])
    if step == 'message':
        return buttons(c, t(L, 'ask_message'), [('enq:skip', 'b_skip')])
    return send_summary(c, state)


def send_summary(c, state):
    data, L = state['data'], lang(c)
    dash = t(L, 'not_given')
    services = ', '.join(service_label(c, s) for s in data.get('services') or []) or dash
    body = t(L, 'summary', name=data.get('name') or dash, business=data.get('business') or dash, services=services,
             timeline=t(L, f"tl_{data['timeline']}") if data.get('timeline') else dash,
             method=t(L, f"cm_{data['method']}") if data.get('method') else dash,
             phone=phone_display(data.get('phone')) or dash, email=data.get('email') or dash,
             message=(data.get('message') or dash)[:400])
    state['step'] = 'confirm'
    set_state(c, state)
    buttons(c, body, [('enq:submit', 'b_submit'), ('enq:edit', 'b_edit'), ('enq:cancel', 'b_cancel')])


def enquiry_answer(c, state, step, value):
    """Save one answer. Returns an error text key when the value is not valid."""
    data, done = state['data'], state['done']
    if step == 'name':
        value = valid_name(value)
        if not value:
            return 'bad_name'
        data['name'] = value
    elif step == 'business':
        data['business'] = str(value or '').strip()[:160]
    elif step == 'services':
        codes = [v for v in (value if isinstance(value, list) else [value]) if v in SVC_NAMES]
        if not codes:
            return 'ask_services'
        data['services'] = list(dict.fromkeys(data['services'] + codes))
        state['step'] = 'services_more'
        set_state(c, state)
        added = ', '.join(service_label(c, s) for s in codes)
        if len(data['services']) >= len(SVC_NAMES):
            done.append('services')
            return None
        buttons(c, t(lang(c), 'svc_added', svc=added), [('enq:svc:more', 'b_add_more'), ('enq:svc:done', 'b_done')])
        return 'wait'
    elif step == 'timeline':
        if value not in TIMELINES:
            return 'ask_timeline'
        data['timeline'] = value
    elif step == 'method':
        if value not in METHODS:
            return 'ask_method'
        data['method'] = value
        if value == 'email' and not data.get('email') and 'email' in done:
            done.remove('email')
    elif step == 'email':
        value = str(value or '').strip()
        if not value and data.get('method') == 'email':
            return 'ask_email_required'
        if value and not EMAIL_RE.match(value):
            return 'bad_email'
        data['email'] = value[:254]
    elif step == 'phone':
        number = normalise_phone(value)
        if not number:
            return 'bad_phone'
        data['phone'] = number
        state.pop('typing_phone', None)
    elif step == 'message':
        data['message'] = str(value or '').strip()[:500]
    if step not in done:
        done.append(step)
    return None


def enquiry_continue(c, state):
    if state.pop('editing', False):
        return send_summary(c, state)
    ask_enquiry_step(c, state)


def enquiry_action(c, state, action):
    parts = action.split(':')
    step = state.get('step')
    if action == 'enq:submit':
        return submit_enquiry(c, state)
    if action == 'enq:cancel':
        clear_state(c)
        return say(c, 'cancelled')
    if action == 'enq:edit':
        fields = [s for s in ENQ_STEPS if s != 'confirm']
        got = labels(c, [f'f_{s}' for s in fields] + ['edit_button'])
        return wa.send_list(c['wa_id'], t(lang(c), 'edit_which'), got[-1],
                            [(f'enq:edit:{s}', got[i], '') for i, s in enumerate(fields)])
    if parts[1] == 'edit' and len(parts) == 3 and parts[2] in ENQ_STEPS:
        target = parts[2]
        if target in state['done']:
            state['done'].remove(target)
        if target == 'services':
            state['data']['services'] = []
        state['editing'] = True
        return ask_enquiry_step(c, state, target)
    if action == 'enq:name:profile':
        error = enquiry_answer(c, state, 'name', c.get('profile_name'))
    elif action == 'enq:skip':
        if step not in ('business', 'email', 'message'):
            return ask_enquiry_step(c, state)
        error = enquiry_answer(c, state, step, '')
    elif parts[1] == 'svc' and parts[2] == 'more':
        state['step'] = 'services'
        set_state(c, state)
        return wa.send_list(c['wa_id'], t(lang(c), 'ask_services'), t(lang(c), 'ask_services_button'),
                            service_rows(c, exclude=state['data']['services']))
    elif parts[1] == 'svc' and parts[2] == 'done':
        if not state['data']['services']:
            return ask_enquiry_step(c, state, 'services')
        if 'services' not in state['done']:
            state['done'].append('services')
        error = None
    elif parts[1] == 'svc':
        error = enquiry_answer(c, state, 'services', [parts[2]])
    elif parts[1] == 'tl':
        error = enquiry_answer(c, state, 'timeline', parts[2])
    elif parts[1] == 'cm':
        error = enquiry_answer(c, state, 'method', parts[2])
    elif action == 'enq:phone:yes':
        error = enquiry_answer(c, state, 'phone', c['wa_id'])
    elif action == 'enq:phone:other':
        state['typing_phone'] = True
        return ask_enquiry_step(c, state, 'phone')
    else:
        return ask_enquiry_step(c, state)
    if error == 'wait':
        return None
    if error:
        if error.startswith('bad_'):
            say(c, error)
        return ask_enquiry_step(c, state, step if step != 'services_more' else 'services')
    enquiry_continue(c, state)


YES_WORDS = {'yes', 'ok', 'okay', 'k', 'yes correct', 'correct', 'right', 'yep', 'yeah', 'sure', 'sari', 'seri',
             'aama', 'aamam', 'ama', 'ஆம்', 'சரி', 'haan', 'ha', 'done', 'confirm', 'submit', 'send'}
DONE_WORDS = {'done', 'no', 'nothing', 'nothing else', 'that is all', "that's all", 'thats all', 'no more', 'podhum',
              'pothum', 'illa', 'illai', 'no thanks', 'முடிந்தது', 'போதும்', 'இல்லை', 'next'}


def enquiry_text(c, state, text):
    step = state.get('step') or next_enquiry_step(state)
    low = plain(text)
    if step == 'services_more':
        if low in DONE_WORDS:
            return enquiry_action(c, state, 'enq:svc:done')
        step = 'services'
    if step == 'confirm' and low in YES_WORDS:
        return submit_enquiry(c, state)
    if step == 'phone' and not state.get('typing_phone') and low in YES_WORDS:
        return enquiry_action(c, state, 'enq:phone:yes')
    question_key = 'ask_email_required' if step == 'email' and state['data'].get('method') == 'email' else ENQ_QUESTION[step]
    if step == 'email' and '@' in text:
        got = {'intent': 'answer', 'value': next(w for w in text.split() if '@' in w).strip('.,;<>()'), 'fields': {}}
    elif step == 'phone' and len(config.digits(text)) >= 7 and not re.search(r'[a-zA-Z]{4,}', text):
        got = {'intent': 'answer', 'value': text, 'fields': {}}
    else:
        got = understand(c, step, question_key, text)
    if got['intent'] == 'cancel':
        clear_state(c)
        return say(c, 'cancelled')
    apply_enquiry_fields(state, got.get('fields') or {})
    if got['intent'] == 'answer' and step != 'confirm':
        value = got.get('value')
        if step == 'services' and not value and state['data']['services']:
            return enquiry_action(c, state, 'enq:svc:done')
        error = enquiry_answer(c, state, step, value)
        if error == 'wait':
            return None
        if error:
            if error.startswith('bad_'):
                say(c, error)
            return ask_enquiry_step(c, state, step)
        return enquiry_continue(c, state)
    note = f'giving details for a free quote (the bot is waiting for: {T[question_key]["en"]})'
    answer_question_mid_flow(c, text, note)
    if step == 'confirm':
        return send_summary(c, state)
    set_state(c, state)                                   # keeps any details picked up from the message
    ask_enquiry_step(c, state)


def submit_enquiry(c, state):
    data = state['data']
    if not valid_name(data.get('name')):
        state['done'] = [s for s in state['done'] if s != 'name']
        return ask_enquiry_step(c, state, 'name')
    phone = phone_display(data.get('phone') or c['wa_id'])
    services = [SVC_NAMES[s] for s in data.get('services') or [] if s in SVC_NAMES]
    message = data.get('message') or ''
    if data.get('attachments'):
        message += f"\n\n(The customer also shared {data['attachments']} file(s) on WhatsApp. See the chat in the dashboard.)"
    enquiry_id = db.insert_enquiry(data['name'], phone, data.get('email') or '', data.get('business') or '', services,
                                   data.get('timeline') or '', data.get('method') or '', message.strip(), lang(c))
    db.update_contact(c['wa_id'], name=data['name'], business_name=data.get('business') or c.get('business_name') or '',
                      email=data.get('email') or c.get('email') or '', state={})
    c.update({'name': data['name'], 'state': {}})
    timeline = dict(asap='As soon as possible', **{'1m': 'Within a month', '3m': '1-3 months', 'explore': 'Just exploring'})
    detail = '\n'.join(x for x in [
        f"Business: {data.get('business') or '-'}",
        f"Services: {', '.join(services) or '-'}",
        f"When: {timeline.get(data.get('timeline'), '-')}",
        f"Contact by: {data.get('method') or '-'}",
        f"Email: {data.get('email') or '-'}",
        f"Project: {message.strip() or '-'}"] if x)
    summary = f"New enquiry #{enquiry_id} from the WhatsApp bot: {', '.join(services) or 'service not given'}"
    db.queue_alert('new_enquiry', summary, wa_id=c['wa_id'], customer_name=data['name'], customer_phone=phone,
                   detail=detail, ref_id=enquiry_id)
    db.queue_alert('enquiry_reminder',
                   f'Enquiry #{enquiry_id} is still New. Please contact the customer (we promised 24 hours)',
                   wa_id=c['wa_id'], customer_name=data['name'], customer_phone=phone, detail=detail, ref_id=enquiry_id,
                   due_at=db.now() + timedelta(hours=config.ENQUIRY_REMINDER_HOURS))
    say(c, 'enq_done', name=data['name'].split()[0], id=enquiry_id)
    if db.upcoming_booking(c['wa_id']):
        return buttons(c, t(lang(c), 'menu_body'), [('m:work', 'b_work'), ('m:menu', 'b_menu')])
    buttons(c, t(lang(c), 'enq_next'), [('m:call', 'b_call'), ('m:menu', 'b_menu')])


# ===========================================================================
# Call booking flow
# ===========================================================================
WD = {'en': ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
      'ta': ['திங்கள்', 'செவ்வாய்', 'புதன்', 'வியாழன்', 'வெள்ளி', 'சனி', 'ஞாயிறு']}
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def time_label(hhmm):
    return datetime.strptime(hhmm, '%H:%M').strftime('%I:%M %p').lstrip('0')


def day_label(c, d, with_year=False):
    L = 'ta' if lang(c) == 'ta' else 'en'
    wd = WD[L][d.weekday()]
    text = f'{wd} {d.day}/{d.month}' if L == 'ta' else f'{wd} {d.day} {MONTHS[d.month - 1]}'
    if with_year:
        text += f'/{d.year}' if L == 'ta' else f' {d.year}'
    today = now_ist().date()
    if d == today:
        text = f"{t(lang(c), 'bk_today')}, {text}"
    elif d == today + timedelta(days=1):
        text = f"{t(lang(c), 'bk_tomorrow')}, {text}"
    return text


def when_label(c, d, hhmm):
    return f'{day_label(c, d, with_year=True)}, {time_label(hhmm)}'


def to_date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def free_slots(day, taken=None):
    if taken is None:
        taken = db.booked_slots(day, day)
    earliest = now_ist() + timedelta(minutes=config.CALL_MIN_NOTICE_MINUTES)
    out = []
    for slot in config.CALL_SLOTS:
        h, m = map(int, slot.split(':'))
        if (day, slot) in taken:
            continue
        if datetime.combine(day, dtime(h, m), tzinfo=config.TZ) < earliest:
            continue
        out.append(slot)
    return out


def open_days():
    today = now_ist().date()
    last = today + timedelta(days=config.CALL_DAYS_AHEAD)
    taken = db.booked_slots(today, last)
    days = []
    for i in range(config.CALL_DAYS_AHEAD + 1):
        d = today + timedelta(days=i)
        if d.weekday() not in config.CALL_WEEKDAYS:
            continue
        slots = free_slots(d, taken)
        if slots:
            days.append((d, len(slots)))
    return days[:10]


def start_booking(c, replace_id=None):
    if not replace_id:
        existing = db.upcoming_booking(c['wa_id'])
        if existing:
            when = when_label(c, existing['call_date'], existing['call_time'].strftime('%H:%M'))
            bid = existing['id']
            return buttons(c, t(lang(c), 'bk_existing', when=when),
                           [(f'bk:resched:{bid}', 'b_change_time'), (f'bk:cancelcall:{bid}', 'b_cancel_call'),
                            (f'bk:keep:{bid}', 'b_keep')])
    state = {'flow': 'booking', 'data': {'name': c.get('name') or '', 'replace_id': replace_id},
             'started': db.now().isoformat()}
    say(c, 'bk_start')
    if not valid_name(state['data']['name']):
        return ask_booking_step(c, state, 'name')
    ask_booking_step(c, state, 'day')


def ask_booking_step(c, state, step):
    state['step'] = step
    set_state(c, state)
    data, L = state['data'], lang(c)
    if step == 'name':
        profile = (c.get('profile_name') or '').strip()
        if valid_name(profile):
            return buttons(c, t(L, 'ask_name_profile'), [('bk:name:profile', ('literal', f'✅ {profile}'))])
        return say(c, 'ask_name')
    if step == 'day':
        days = open_days()
        if not days:
            clear_state(c)
            name = data.get('name') or display_name(c)
            db.queue_alert('call_request', f'{name or "A customer"} wants a call, but all call times are full',
                           wa_id=c['wa_id'], customer_name=name, customer_phone=phone_display(c['wa_id']))
            db.update_contact(c['wa_id'], needs_reply=True)
            return say(c, 'bk_no_slots')
        rows = [(f'bk:day:{d.isoformat()}', day_label(c, d), t(L, 'bk_slots_left', n=n)) for d, n in days]
        return wa.send_list(c['wa_id'], t(L, 'bk_ask_day'), t(L, 'bk_day_button'), rows)
    if step == 'time':
        day = to_date(data.get('date'))
        slots = free_slots(day) if day else []
        if not slots:
            say(c, 'bk_day_full')
            return ask_booking_step(c, state, 'day')
        rows = [(f'bk:time:{s}', time_label(s), '') for s in slots]
        return wa.send_list(c['wa_id'], t(L, 'bk_ask_time', day=day_label(c, day)), t(L, 'bk_time_button'), rows)
    if step == 'topic':
        return buttons(c, t(L, 'bk_ask_topic'), [('bk:skip', 'b_skip')])
    day = to_date(data['date'])
    body = t(L, 'bk_confirm', when=when_label(c, day, data['time']), phone=phone_display(c['wa_id']),
             topic=data.get('topic') or t(L, 'not_given'))
    buttons(c, body, [('bk:confirm', 'b_confirm'), ('bk:change', 'b_change_time'), ('bk:cancel', 'b_cancel')])


def booking_set_when(c, state, value):
    """value: {"date": ..., "time": ...}. Returns the next step to ask."""
    data = state['data']
    value = value if isinstance(value, dict) else {}
    day = to_date(value.get('date')) or to_date(data.get('date'))
    open_list = [d for d, _ in open_days()]
    if not day or day not in open_list:
        if value.get('date'):
            say(c, 'bk_day_full')
        return 'day'
    data['date'] = day.isoformat()
    slot = (value.get('time') or '')[:5]
    if slot and slot in free_slots(day):
        data['time'] = slot
        return 'topic'
    if slot:
        say(c, 'bk_slot_taken' if slot in config.CALL_SLOTS else 'bk_bad_time')
    data.pop('time', None)
    return 'time'


def booking_action(c, state, action):
    parts = action.split(':')
    data = state['data']
    if action == 'bk:cancel':
        clear_state(c)
        return say(c, 'cancelled')
    if action == 'bk:change':
        data.pop('time', None)
        return ask_booking_step(c, state, 'day')
    if action == 'bk:confirm':
        return confirm_booking(c, state)
    if action == 'bk:skip':
        data['topic'] = ''
        return ask_booking_step(c, state, 'confirm')
    if action == 'bk:name:profile':
        data['name'] = valid_name(c.get('profile_name')) or ''
        return ask_booking_step(c, state, 'day' if data['name'] else 'name')
    if parts[1] == 'day' and len(parts) >= 3:
        return ask_booking_step(c, state, booking_set_when(c, state, {'date': parts[2]}))
    if parts[1] == 'time' and len(parts) >= 4:
        return ask_booking_step(c, state, booking_set_when(c, state, {'time': f'{parts[2]}:{parts[3]}'}))
    return ask_booking_step(c, state, state.get('step') or 'day')


def booking_text(c, state, text):
    step = state.get('step') or 'day'
    question = {'name': 'ask_name', 'day': 'bk_ask_day', 'time': 'bk_ask_time', 'topic': 'bk_ask_topic',
                'confirm': 'bk_confirm'}[step]
    if step == 'confirm':
        if plain(text) in {'yes', 'ok', 'confirm', 'sari', 'seri', 'aama', 'ஆம்', 'சரி', 'done'}:
            return confirm_booking(c, state)
    got = understand(c, step if step != 'confirm' else 'time', question, text)
    if got['intent'] == 'cancel':
        clear_state(c)
        return say(c, 'cancelled')
    if got['intent'] == 'answer':
        if step == 'name':
            name = valid_name(got['value'])
            if name:
                state['data']['name'] = name
                return ask_booking_step(c, state, 'day')
            say(c, 'bad_name')
            return ask_booking_step(c, state, 'name')
        if step in ('day', 'time', 'confirm'):
            return ask_booking_step(c, state, booking_set_when(c, state, got['value']))
        if step == 'topic':
            state['data']['topic'] = str(got['value'] or '')[:500]
            return ask_booking_step(c, state, 'confirm')
    answer_question_mid_flow(c, text, f'booking a free call (the bot is waiting for: {T[question]["en"]})')
    ask_booking_step(c, state, step)


def confirm_booking(c, state):
    data = state['data']
    day, slot = to_date(data.get('date')), data.get('time')
    if not day or not slot or slot not in free_slots(day):
        if day and slot:
            say(c, 'bk_slot_taken')
        return ask_booking_step(c, state, 'time' if day else 'day')
    enquiry = db.latest_enquiry(c['wa_id'])
    enquiry_id = enquiry['id'] if enquiry and db.now() - enquiry['created_at'] < timedelta(days=30) else None
    name = data.get('name') or display_name(c)
    booking = db.insert_booking(c['wa_id'], name, phone_display(c['wa_id']), data.get('topic') or '', day, slot, enquiry_id)
    if not booking:
        say(c, 'bk_slot_taken')
        return ask_booking_step(c, state, 'time')
    if data.get('replace_id'):
        old = db.get_booking(data['replace_id'])
        if old and old['wa_id'] == c['wa_id'] and old['status'] == 'booked':
            db.set_booking_status(old['id'], 'cancelled')
            db.cancel_alerts('call_reminder', old['id'])
            db.cancel_alerts('cust_call_reminder', old['id'])
    clear_state(c)
    if valid_name(name) and not c.get('name'):
        db.update_contact(c['wa_id'], name=name)
    when_en = f"{WD['en'][day.weekday()]} {day.day} {MONTHS[day.month - 1]}, {time_label(slot)}"
    phone = phone_display(c['wa_id'])
    detail = f"Topic: {data.get('topic') or '-'}" + (f'\nEnquiry #{enquiry_id}' if enquiry_id else '')
    verb = 'moved their call to' if data.get('replace_id') else 'booked a call for'
    db.queue_alert('call_booked', f'{name or "A customer"} {verb} {when_en}', wa_id=c['wa_id'], customer_name=name,
                   customer_phone=phone, detail=detail, ref_id=booking['id'])
    start = datetime.combine(day, dtime(*map(int, slot.split(':'))), tzinfo=config.TZ)
    remind_at = start - timedelta(minutes=config.CALL_REMINDER_MINUTES)
    if remind_at > now_ist():
        db.queue_alert('call_reminder', f'Call with {name or "a customer"} at {time_label(slot)} today',
                       wa_id=c['wa_id'], customer_name=name, customer_phone=phone, detail=detail,
                       ref_id=booking['id'], due_at=remind_at)
        db.queue_alert('cust_call_reminder', f'Reminder to customer for call at {time_label(slot)}',
                       wa_id=c['wa_id'], customer_name=name, customer_phone=phone, ref_id=booking['id'],
                       due_at=remind_at)
    say(c, 'bk_done', when=when_label(c, day, slot), phone=phone)


def booking_manage(c, action):
    parts = action.split(':')
    booking = db.get_booking(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if not booking or booking['wa_id'] != c['wa_id'] or booking['status'] != 'booked':
        return start_booking(c)
    when = when_label(c, booking['call_date'], booking['call_time'].strftime('%H:%M'))
    if parts[1] == 'resched':
        return start_booking(c, replace_id=booking['id'])
    if parts[1] == 'cancelcall':
        db.set_booking_status(booking['id'], 'cancelled')
        db.cancel_alerts('call_reminder', booking['id'])
        db.cancel_alerts('cust_call_reminder', booking['id'])
        name = booking['name'] or display_name(c)
        db.queue_alert('call_cancelled', f'{name or "A customer"} cancelled their call ({when})', wa_id=c['wa_id'],
                       customer_name=name, customer_phone=phone_display(c['wa_id']), ref_id=booking['id'])
        return say(c, 'bk_cancelled', when=when)
    say(c, 'bk_kept', when=when)


# ===========================================================================
# Review flow
# ===========================================================================
def start_review(c):
    state = {'flow': 'review', 'data': {}, 'started': db.now().isoformat()}
    say(c, 'rv_start')
    ask_review_step(c, state, 'rating')


def ask_review_step(c, state, step):
    state['step'] = step
    set_state(c, state)
    L = lang(c)
    if step == 'rating':
        got = labels(c, [f'rv_{n}' for n in (5, 4, 3, 2, 1)] + ['rv_rating_button'])
        rows = [(f'rv:rate:{n}', f"{'⭐' * n} {got[i]}", '') for i, n in enumerate((5, 4, 3, 2, 1))]
        return wa.send_list(c['wa_id'], t(L, 'rv_ask_rating'), got[-1], rows)
    if step == 'text':
        return say(c, 'rv_ask_text')
    if step == 'name':
        profile = (c.get('name') or c.get('profile_name') or '').strip()
        if valid_name(profile):
            return buttons(c, t(L, 'rv_ask_name'), [('rv:name:profile', ('literal', f'✅ {profile}'))])
        return say(c, 'rv_ask_name')
    if step == 'biz':
        return buttons(c, t(L, 'rv_ask_biz'), [('rv:skip', 'b_skip')])
    buttons(c, t(L, 'rv_ask_publish'), [('rv:pub:yes', 'b_publish_yes'), ('rv:pub:no', 'b_publish_no')])


def review_action(c, state, action):
    parts = action.split(':')
    data = state['data']
    if parts[1] == 'rate' and len(parts) == 3 and parts[2] in '12345':
        data['rating'] = int(parts[2])
        return ask_review_step(c, state, 'text' if not data.get('text') else 'name')
    if action == 'rv:name:profile':
        data['name'] = valid_name(c.get('name') or c.get('profile_name'))
        return ask_review_step(c, state, 'biz' if data['name'] else 'name')
    if action == 'rv:skip':
        data.update(business='', location='')
        return ask_review_step(c, state, 'publish')
    if parts[1] == 'pub':
        return finish_review(c, state, parts[2] == 'yes')
    return ask_review_step(c, state, state.get('step') or 'rating')


def review_text(c, state, text):
    step = state.get('step') or 'rating'
    data = state['data']
    question = {'rating': 'rv_ask_rating', 'text': 'rv_ask_text', 'name': 'rv_ask_name', 'biz': 'rv_ask_biz',
                'publish': 'rv_ask_publish'}[step]
    if step == 'text':
        if plain(text) in CANCEL_WORDS:
            clear_state(c)
            return say(c, 'cancelled')
        if len(text.strip()) < 3:
            say(c, 'rv_too_short')
            return ask_review_step(c, state, 'text')
        data['text'] = text.strip()[:2000]
        return ask_review_step(c, state, 'name')
    if step == 'publish':
        low = plain(text)
        if low in {'yes', 'ok', 'sure', 'aama', 'seri', 'sari', 'ஆம்', 'சரி', 'kaattalaam'}:
            return finish_review(c, state, True)
        if low in {'no', 'illa', 'venaam', 'வேண்டாம்', 'private', 'இல்லை'}:
            return finish_review(c, state, False)
    step_name = {'rating': 'rating', 'name': 'review_name', 'biz': 'review_biz', 'publish': 'review_name'}[step]
    got = understand(c, step_name, question, text)
    if got['intent'] == 'cancel':
        clear_state(c)
        return say(c, 'cancelled')
    if got['intent'] == 'answer' and step != 'publish':
        if step == 'rating':
            try:
                rating = int(got['value'])
            except (TypeError, ValueError):
                rating = 0
            if 1 <= rating <= 5:
                data['rating'] = rating
                return ask_review_step(c, state, 'text')
        elif step == 'name':
            name = valid_name(got['value'])
            if name:
                data['name'] = name
                return ask_review_step(c, state, 'biz')
        elif step == 'biz':
            value = got['value'] if isinstance(got['value'], dict) else split_business(str(got['value']))
            data['business'] = str(value.get('business') or '')[:160]
            data['location'] = str(value.get('location') or '')[:120]
            return ask_review_step(c, state, 'publish')
    answer_question_mid_flow(c, text, f'leaving a review (the bot is waiting for: {T[question]["en"]})')
    ask_review_step(c, state, step)


def finish_review(c, state, publish):
    data = state['data']
    if not data.get('rating') or not data.get('text'):
        return ask_review_step(c, state, 'rating' if not data.get('rating') else 'text')
    name = data.get('name') or valid_name(display_name(c)) or 'Client'
    original = data['text']
    stars = '★' * data['rating']
    clear_state(c)
    if not c.get('name') and valid_name(data.get('name')):
        db.update_contact(c['wa_id'], name=data['name'])
    if publish:
        review_en, review_ta = original, ''
        written = script_language(original)
        if ai.enabled():
            try:
                en, ta = ai.review_versions(original)
                review_en = original if written is None else (en or original)
                review_ta = original if written == 'ta' else ta
            except Exception as e:
                log.warning('Review translation failed: %s', e)
                review_ta = original if written == 'ta' else ''
        elif written == 'ta':
            review_ta = original
        review_id = db.insert_review(name, data.get('business') or '', data.get('location') or '', data['rating'],
                                     review_en, review_ta)
        db.queue_alert('new_review', f'New {stars} review from {name}. It is hidden until you publish it in Dashboard > Reviews',
                       wa_id=c['wa_id'], customer_name=name, customer_phone=phone_display(c['wa_id']),
                       detail=original, ref_id=review_id)
        say(c, 'rv_done_public', name=name.split()[0])
        if config.GOOGLE_REVIEW_URL and data['rating'] >= 4:
            say(c, 'rv_google', url=config.GOOGLE_REVIEW_URL)
    else:
        db.queue_alert('private_feedback', f'Private {stars} feedback from {name} (not for the website)',
                       wa_id=c['wa_id'], customer_name=name, customer_phone=phone_display(c['wa_id']), detail=original)
        say(c, 'rv_done_private', name=name.split()[0])


# ===========================================================================
# Routing
# ===========================================================================
def handle_action(c, action):
    action = (action or '').strip()
    fl, state = flow(c)
    head = action.split(':')[0]
    if action.startswith('m:'):
        return menu_action(c, action[2:])
    if head == 'svc':
        return show_services(c, action[4:])
    if action == 'pf:more':
        return show_portfolio(c)
    if head == 'pf':
        return show_project(c, action[3:])
    if head == 'lang':
        return set_language(c, action[5:])
    if action == 'rv:start':
        return start_review(c)
    if action in ('flow:continue', 'flow:cancel'):
        if not fl:
            return send_menu(c)
        if action == 'flow:cancel':
            clear_state(c)
            return say(c, 'cancelled')
        return resume_flow(c)
    if head == 'bk' and action.split(':')[1] in ('resched', 'cancelcall', 'keep'):
        return booking_manage(c, action)
    if head == 'enq':
        if fl == 'enquiry':
            return enquiry_action(c, state, action)
        if action == 'enq:submit':
            return say(c, 'enq_already')
    if head == 'bk' and fl == 'booking':
        return booking_action(c, state, action)
    if head == 'rv' and fl == 'review':
        return review_action(c, state, action)
    # a button from an old message
    send_menu(c, t(lang(c), 'expired'))


def menu_action(c, item):
    if item in ('quote', 'call', 'review') and flow(c)[0]:
        clear_state(c)
    if item == 'menu':
        return send_menu(c)
    if item == 'services':
        return show_services(c)
    if item == 'prices':
        return show_prices(c)
    if item == 'work':
        return show_portfolio(c)
    if item == 'quote':
        return start_enquiry(c)
    if item == 'call':
        return start_booking(c)
    if item == 'team':
        return talk_to_team(c)
    if item == 'review':
        return start_review(c)
    if item == 'lang':
        return ask_language(c)
    send_menu(c)


def resume_flow(c):
    fl, state = flow(c)
    if fl == 'enquiry':
        return ask_enquiry_step(c, state, state.get('step') if state.get('step') != 'services_more' else 'services')
    if fl == 'booking':
        return ask_booking_step(c, state, state.get('step') or 'day')
    if fl == 'review':
        return ask_review_step(c, state, state.get('step') or 'rating')
    send_menu(c)


def handle_text(c, text, first_time=False):
    low = plain(text)
    fl, state = flow(c)

    if low in STOP_WORDS:
        db.update_contact(c['wa_id'], opted_out=True, opted_out_at=db.now(), state={})
        return say(c, 'stop_done')
    if low in START_WORDS and c.get('opted_out'):
        db.update_contact(c['wa_id'], opted_out=False, opted_out_at=None)
        return say(c, 'start_done')
    if low in MENU_WORDS or low in START_WORDS:
        clear_state(c)
        return send_menu(c)
    if GREETINGS.match(text) and not fl:
        return welcome(c)
    if low in REVIEW_WORDS:
        return start_review(c)
    if re.search(r'\b(change|cancel|reschedule)\s+(my\s+)?call\b|call\s*(maathu|maatru|cancel)', low):
        clear_state(c)
        return start_booking(c)
    if fl and low in CANCEL_WORDS:
        clear_state(c)
        return say(c, 'cancelled')

    if fl == 'enquiry':
        return enquiry_text(c, state, text)
    if fl == 'booking':
        return booking_text(c, state, text)
    if fl == 'review':
        return review_text(c, state, text)
    return free_chat(c, text, first_time)


def free_chat(c, text, first_time=False, image=None):
    reply, calls = '', []
    if ai.enabled():
        try:
            reply, calls = ai.chat(c, db.recent_messages(c['wa_id']), lang(c), image=image)
        except Exception as e:
            log.warning('AI chat failed: %s', e)
            reply, calls = '', simple_route(text)
    else:
        calls = simple_route(text)
    if reply:
        text_to(c, reply)
    ran = False
    if calls:
        name, args = calls[0]
        ran = run_tool(c, name, args, intro=not reply) is not False
    if not ran and not reply:
        return send_menu(c, t(lang(c), 'didnt_get'))
    if not ran and first_time:
        send_menu(c)


def run_tool(c, name, args, intro=True):
    if name == 'show_menu':
        return send_menu(c)
    if name == 'show_services':
        return show_services(c, args.get('service'))
    if name == 'start_enquiry':
        return start_enquiry(c, prefill=args, intro=intro)
    if name == 'show_portfolio':
        return show_portfolio(c)
    if name == 'book_call':
        return start_booking(c)
    if name == 'talk_to_team':
        return talk_to_team(c, str(args.get('reason') or '')[:200])
    if name == 'leave_review':
        return start_review(c)
    if name == 'change_language':
        return ask_language(c)
    if name == 'show_prices':
        return show_prices(c)
    return False


def simple_route(text):
    """Keyword routing when the AI is not available."""
    low = text.lower()
    rules = [
        (r'price|cost|rate|charge|how much|evlo|evvalavu|kitna|விலை|கட்டணம்|budget|quote|quotation', 'show_prices'),
        (r'portfolio|your work|projects|sample|example|demo|previous', 'show_portfolio'),
        (r'call me|book.*call|appointment|meeting|call back|callback', 'book_call'),
        (r'human|person|agent|staff|talk to|speak to|owner|manager|complaint', 'talk_to_team'),
        (r'review|feedback|rating', 'leave_review'),
        (r'language|tamil|english|மொழி', 'change_language'),
        (r'service|website|web site|app|store|shop|seo|marketing|hosting|domain|software', 'show_services'),
    ]
    for pattern, tool in rules:
        if re.search(pattern, low):
            return [(tool, {})]
    return []


def handle_media(c, kind, caption, media):
    fl, state = flow(c)
    if fl == 'enquiry' and kind in ('image', 'document', 'video'):
        state['data']['attachments'] = int(state['data'].get('attachments') or 0) + 1
        set_state(c, state)
    if kind == 'sticker':
        return None
    image = None
    if kind == 'image' and ai.enabled() and media.get('id'):
        data, mime = wa.download_media(media['id'], max_bytes=5 * 1024 * 1024)
        if data and (mime or '').startswith('image/'):
            image = (data, mime, caption)
    if fl:
        note = {'enquiry': 'giving details for a free quote', 'booking': 'booking a free call',
                'review': 'leaving a review'}[fl]
        if not (image and answer_question_mid_flow(c, caption, note + ' and just sent an image', image=image)):
            say(c, 'media_thanks')
        return resume_flow(c)
    if image:
        return free_chat(c, caption or '(image)', image=image)
    if caption and kind in ('image', 'document', 'video'):
        say(c, 'media_thanks')
        return free_chat(c, caption)
    say(c, 'media_thanks')
    buttons(c, t(lang(c), 'menu_body'), [('m:quote', 'b_quote'), ('m:menu', 'b_menu')])


# ===========================================================================
# Follow-up for customers who stopped halfway (called by jobs.py)
# ===========================================================================
def send_nudge(c):
    fl, state = flow(c)
    if not fl or not db.window_open(c):
        return
    what = t(lang(c), {'enquiry': 'what_enquiry', 'booking': 'what_booking', 'review': 'what_review'}[fl])
    name = valid_name((state.get('data') or {}).get('name'))
    buttons(c, t(lang(c), 'nudge', name=name.split()[0] if name else friendly(c), what=what),
            [('flow:continue', 'b_continue'), ('flow:cancel', 'b_cancel')])


# ===========================================================================
# AJ messages the bot (admin)
# ===========================================================================
def admin_reply(c):
    s = db.admin_summary()
    text = (f"Hi AJ 👋 Here is your quick summary:\n\n"
            f"📥 New enquiries (not contacted): *{s['new_enquiries']}*\n"
            f"🤖 From the bot in the last 24 hours: *{s['bot_today']}*\n"
            f"💬 Chats waiting for your reply: *{s['needs_reply']}*\n"
            f"📅 Calls today: *{s['calls_today']}* · Later: *{s['calls_later']}*\n\n"
            f"Dashboard: {config.DASHBOARD_URL}\n\n"
            "Alerts can now reach you as normal messages for the next 24 hours. "
            "To test the bot as a customer, message it from another phone.")
    wa.send_text(c['wa_id'], text)

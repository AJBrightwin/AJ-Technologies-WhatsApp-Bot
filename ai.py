"""
OpenAI helpers: answering questions, understanding replies in any language,
voice notes, images and translation.

If OPENAI_API_KEY is missing or OpenAI is down, the bot still works with
buttons and simple keyword matching (see bot.py).
"""
import base64
import json
import logging
import threading
from datetime import datetime

import config
from texts import LANG_NAMES

log = logging.getLogger('bot.ai')

_client = None
_client_lock = threading.Lock()
_cache = {}
_cache_lock = threading.Lock()


def enabled():
    return bool(config.OPENAI_API_KEY)


def client():
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                import openai
                _client = openai.OpenAI(api_key=config.OPENAI_API_KEY, timeout=30, max_retries=1)
    return _client


def _complete(messages, json_mode=False, tools=None, max_tokens=500, temperature=0.4):
    kwargs = {'model': config.OPENAI_MODEL, 'messages': messages, 'max_tokens': max_tokens,
              'temperature': temperature}
    if json_mode:
        kwargs['response_format'] = {'type': 'json_object'}
    if tools:
        kwargs['tools'] = tools
        kwargs['tool_choice'] = 'auto'
    return client().chat.completions.create(**kwargs).choices[0].message


def lang_name(code):
    return LANG_NAMES.get(code, code)


# ---------------------------------------------------------------------------
# Company knowledge (what the AI may say)
# ---------------------------------------------------------------------------
KNOWLEDGE = f"""
COMPANY: {config.COMPANY} ("{config.TAGLINE}"), a web, app and digital marketing company in {config.LOCATION}.
We work with businesses across Tamil Nadu and all over India, fully end to end: idea, design, development, launch, marketing and support.
Phone / WhatsApp for the team: {config.PHONE_DISPLAY}. Email: {config.EMAIL}. Website: {config.SITE_URL}
Portfolio: {config.PORTFOLIO_URL}. Instagram: {config.INSTAGRAM}. YouTube: {config.YOUTUBE}

SERVICES
- Business Websites: professional, mobile-friendly sites for shops, clinics, restaurants, schools, professionals. Contact form, WhatsApp button, Google Maps, SEO basics, English & Tamil, admin panel, SSL, speed optimised, free support after launch.
- E-commerce Stores: online stores with Razorpay payments (UPI, cards, net banking, wallets), product listings, order management, admin panel.
- Landing Pages for campaigns, launches and ads. Website Redesign of old sites.
- Web Apps & SaaS: online tools/portals with secure logins and admin dashboards (bookings, billing, dashboards...).
- Mobile Apps: Android and iOS, tested on real devices, published on Play Store and App Store for the client.
- Digital Marketing: SEO, Google Business Profile (Google Maps), social media marketing (Instagram, Facebook, YouTube), WhatsApp Business integration (chat buttons, catalogues, automated replies). One-time setup or monthly plans.
- Domain & Hosting setup, Maintenance & AMC (updates, backups, security checks, content changes, hosting renewal).
Every project: free consultation, design approval before coding, testing on every device, training, support after launch.

TERMS (from our website policies)
- Payment: 50% advance to start, 50% on completion. Payments are made directly to us; there is no online payment on our website.
- 2 rounds of design revisions are included.
- The client owns the website, domain and content after full payment; source code is shared on request.
- Third-party costs (domain, hosting, paid plugins, ad spend, app store fees) are paid by the client.
- Timelines depend on the project and are agreed after the consultation.
- Privacy Policy: {config.PRIVACY_URL} · Terms: {config.TERMS_URL} · Service Delivery: {config.DELIVERY_URL}
"""

RULES = """
YOU ARE: "AJ Technologies Assistant", the WhatsApp assistant of AJ Technologies. You are an AI assistant, not a human; say so if asked.

HOW TO REPLY
- Reply in the customer's language and script: {lang}. Tamil in Tamil script; Tanglish = Tamil words in English letters; match how they write.
- WhatsApp style: short, warm, polite, clear. Usually 1-4 short sentences (max about 90 words). Use *bold* sparingly, no markdown headings, no tables.
- Remember the conversation so far and stay consistent with what you or the team already said.

STRICT RULES
- NEVER give any price, cost, range, "starting from" amount or discount, even if asked many times. Explain every project is custom built and offer a free quote; call start_enquiry when they ask about price or want to go ahead.
- NEVER promise a delivery date or timeline; say it is agreed after a free consultation.
- NEVER invent clients, projects, reviews, offers or facts not listed above. If you don't know, say our team will confirm.
- If they want a person, a call back or are unhappy: call talk_to_team (the team contacts them within 24 hours) and keep helping.
- To show the options menu call show_menu. To show our work call show_portfolio. To book a call call book_call. Existing clients wanting to leave a review: leave_review.
- If they share project details (what they need, business name...), pass those details to start_enquiry.
- For unrelated topics, answer briefly and politely bring the chat back to how we can help their business.
- Do not ask for passwords, OTPs, card or bank details.
"""

TOOLS = [
    {'type': 'function', 'function': {'name': 'show_menu', 'description': 'Show the main menu of options.',
                                      'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {
        'name': 'show_services', 'description': 'Show our services, or the details of one service.',
        'parameters': {'type': 'object', 'properties': {
            'service': {'type': 'string', 'enum': [c for c, _ in config.SERVICES],
                        'description': 'Only when the customer asks about one specific service.'}}}}},
    {'type': 'function', 'function': {
        'name': 'start_enquiry',
        'description': 'Start collecting a quote request (enquiry). Use when the customer asks the price, wants a quote, or wants to start a project. Fill in any details they already gave.',
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string'}, 'business_name': {'type': 'string'},
            'services': {'type': 'array', 'items': {'type': 'string', 'enum': [c for c, _ in config.ENQUIRY_SERVICES]}},
            'timeline': {'type': 'string', 'enum': ['asap', '1m', '3m', 'explore']},
            'contact_method': {'type': 'string', 'enum': ['whatsapp', 'call', 'email']},
            'email': {'type': 'string'},
            'message': {'type': 'string', 'description': 'What they want built, in their words.'}}}}},
    {'type': 'function', 'function': {'name': 'show_portfolio', 'description': 'Show projects we have built.',
                                      'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {'name': 'book_call', 'description': 'Book a free phone call with the team.',
                                      'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {
        'name': 'talk_to_team', 'description': 'The customer wants a human / call back / is unhappy. The team contacts them within 24 hours.',
        'parameters': {'type': 'object', 'properties': {'reason': {'type': 'string'}}}}},
    {'type': 'function', 'function': {'name': 'leave_review', 'description': 'An existing client wants to leave a review.',
                                      'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {'name': 'change_language', 'description': 'The customer wants to change the reply language.',
                                      'parameters': {'type': 'object', 'properties': {}}}},
]


def _history_messages(history):
    out = []
    for m in history:
        role = 'user' if m['direction'] == 'in' else 'assistant'
        text = m['body']
        if m['sender'] == 'admin':
            text = f'(Our team replied:) {text}'
        out.append({'role': role, 'content': text[:1500]})
    return out


def _profile(contact):
    known = {k: contact.get(k) for k in ('name', 'business_name', 'email') if contact.get(k)}
    if contact.get('profile_name') and not known.get('name'):
        known['whatsapp_profile_name'] = contact['profile_name']
    return json.dumps(known, ensure_ascii=False) if known else 'nothing yet'


def chat(contact, history, lang, mid_flow_note='', image=None, extra_note=''):
    """Answer the customer. Returns (text, [(tool_name, args), ...])."""
    system = (RULES.format(lang=lang_name(lang)) + '\n' + KNOWLEDGE +
              f'\nTODAY: {datetime.now(config.TZ):%A %d %B %Y, %I:%M %p} (India time)'
              f'\nWHAT WE KNOW ABOUT THIS CUSTOMER: {_profile(contact)}')
    if extra_note:
        system += f'\nNOTE: {extra_note}'
    if mid_flow_note:
        system += (f'\nRIGHT NOW: the customer is in the middle of {mid_flow_note}. Answer their message briefly '
                   '(1-3 sentences). Do NOT ask for the next detail and do NOT call tools; the bot asks it right after you.')
    messages = [{'role': 'system', 'content': system}] + _history_messages(history)
    if image:
        data, mime, caption = image
        messages.append({'role': 'user', 'content': [
            {'type': 'text', 'text': caption or '(The customer sent this image.)'},
            {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{base64.b64encode(data).decode()}'}}]})
    msg = _complete(messages, tools=None if mid_flow_note else TOOLS)
    calls = []
    for call in (msg.tool_calls or []):
        try:
            args = json.loads(call.function.arguments or '{}')
        except ValueError:
            args = {}
        calls.append((call.function.name, args if isinstance(args, dict) else {}))
    return (msg.content or '').strip(), calls


# ---------------------------------------------------------------------------
# Understanding a reply to a question the bot asked
# ---------------------------------------------------------------------------
STEP_HELP = {
    'name': 'value = the person\'s name only (proper capitals), e.g. "my name is ravi" -> "Ravi".',
    'business': 'value = the business name, or "" if they have none / want to skip.',
    'services': 'value = list of codes from web (websites), shop (online store / e-commerce), saas (web app / software / portal), app (mobile app), mkt (marketing / SEO / social media / Google), other.',
    'timeline': 'value = one of asap, 1m (within a month), 3m (1-3 months), explore (just exploring / not sure).',
    'method': 'value = one of whatsapp, call, email.',
    'email': 'value = the email address, or "" if they do not want to share it.',
    'phone': 'value = the phone number as digits (keep country code if given).',
    'message': 'value = their project description, cleaned up but in their words and language.',
    'topic': 'value = what they want to discuss, or "" if nothing in particular.',
    'day': 'value = {"date": "YYYY-MM-DD", "time": "HH:MM" or ""} for the day (and time, if given) they want.',
    'time': 'value = {"date": "YYYY-MM-DD" or "", "time": "HH:MM"} (24-hour) for the time they want.',
    'rating': 'value = a whole number 1 to 5.',
    'review_text': 'value = their review text, exactly as they wrote it (fix only obvious typos).',
    'review_name': 'value = the name to show, or "" if they prefer no name.',
    'review_biz': 'value = {"business": "...", "location": "..."} (either can be "").',
}


def extract(step, question, text, lang, recent=''):
    """Returns {"intent": answer|question|cancel|other, "value": ..., "fields": {...}} or None on failure."""
    system = f"""You read a WhatsApp customer's reply to a question from AJ Technologies Assistant.
Today is {datetime.now(config.TZ):%A %Y-%m-%d} (India). The customer writes in {lang_name(lang)} (may mix languages).
The bot asked ({step}): {question}
Return JSON: {{"intent": "...", "value": ..., "fields": {{...}}}}
intent:
- "answer": the message answers the question (even partly or casually). {STEP_HELP.get(step, '')}
- "question": they ask something instead of answering (e.g. price, services, how long).
- "cancel": they want to stop / not interested now.
- "other": anything else (greeting, unrelated, unclear).
fields: other details the message clearly gives, using only these keys: name, business_name, services (codes as above),
timeline, contact_method, email, message. Use {{}} if none. Never guess."""
    user = (f'Recent chat:\n{recent}\n\n' if recent else '') + f'Customer reply: {text}'
    msg = _complete([{'role': 'system', 'content': system}, {'role': 'user', 'content': user[:3000]}],
                    json_mode=True, max_tokens=400, temperature=0)
    data = json.loads(msg.content or '{}')
    if not isinstance(data, dict) or data.get('intent') not in ('answer', 'question', 'cancel', 'other'):
        return None
    if not isinstance(data.get('fields'), dict):
        data['fields'] = {}
    return data


# ---------------------------------------------------------------------------
# Language
# ---------------------------------------------------------------------------
def detect_language(text):
    """Language code for text written in English letters: en, tanglish, hinglish, or another ISO code."""
    msg = _complete([
        {'role': 'system', 'content': 'Identify the language of this WhatsApp message. Reply JSON {"lang": code}. '
                                      'Codes: "en" English, "tanglish" Tamil written in English letters, '
                                      '"hinglish" Hindi written in English letters, otherwise the ISO 639-1 code '
                                      '(e.g. "ml", "fr"). If it is mostly English with one or two other words, use "en".'},
        {'role': 'user', 'content': text[:500]}], json_mode=True, max_tokens=20, temperature=0)
    code = str(json.loads(msg.content or '{}').get('lang', '')).lower().strip()
    return code if code and len(code) <= 12 else None


def _cached(key):
    with _cache_lock:
        return _cache.get(key)


def _remember(key, value):
    with _cache_lock:
        if len(_cache) > 3000:
            _cache.clear()
        _cache[key] = value


def translate(text, lang):
    if not text or lang == 'en' or not enabled():
        return text
    key = (lang, text)
    hit = _cached(key)
    if hit:
        return hit
    try:
        msg = _complete([
            {'role': 'system', 'content': f'Translate this WhatsApp message from AJ Technologies into {lang_name(lang)}. '
                                          'Keep emojis, *bold* markers, line breaks, links, numbers, names, "AJ Technologies" '
                                          'and words like STOP / START / cancel exactly. Reply with the translation only.'},
            {'role': 'user', 'content': text}], max_tokens=900, temperature=0.2)
        out = (msg.content or '').strip() or text
    except Exception as e:
        log.warning('Translate failed: %s', e)
        return text
    _remember(key, out)
    return out


def translate_many(items, lang):
    if lang == 'en' or not enabled() or not items:
        return list(items)
    key = (lang, tuple(items))
    hit = _cached(key)
    if hit:
        return list(hit)
    try:
        msg = _complete([
            {'role': 'system', 'content': f'Translate each short WhatsApp button/menu label into {lang_name(lang)}. '
                                          'Keep emojis and keep each label as short as the original (under 20 characters '
                                          'when the original is short). Reply JSON {"items": [...]} in the same order.'},
            {'role': 'user', 'content': json.dumps(list(items), ensure_ascii=False)}],
            json_mode=True, max_tokens=900, temperature=0)
        out = json.loads(msg.content or '{}').get('items')
        if not isinstance(out, list) or len(out) != len(items):
            return list(items)
        out = [str(o).strip() or i for o, i in zip(out, items)]
    except Exception as e:
        log.warning('Translate labels failed: %s', e)
        return list(items)
    _remember(key, tuple(out))
    return out


def review_versions(text):
    """English and Tamil versions of a review for the website. Returns (review_en, review_ta)."""
    msg = _complete([
        {'role': 'system', 'content': 'A client wrote this review of AJ Technologies. Return JSON {"en": ..., "ta": ...}: '
                                      'a faithful English version and a faithful Tamil (Tamil script) version. Keep the meaning '
                                      'and tone, do not add praise, fix only spelling.'},
        {'role': 'user', 'content': text[:2000]}], json_mode=True, max_tokens=900, temperature=0.2)
    data = json.loads(msg.content or '{}')
    return str(data.get('en') or '').strip(), str(data.get('ta') or '').strip()


# ---------------------------------------------------------------------------
# Voice notes
# ---------------------------------------------------------------------------
def transcribe(audio, mime):
    ext = 'ogg'
    if 'mpeg' in mime or 'mp3' in mime:
        ext = 'mp3'
    elif 'mp4' in mime or 'm4a' in mime or 'aac' in mime:
        ext = 'm4a'
    elif 'amr' in mime:
        ext = 'amr'
    result = client().audio.transcriptions.create(
        model=config.OPENAI_TRANSCRIBE_MODEL, file=(f'voice.{ext}', audio, mime or 'audio/ogg'),
        prompt='AJ Technologies, website, online store, app, SEO, Thoothukudi, Tamil, Tanglish, English.')
    return (getattr(result, 'text', '') or '').strip()

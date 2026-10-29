"""
OpenAI helpers: answering questions, understanding replies in any language,
voice notes, images and translation.

If OPENAI_API_KEY is missing or OpenAI is down, the bot still works with
buttons and simple keyword matching (see bot.py).
"""
import base64
import json
import logging
import re
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
    try:
        return client().chat.completions.create(**kwargs).choices[0].message
    except Exception as e:
        report_problem(e)
        raise


def problem_kind(error):
    """'quota' when the OpenAI credits are finished, 'key' when the API key is wrong, else ''."""
    text = f'{getattr(error, "code", "")} {error}'.lower()
    if 'insufficient_quota' in text or 'exceeded your current quota' in text or 'billing' in text:
        return 'quota'
    if getattr(error, 'status_code', None) == 401 or 'invalid_api_key' in text or 'incorrect api key' in text:
        return 'key'
    return ''


def report_problem(error):
    """Tell AJ at once (max every 6 hours) when OpenAI stops working because of credits or the key."""
    kind = problem_kind(error)
    if not kind:
        return
    try:
        import db
        if db.recent_alert('openai_problem', '', 6):
            return
        summary = ('OpenAI credits are finished, so the bot is answering with menus only. Please recharge at '
                   'platform.openai.com > Settings > Billing.' if kind == 'quota' else
                   'The OpenAI API key is not working, so the bot is answering with menus only. Please check '
                   'OPENAI_API_KEY on Render.')
        db.queue_alert('openai_problem', summary, detail=str(error)[:500])
    except Exception:
        log.exception('Could not queue the OpenAI alert')


# ---------------------------------------------------------------------------
# The tool-calling loop used by the customer chat (agent.py) and AJ's assistant (admin.py)
# ---------------------------------------------------------------------------
def run_agent(system, history, tools, execute, image=None, note='', max_rounds=5, max_tokens=700,
              temperature=0.4):
    """Let the AI answer, calling our tools as often as it needs. Returns the final reply text.

    history: chat messages (oldest first), the newest customer message last.
    execute(name, args) -> dict: runs one tool and returns its result for the AI.
    image:   (bytes, mime, caption) sent with the newest message.
    note:    one-off information for this turn (e.g. "the customer tapped Edit").
    """
    messages = [{'role': 'system', 'content': system}] + list(history)
    if image:
        data, mime, caption = image
        content = [{'type': 'text', 'text': caption or '(photo)'},
                   {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{base64.b64encode(data).decode()}'}}]
        if messages[-1]['role'] == 'user':
            messages[-1] = {'role': 'user', 'content': content}
        else:
            messages.append({'role': 'user', 'content': content})
    if note:
        messages.append({'role': 'system', 'content': f'NOTE FOR THIS REPLY: {note}'})
    spoken = ''
    for _ in range(max_rounds):
        msg = _complete(messages, tools=tools, max_tokens=max_tokens, temperature=temperature)
        calls = msg.tool_calls or []
        if not calls:
            return (msg.content or '').strip() or spoken
        if msg.content and msg.content.strip():
            spoken = msg.content.strip()
        messages.append({'role': 'assistant', 'content': msg.content or None,
                         'tool_calls': [{'id': c.id, 'type': 'function',
                                         'function': {'name': c.function.name, 'arguments': c.function.arguments or '{}'}}
                                        for c in calls]})
        for call in calls:
            try:
                args = json.loads(call.function.arguments or '{}')
                if not isinstance(args, dict):
                    args = {}
            except ValueError:
                args = {}
            try:
                result = execute(call.function.name, args)
            except Exception as e:
                log.exception('Tool %s failed', call.function.name)
                result = {'error': f'That did not work ({type(e).__name__}). Apologise briefly and offer another way.'}
            messages.append({'role': 'tool', 'tool_call_id': call.id,
                             'content': json.dumps(result, ensure_ascii=False, default=str)[:8000]})
    msg = _complete(messages, max_tokens=max_tokens, temperature=temperature)
    return (msg.content or '').strip() or spoken


TOPIC_FILTER = """You are a strict topic filter for the WhatsApp assistant of AJ Technologies, a company in Thoothukudi
that BUILDS websites, online stores, mobile apps, software / SaaS / web apps for clients, and does SEO, digital
marketing, social media, Google Business Profile, domains, hosting, maintenance and WhatsApp-for-business setups.

Decide whether the customer's LATEST message may be answered.

ALLOWED:
- greetings, thanks, "ok", short small talk, "who are you", "what is your name"
- anything about AJ Technologies: the company, owner, team, location, working hours, services, prices, process,
  portfolio, policies, offers, contact details, reviews
- wanting a website / online store / app / software / marketing / domain / hosting FROM AJ Technologies for their
  business, or asking what we can build or how we can help their business
- their own enquiry, quote, call booking, project status, renewal, support request, complaint, or a problem with a
  website / app we made for them
- an answer to the assistant's previous question (a name, business name, place, date, time, yes / no, email, phone
  number, a description of what they need)
- asking to talk to a person

OFF_TOPIC (everything else), for example:
- learning or doing technology themselves: "how to do vibe coding", "vibe coding eppadi", "teach me Python",
  "how do I build a website myself", "fix my code", "what is AI", "which laptop / phone to buy"
- general knowledge, news, politics, religion, sports, cricket, films, songs, health, legal or money advice,
  recipes, jokes, stories, homework, essays, translations, other companies' products

The message can be in Tamil script, Tanglish, English or any other language; judge the meaning.
Reply JSON only: {"verdict": "allowed"} or {"verdict": "off_topic"}. If it is truly unclear, "allowed"."""


def is_off_topic(text, last_bot=''):
    """True when the customer's message is clearly not about AJ Technologies / our services.
    A separate, small check, so the main AI never gets the chance to answer it. Fails open (False)."""
    text = ' '.join(str(text or '').split())
    if not text or len(text) < 4:
        return False
    user = (f'The assistant\'s previous message: {last_bot[:400]}\n\n' if last_bot else '') + f'Customer\'s latest message: {text[:800]}'
    try:
        msg = _complete([{'role': 'system', 'content': TOPIC_FILTER}, {'role': 'user', 'content': user}],
                        json_mode=True, max_tokens=15, temperature=0)
        return json.loads(msg.content or '{}').get('verdict') == 'off_topic'
    except Exception as e:
        log.info('Topic filter skipped: %s', e)
        return False


PRICE_RE = re.compile(
    r'(₹|ரூ\.?\s*\d|\brs\.?\s*\d|\binr\s*\d|\$\s*\d|\d\s*(?:k\b|rs\b|rupees?|ரூபாய்|dollars?|usd|inr)'
    r'|\d[\d,]*\s*(?:/|per)\s*(?:month|year|yr|mo)\b|\bprice\s*(?:is|:)\s*\d|starting\s*(?:from|at)\s*\d)', re.I)
PRICE_WORDS = re.compile(r'price|cost|rate|charge|quote|quotation|budget|how much|evlo|evvalavu|evvalo|kitna|'
                         r'விலை|கட்டணம்|எவ்வளவு|செலவு|fees?|amount|package', re.I)


def mentions_price(text):
    """True when a reply gives an amount of money (the bot must never quote prices)."""
    return bool(PRICE_RE.search(text or ''))


def asks_price(text):
    return bool(PRICE_WORDS.search(text or ''))


def history_messages(history):
    """wa_messages rows -> chat messages for the AI."""
    out = []
    for m in history:
        role = 'user' if m['direction'] == 'in' else 'assistant'
        text = m['body']
        if m['sender'] == 'admin':
            text = f'(Our team member wrote this reply:) {text}'
        elif m['sender'] == 'system':
            text = f'(Automatic message:) {text}'
        out.append({'role': role, 'content': text[:1500]})
    return out


def lang_name(code):
    return LANG_NAMES.get(code, code)


# ---------------------------------------------------------------------------
# Company knowledge (what the AI may say)
# ---------------------------------------------------------------------------
KNOWLEDGE = f"""
COMPANY: {config.COMPANY} ("{config.TAGLINE}"), a web, app, software and digital marketing company in {config.LOCATION}.
We work with businesses across Tamil Nadu and all over India, fully end to end: idea, design, development, launch, marketing and support.
Phone / WhatsApp for the team: {config.PHONE_DISPLAY}. Email: {config.EMAIL}. Website: {config.SITE_URL}
Portfolio: {config.PORTFOLIO_URL}. Contact page: {config.CONTACT_URL}. Instagram: {config.INSTAGRAM}. YouTube: {config.YOUTUBE}

ABOUT US
- Founder, CEO and Owner: {config.OWNER_NAME}.
- Based in Thoothukudi (Tuticorin), Tamil Nadu. We serve businesses all over India; meetings can be online or by phone.
- A dedicated team of skilled developers and designers. (Never give a number of people.)
- We have built many successful websites, online stores, apps and software for shops, clinics, restaurants, schools,
  professionals, startups and growing brands, and our clients keep coming back for more. (Never give a number of
  projects, clients or years.)
- Availability: this assistant answers 24 hours a day, 7 days a week. Our team replies to every enquiry within 24 hours.
- Why choose us: everything custom built for the business (no copy-paste templates), modern and fast, mobile-first,
  SEO-ready, English & Tamil, honest advice, one team from idea to launch and support after launch.

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
- Do not ask for passwords, OTPs, card or bank details.

TOPICS YOU MAY HELP WITH (STRICT)
- ONLY: AJ Technologies (services, how we work, policies, contact, their enquiry / project / support request), and
  websites, online stores, apps, software, SaaS, domains, hosting, email, SEO, digital marketing, social media and
  WhatsApp for business, and general technology questions related to these.
- Short greetings, thanks and polite small talk are fine (reply briefly, then offer help).
- ANYTHING ELSE (general knowledge, news, politics, religion, sports, films, health, legal or money advice, recipes,
  homework, jokes, writing essays, other companies' products, coding someone's assignment...): do NOT answer it, not
  even partly. Reply with ONE polite sentence in their language, exactly in this spirit:
  "I'm AJ Technologies Assistant, so I can help only with AJ Technologies and our websites, apps, software and digital
  marketing services. Is there anything I can help you with on that?"

CLIENT DATA (STRICT)
- You only ever know THIS customer's own enquiry, projects and support requests (given below). Never mention, guess
  or reveal any other customer's or client's name, project, price or details, even if asked.
- If they ask about a project or request that is not listed below, say you can't find it for this number and offer
  talk_to_team. To show the full project status call show_project_status.

WHEN YOU DON'T KNOW
- If the question is about AJ Technologies or our services and the answer is not in the facts below, do not guess:
  say our team will confirm shortly AND call note_unanswered with the customer's question.
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
    {'type': 'function', 'function': {
        'name': 'show_project_status',
        'description': "An existing client asks about the status / progress of their own project, renewal or website.",
        'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {
        'name': 'raise_support_request',
        'description': 'An existing client reports a problem with their website/app or asks for a change (e.g. "my site is down", "change my photo").',
        'parameters': {'type': 'object', 'properties': {
            'description': {'type': 'string', 'description': 'The problem or change, in their words.'},
            'urgent': {'type': 'boolean', 'description': 'True if something is broken or down.'}}}}},
    {'type': 'function', 'function': {
        'name': 'show_my_requests', 'description': 'The customer asks about the status of their support requests / tickets.',
        'parameters': {'type': 'object', 'properties': {}}}},
    {'type': 'function', 'function': {
        'name': 'note_unanswered',
        'description': 'Save a question about AJ Technologies that you could not answer from the facts, so AJ can answer it. Use it together with your reply.',
        'parameters': {'type': 'object', 'properties': {'question': {'type': 'string'}}, 'required': ['question']}}},
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


def chat(contact, history, lang, mid_flow_note='', image=None, extra_note='', facts='', client=''):
    """Answer the customer. Returns (text, [(tool_name, args), ...]).

    facts:  FAQs / offers AJ added in the dashboard (bot_knowledge)
    client: ONLY this customer's own enquiry, projects and support requests
    """
    system = (RULES.format(lang=lang_name(lang)) + '\n' + KNOWLEDGE +
              (f'\nFACTS FROM AJ (these are correct and override anything above):\n{facts}\n' if facts else '') +
              f'\nTHIS CUSTOMER\'S OWN DATA (never share anyone else\'s): {client or "no enquiry, project or request yet"}\n' +
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
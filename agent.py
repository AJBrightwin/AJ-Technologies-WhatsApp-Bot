"""
The AI conversation with customers (upgrade v3).

Customers simply chat: they type, send a voice note or a photo, and the AI replies like a
person from our team. It asks for details one or two at a time and acts through the tools
below (save a quote request, book a call, raise a support request, save a review ...).
Buttons are used only where they help: the starting menu, and Submit / Edit under a summary.

Privacy: the AI only ever gets THIS customer's own data (their enquiry, projects, renewals,
calls and support requests), and every tool checks the WhatsApp number again.

If OpenAI is not available, NoAI is raised and bot.py answers with the button menus instead.
"""
import logging
import time
from datetime import datetime, timedelta

import ai
import bot
import config
import db
from texts import t

log = logging.getLogger('bot.agent')


class NoAI(Exception):
    """The AI could not answer and nothing was sent yet, so the menus can take over."""


DRAFT_DAYS = 7                      # a half-finished quote / support request is forgotten after this
HISTORY = 24                        # messages of the chat the AI reads every time

SERVICE_CODES = [code for code, _ in config.ENQUIRY_SERVICES]
TIMELINES = {'asap': 'As soon as possible', '1m': 'Within a month', '3m': 'In 1-3 months', 'explore': 'Just exploring'}
METHODS = {'whatsapp': 'WhatsApp', 'call': 'Phone call', 'email': 'Email'}

# what a tap on the starting menu means, in the customer's own words
MENU_NOTES = {
    'services': 'The customer tapped "Our services" in the menu. Briefly explain what we do and ask what they need.',
    'prices': 'The customer tapped "Prices" in the menu. Explain that every project is custom-built, so our team '
              'gives a free, clear quote after understanding their needs, and start finding out what they need.',
    'work': 'The customer tapped "Our work" in the menu. Tell them about two or three of our portfolio projects that '
            'fit them best (or ask what kind of business they have), and offer to send photos.',
    'quote': 'The customer tapped "Get a free quote" in the menu. Start collecting their enquiry with a friendly question.',
    'call': 'The customer tapped "Book a call" in the menu. Check get_call_slots and suggest a few free times.',
    'project': 'The customer tapped "My project" in the menu. Tell them the status of their own project(s) from '
               'CUSTOMER DATA, or say you cannot find a project for this WhatsApp number.',
    'support': 'The customer tapped "Support request" in the menu. Ask what the problem or change is.',
    'team': 'The customer tapped "Talk to our team". Call talk_to_team and tell them we will contact them within 24 hours.',
    'review': 'The customer tapped "Write a review". Start collecting their review (star rating first).',
}


# ===========================================================================
# Entry point (from bot.handle_message)
# ===========================================================================
def route(c, kind, text, action, media, first_time):
    low = bot.plain(text)
    if action:
        return on_action(c, action, text)
    if kind in ('image', 'document', 'video', 'sticker', 'location', 'contacts'):
        return on_media(c, kind, text, media)
    if kind not in ('text', 'audio', 'button', 'interactive', 'request_welcome'):
        return bot.say(c, 'unsupported')
    if not text:
        return None
    if low in bot.STOP_WORDS:
        db.update_contact(c['wa_id'], opted_out=True, opted_out_at=db.now(), state={})
        return bot.say(c, 'stop_done')
    if low in bot.START_WORDS and c.get('opted_out'):
        db.update_contact(c['wa_id'], opted_out=False, opted_out_at=None)
        return bot.say(c, 'start_done')
    if low in bot.MENU_WORDS or low in bot.START_WORDS:
        return bot.send_menu(c)
    if bot.GREETINGS.match(text) and (first_time or kind == 'request_welcome' or quiet_for(c, hours=12)):
        return bot.welcome(c)
    if bot.GREETINGS.match(text) is None and ai.is_off_topic(text, last_bot_text(c)):
        return bot.say(c, 'off_topic')            # never let the main AI answer off-topic questions
    return converse(c)


def last_bot_text(c):
    for m in reversed(db.recent_messages(c['wa_id'], 4)):
        if m['direction'] == 'out':
            return m['body']
    return ''


def quiet_for(c, hours):
    last = c.get('last_outbound_at')
    return not last or db.now() - last > timedelta(hours=hours)


def on_action(c, action, title):
    a = action.strip()
    head = a.split(':')[0]
    if a == 'ai:enq:submit':
        return submit_enquiry_button(c)
    if a == 'ai:enq:edit':
        return converse(c, note='The customer tapped "Edit" under the enquiry summary. Ask what they would like to change.')
    if a == 'ai:sp:submit':
        return submit_support_button(c)
    if a == 'ai:sp:edit':
        return converse(c, note='The customer tapped "Edit" under the support request summary. Ask what to change.')
    if head == 'm':
        item = a[2:]
        if item == 'lang':
            return bot.ask_language(c)
        if item in MENU_NOTES:
            return converse(c, note=MENU_NOTES[item])
        return converse(c, note=f'The customer tapped the button "{title}". If they want the options menu, call '
                                'show_menu; otherwise ask how you can help.')
    if head == 'lang':
        return bot.set_language(c, a[5:])
    if a == 'pf:more':
        return converse(c, note='The customer wants to see more of our work.')
    if head == 'pf':
        if bot.show_project(c, a[3:], follow_up=False):
            return None
        return converse(c, note='The customer wants to see our work.')
    if head == 'svc':
        name = dict(config.SERVICES).get(a[4:], a[4:])
        return converse(c, note=f'The customer is interested in our service "{name}". Explain it briefly and ask about their needs.')
    if head == 'fu':
        return followup_reply(c, a)
    if head == 'rn':
        return renewal_reply(c, a)
    if a == 'sp:list':
        return converse(c, note='The customer wants the status of their support requests (see CUSTOMER DATA).')
    if a == 'rv:start':
        return converse(c, note=MENU_NOTES['review'])
    return converse(c, note=f'The customer tapped an old button "{title}". Continue the conversation from what they '
                            'need now.')


def on_media(c, kind, caption, media):
    if kind == 'sticker':
        return None
    if kind == 'image':
        image = None
        if media.get('id'):
            data, mime = bot.wa.download_media(media['id'], max_bytes=5 * 1024 * 1024)
            if data and (mime or '').startswith('image/'):
                image = (data, mime, caption or '(photo)')
        note = 'The customer sent a photo' + (f' with the caption "{caption}"' if caption else '') + \
               '. Look at it and reply about it in context (e.g. a screenshot of a problem, a design they like, ' \
               'their shop or logo). If it has nothing to do with our work, politely say what you can help with.'
        if not image:
            note = 'The customer sent a photo, but it could not be opened. Thank them and say our team can see it.'
        return converse(c, note=note, image=image)
    if kind == 'document':
        filename = media.get('filename') or 'file'
        forward_file(c, media, caption)
        a = load(c)
        for key in ('enquiry', 'support'):
            if a.get(key):
                a[key]['attachments'] = int(a[key].get('attachments') or 0) + 1
        save(c, a)
        note = (f'The customer sent a file named "{filename}"' + (f' with the message "{caption}"' if caption else '') +
                '. You cannot open files, but it has already been forwarded to our team, who will go through it. '
                'Thank them in one short sentence and carry on with the conversation (for example, if they are '
                'telling us about a project, continue collecting the details).')
        try:
            return converse(c, note=note)
        except NoAI:
            return bot.say(c, 'ai_file_ack')
    if kind == 'video':
        return converse(c, note='The customer sent a video. You cannot watch videos, but our team can see it in the '
                                'chat. Thank them and continue the conversation.' + (f' Caption: "{caption}"' if caption else ''))
    return converse(c, note=f'The customer shared this: {caption}')


def forward_file(c, media, caption=''):
    """Queue the customer's file for AJ (jobs.py sends it as a document, with the file attached)."""
    if not media.get('id'):
        return
    name = bot.display_name(c) or 'A customer'
    filename = (media.get('filename') or 'file')[:200]
    db.queue_alert('admin_file', f'{name} sent a file: {filename}', wa_id=c['wa_id'], customer_name=name,
                   customer_phone=bot.phone_display(c['wa_id']),
                   detail=db.dumps({'media_id': media['id'], 'mime': media.get('mime', ''), 'filename': filename,
                                    'caption': (caption or '')[:500]}))


# ===========================================================================
# The conversation
# ===========================================================================
class Turn:
    """What happened during one reply: things to send after the AI's text, and plain fallbacks."""

    def __init__(self):
        self.after = []        # [(kind, value)] sent after the AI's text, in order
        self.fallback = []     # fixed texts to send if the AI fails after a tool already did something
        self.acted = False


def converse(c, note='', image=None):
    if not ai.enabled():
        raise NoAI('no OpenAI key')
    a = load(c)
    turn = Turn()
    history = ai.history_messages(db.recent_messages(c['wa_id'], HISTORY))
    if not history or history[-1]['role'] != 'user':
        history.append({'role': 'user', 'content': '(see the note)' if note else '(message)'})
    if not note and history and ai.asks_price(history[-1]['content']):
        note = ('The customer is asking about price / a quote. NEVER give any amount, range, estimate or currency. Say '
                'every project is custom-built and our team sends a free, clear quote within 24 hours, then collect the '
                'enquiry details (save_enquiry_details / show_enquiry_summary).')
    try:
        reply = ai.run_agent(system_prompt(c, a), history, TOOLS, lambda name, args: run_tool(c, a, turn, name, args),
                             image=image, note=note, max_rounds=5, max_tokens=700)
    except Exception as e:
        save(c, a)
        if not turn.acted:
            raise NoAI(str(e)[:200])
        log.warning('AI failed after a tool ran (%s); sending the plain confirmation', e)
        reply = ''
    save(c, a)
    customer_text = next((m['content'] for m in reversed(history) if m['role'] == 'user' and isinstance(m['content'], str)), '')
    log.info('AI reply to %s (%s): %s', c['wa_id'][-4:], config.VERSION, (reply or '')[:120].replace('\n', ' '))
    deliver(c, reply, turn, customer_text)


def deliver(c, reply, turn, customer_text=''):
    reply = ai.guard_reply(bot.lang(c), customer_text, reply)
    sent = False
    if reply:
        bot.text_to(c, reply)
        sent = True
    elif turn.fallback:
        for text in turn.fallback:
            bot.text_to(c, text)
        sent = True
    for kind, value in turn.after:
        try:
            if kind == 'enq_summary':
                send_enquiry_summary(c, value, with_hint=not sent)
            elif kind == 'sp_summary':
                send_support_summary(c, value, with_hint=not sent)
            elif kind == 'project':
                bot.show_project(c, value, follow_up=False)
            elif kind == 'menu':
                bot.send_menu(c)
            sent = True
        except Exception:
            log.exception('Could not send %s', kind)
    if not sent:
        bot.send_menu(c, t(bot.lang(c), 'didnt_get'))


# ===========================================================================
# Drafts (a half-finished quote / support request), kept in wa_contacts.state
# ===========================================================================
def load(c):
    st = c.get('state') or {}
    a = dict(st.get('ai') or {})
    try:
        updated = datetime.fromisoformat(a.get('updated')) if a.get('updated') else None
    except ValueError:
        updated = None
    if updated and db.now() - updated > timedelta(days=DRAFT_DAYS):
        a = {}
    return a


def save(c, a):
    """Store the drafts; old v1/v2 menu flows are dropped, the AI takes over from the chat history."""
    state = {}
    a = {k: v for k, v in a.items() if v not in (None, {}, [], '')}
    if any(k in a for k in ('enquiry', 'support')):
        a['updated'] = db.now().isoformat()
        state['ai'] = a
        state['ai_pending'] = 'enquiry' if 'enquiry' in a else 'support'
    elif a.get('last_enquiry_id') or a.get('last_ticket_id'):
        state['ai'] = {k: a[k] for k in ('last_enquiry_id', 'last_ticket_id') if k in a}
    if state != (c.get('state') or {}):
        bot.set_state(c, state)


def enquiry_missing(e):
    missing = []
    if not bot.valid_name(e.get('name')):
        missing.append('name')
    if not e.get('services'):
        missing.append('service')
    if len((e.get('message') or '').strip()) < 3:
        missing.append('requirement (what they want built)')
    if e.get('method') == 'email' and not e.get('email'):
        missing.append('email address (they chose email)')
    return missing


def enquiry_view(e):
    return {
        'name': e.get('name') or None, 'business': e.get('business') or None,
        'services': [dict(config.ENQUIRY_SERVICES)[s] for s in e.get('services') or []] or None,
        'requirement': e.get('message') or None, 'timeline': TIMELINES.get(e.get('timeline')) or None,
        'contact_by': METHODS.get(e.get('method')) or None, 'email': e.get('email') or None,
        'phone': bot.phone_display(e.get('phone')) if e.get('phone') else None,
        'files_shared': e.get('attachments') or 0, 'summary_shown': bool(e.get('summary_shown')),
    }


# ===========================================================================
# What the AI knows
# ===========================================================================
RULES = """
You are "AJ Technologies Assistant", the official WhatsApp assistant of AJ Technologies. You chat with customers like a
helpful, professional member of our team. (You are an AI assistant; say so honestly if someone asks.)

LANGUAGE
- Always reply in the language and script of the customer's latest message: Tamil script -> Tamil script; Tamil written
  in English letters (Tanglish) -> Tanglish; English -> English; any other language -> that language.
  (Their usual language: {lang}.)

STYLE
- Professional, warm and polite. Short WhatsApp messages: usually 1-4 sentences, at most about 110 words.
- Emojis: rarely, at most one per message, and none in most messages.
- *bold* for a key word now and then. No markdown headings, no tables. Short lists only when really needed.
- Ask at most two questions per message. Never ask for something the customer already told you (check the chat and the
  drafts below).
- Do not offer menus or option lists; just talk. Only if the customer asks for the menu / options, call show_menu.

WHO YOU ARE
- If asked your name or who you are: you are AJ Technologies Assistant, the virtual assistant of AJ Technologies, and
  ask how you can help (in their language).

WHAT YOU HELP WITH (STRICT)
- ONLY: AJ Technologies (the company, owner, team, services, how we work, policies, contact details, our portfolio),
  this customer's own enquiry / call / project / renewals / support requests, and getting a website, online store,
  app, software, SaaS, domain, hosting, SEO, digital marketing or WhatsApp-for-business setup FROM AJ Technologies.
- Everything else is off-topic, even technology in general: e.g. "how do I code / vibe code", "teach me Python",
  "fix my code", "which laptop to buy", "write an essay", general knowledge, news, politics, religion, sports, films,
  health, legal or money advice, recipes, jokes, homework, other companies. Do not answer it, not even partly or with
  tips. Reply with one polite sentence in their language in this spirit: "I'm AJ Technologies Assistant, so I can
  help only with AJ Technologies and our services. Would you like a website, app or software for your business?"
- Greetings, thanks and short small talk are fine: reply briefly and offer help.

SELLING (be an excellent, honest salesperson)
- When someone needs a website / app / software / marketing, show real interest in their business, say briefly and
  confidently how we can help them grow, and guide them to a free quote.
- Speak about our experience and quality persuasively, but NEVER give numbers (no counts of projects, clients, years or
  team size) and never invent clients, results, awards or reviews.

PRICES AND TIMELINES (STRICT)
- NEVER give any price, cost, range, "starting from" amount, discount or estimate, even if asked many times. Explain
  that every project is custom-built for the business, so our team gives a free, clear quote once they understand the
  requirement - then start collecting the enquiry.
- NEVER promise a delivery date or timeline; it is agreed after the free consultation.

COLLECTING AN ENQUIRY (QUOTE REQUEST)
- Have a natural conversation. Find out, one or two things at a time: what they want built and why (requirement,
  features, goal), which service, their business (name, what it does, where), their name, when they would like to
  start, and how our team should contact them (WhatsApp, phone call or email - and the email address if they choose
  email). Their phone number is this WhatsApp number unless they give another one.
- Save details with save_enquiry_details as soon as you learn them (several at once is fine, every turn if needed).
- When name, service and requirement are known and you have asked about the timeline and contact method, call
  show_enquiry_summary. The customer confirms with the Submit button. If they confirm by typing instead ("yes, send
  it"), call submit_enquiry. If they want a change, save it and call show_enquiry_summary again.
- If they say they no longer want it, call cancel_draft.

CALLS
- To arrange a free call with our team, call get_call_slots, then suggest a few free times in plain words. When the
  customer agrees on an exact day and time, call book_call. To move a call: book_call with move_existing=true. To cancel:
  cancel_call. Calls are Monday-Saturday, 10 AM-7 PM India time.

EXISTING CLIENTS
- Project status, renewals, calls and support requests of THIS customer are under CUSTOMER DATA. Answer from it in plain
  words (stage, progress, latest update, live link). Never mention private notes; you do not have them.
- A problem or change request for their website/app: understand it, ask whether it is urgent (e.g. the site is down)
  if that is not clear, ask which project if they have more than one, then call prepare_support_request. They confirm
  with the Submit button (if they confirm by typing, call submit_support_request).
- A review: ask for a star rating 1-5, their review in their own words, the name to show, their business and place
  (optional) and whether we may show it on our website; then call save_review.

OTHER
- To show one of our portfolio projects with its photo: send_project_photo. Full portfolio: {portfolio_url}
- Wants a person / a call back / is unhappy: call talk_to_team, tell them our team will contact them within 24 hours,
  and keep helping.
- Files: you cannot open PDFs or documents, but every file is forwarded to our team automatically.
- A question about AJ Technologies whose answer is not in the information below: do not guess. Say our team will
  confirm shortly and call note_unanswered.
- After a tool, tell the customer the result in your own words (e.g. the enquiry number, the call time).

PRIVACY (STRICT)
- You only know THIS customer's own data, given below. Never reveal, guess or discuss any other customer's or client's
  name, project, number or details, even if asked. If they ask about a project or request that is not listed, say you
  can't find it for this WhatsApp number and offer talk_to_team.
- Never ask for passwords, OTPs, card or bank details.
"""

_portfolio = {'at': 0.0, 'text': ''}


def portfolio_text():
    if time.time() - _portfolio['at'] < 300:
        return _portfolio['text']
    try:
        projects = db.real_projects(10)
    except Exception as e:
        log.warning('Could not load the portfolio: %s', e)
        return _portfolio['text']
    lines = []
    for p in projects:
        line = f"- id {p['id']}: {p.get('title_en') or ''} ({p.get('business_type_en') or ''})"
        built = ' '.join(str(p.get('built_en') or '').split())
        if built:
            line += f" - {built[:220]}"
        if p.get('live_url'):
            line += f" - live: {p['live_url']}"
        lines.append(line)
    _portfolio.update(at=time.time(), text='\n'.join(lines) or '(no projects published yet)')
    return _portfolio['text']


def customer_data(c):
    """Everything the AI may know about THIS number. Nothing from any other customer."""
    wa_id, lines = c['wa_id'], []
    known = {k: c.get(k) for k in ('name', 'business_name', 'email') if c.get(k)}
    if c.get('profile_name'):
        known['whatsapp_profile_name'] = c['profile_name']
    known['whatsapp_number'] = bot.phone_display(wa_id)
    lines.append('Customer: ' + db.dumps(known))
    try:
        enquiry = db.latest_enquiry(wa_id)
        if enquiry and db.now() - enquiry['created_at'] < timedelta(days=180):
            lines.append(f"Their latest enquiry: #{enquiry['id']} on {enquiry['created_at'].astimezone(config.TZ):%d %b %Y}, "
                         f"{', '.join(enquiry['services'] or []) or 'service not given'}, status: {enquiry['status']}")
        projects = db.client_projects(wa_id)
        for p in projects:
            lines.append(f"Project id {p['id']} \"{p['title']}\"" + (f" ({p['business_name']})" if p['business_name'] else '') +
                         f": stage {t('en', 'stage_' + p['stage'])}, {p['progress']}% done"
                         + (f", latest update for the client: {p['client_note'][:400]}" if p['client_note'] else '')
                         + (f", live link: {p['live_url']}" if p['live_url'] else ''))
        for r in db.client_renewals([p['id'] for p in projects], days=60):
            lines.append(f"Renewal: {t('en', 'item_' + r['item'])} {r['label']} expires on {r['expiry_date']:%d %b %Y}")
        booking = db.upcoming_booking(wa_id)
        if booking:
            lines.append(f"Booked call: {booking['call_date']:%A %d %b %Y} at "
                         f"{bot.time_label(booking['call_time'].strftime('%H:%M'))} (topic: {booking['topic'] or '-'})")
        for tk in db.client_tickets(wa_id, 5):
            lines.append(f"Support request #{tk['id']} ({tk['created_at'].astimezone(config.TZ):%d %b}): "
                         f"{t('en', 'tk_' + tk['status'])}, \"{' '.join(tk['description'].split())[:160]}\""
                         + (f", latest note from our team: {tk['client_update'][:200]}" if tk['client_update'] else ''))
    except Exception as e:
        log.warning('Could not load the customer data: %s', e)
    if len(lines) == 1:
        lines.append('No enquiry, project, call or support request yet.')
    return '\n'.join(lines)


def system_prompt(c, a):
    parts = [RULES.format(lang=ai.lang_name(bot.lang(c)), portfolio_url=config.PORTFOLIO_URL), ai.KNOWLEDGE]
    parts.append('OUR PORTFOLIO (real client projects you may talk about):\n' + portfolio_text())
    facts = bot.facts_text()
    if facts:
        parts.append('FACTS FROM AJ (correct and up to date; they override anything above):\n' + facts)
    parts.append('CUSTOMER DATA (only this customer):\n' + customer_data(c))
    if a.get('enquiry'):
        e = a['enquiry']
        parts.append('ENQUIRY DRAFT IN PROGRESS: ' + db.dumps(enquiry_view(e)) +
                     (f"\nStill needed: {', '.join(enquiry_missing(e))}" if enquiry_missing(e) else
                      '\nAll required details are there.'))
    elif a.get('last_enquiry_id'):
        parts.append(f"This customer already submitted enquiry #{a['last_enquiry_id']} in this chat.")
    if a.get('support'):
        parts.append('SUPPORT REQUEST DRAFT IN PROGRESS: ' + db.dumps(a['support']))
    now = bot.now_ist()
    parts.append(f'NOW: {now:%A %d %B %Y, %I:%M %p} India time.')
    parts.append('REMEMBER: answer ONLY about AJ Technologies, our services and this customer\'s own work with us. For '
                 'anything else (e.g. how to do vibe coding / coding / any general topic) do not explain it at all: reply with '
                 'the one polite "I\'m AJ Technologies Assistant, so I can help only with AJ Technologies..." sentence. '
                 'Keep replies short (max about 110 words), at most one emoji, no numbered lists unless really needed.')
    return '\n\n'.join(parts)


# ===========================================================================
# Tools
# ===========================================================================
def _fn(name, description, properties=None, required=None):
    params = {'type': 'object', 'properties': properties or {}}
    if required:
        params['required'] = required
    return {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': params}}


TOOLS = [
    _fn('save_enquiry_details', 'Save details of a quote request (enquiry) as soon as the customer gives them. Only '
        'include what they actually said.', {
            'name': {'type': 'string', 'description': "The customer's name."},
            'business_name': {'type': 'string', 'description': 'Business name, and what it does / where, if given.'},
            'services': {'type': 'array', 'items': {'type': 'string', 'enum': SERVICE_CODES},
                         'description': 'web = website, shop = online store / e-commerce, saas = web app / software / '
                                        'portal, app = mobile app, mkt = SEO / marketing / social media, other.'},
            'requirement': {'type': 'string', 'description': 'Everything they want built, features and goals, in '
                                                             'their words (the full, updated description).'},
            'timeline': {'type': 'string', 'enum': list(TIMELINES)},
            'contact_method': {'type': 'string', 'enum': list(METHODS)},
            'email': {'type': 'string'},
            'phone': {'type': 'string', 'description': 'Only if they want to be contacted on another number.'}}),
    _fn('show_enquiry_summary', 'Show the customer a summary of their enquiry with Submit and Edit buttons.'),
    _fn('submit_enquiry', 'Submit the enquiry. ONLY after the summary was shown and the customer clearly confirmed in '
        'words. (Tapping the Submit button submits it automatically.)'),
    _fn('cancel_draft', 'The customer no longer wants to continue the enquiry or support request in progress.',
        {'which': {'type': 'string', 'enum': ['enquiry', 'support']}}, ['which']),
    _fn('get_call_slots', 'Free times for a phone call with our team (next 7 days, or one day).',
        {'date': {'type': 'string', 'description': 'YYYY-MM-DD, only to check one day.'}}),
    _fn('book_call', 'Book the call. Only after the customer agreed to this exact day and time.', {
        'date': {'type': 'string', 'description': 'YYYY-MM-DD'},
        'time': {'type': 'string', 'description': 'HH:MM, 24-hour, one of the free times'},
        'topic': {'type': 'string', 'description': 'What they want to discuss.'},
        'name': {'type': 'string', 'description': "The customer's name, if known."},
        'move_existing': {'type': 'boolean', 'description': 'True to move their already booked call to this time.'}},
        ['date', 'time']),
    _fn('cancel_call', "Cancel the customer's booked call (after they asked for it)."),
    _fn('prepare_support_request', 'Show a summary of a support request (problem / change for their website or app) '
        'with Submit and Edit buttons.', {
            'description': {'type': 'string', 'description': 'The problem or change, clearly, in their words.'},
            'urgent': {'type': 'boolean', 'description': 'True if something is broken / down / blocking their business.'},
            'project_id': {'type': 'integer', 'description': 'Their project id from CUSTOMER DATA, if they have one.'}},
        ['description', 'urgent']),
    _fn('submit_support_request', 'Submit the support request. ONLY after its summary was shown and the customer '
        'confirmed in words.'),
    _fn('save_review', "Save the customer's review of AJ Technologies.", {
        'rating': {'type': 'integer', 'minimum': 1, 'maximum': 5},
        'review_text': {'type': 'string', 'description': 'Their review exactly in their words.'},
        'display_name': {'type': 'string'}, 'business_name': {'type': 'string'}, 'location': {'type': 'string'},
        'publish_on_website': {'type': 'boolean', 'description': 'True only if they agreed we may show it.'}},
        ['rating', 'review_text', 'publish_on_website']),
    _fn('send_project_photo', 'Send the photo and short description of one of our portfolio projects.',
        {'project_id': {'type': 'integer'}}, ['project_id']),
    _fn('show_menu', 'Send the options menu. Only when the customer asks for the menu / options.'),
    _fn('talk_to_team', 'The customer wants a person, a call back, or is unhappy. Alerts our team (they reply within '
        '24 hours).', {'reason': {'type': 'string'}}),
    _fn('note_unanswered', 'Save a question about AJ Technologies you could not answer, so the owner can add the '
        'answer. Use it together with your reply.', {'question': {'type': 'string'}}, ['question']),
]


def run_tool(c, a, turn, name, args):
    fn = TOOL_FUNCS.get(name)
    if not fn:
        return {'error': f'Unknown tool {name}'}
    return fn(c, a, turn, args)


# ---- enquiry ---------------------------------------------------------------
def tool_save_enquiry(c, a, turn, args):
    e = a.setdefault('enquiry', {'name': c.get('name') or '', 'business': c.get('business_name') or '',
                                 'email': c.get('email') or '', 'services': [], 'phone': c['wa_id'], 'attachments': 0})
    rejected = []
    if args.get('name'):
        name = bot.valid_name(args['name'])
        if name:
            e['name'] = ' '.join(w[:1].upper() + w[1:] for w in name.split())
        else:
            rejected.append('name (does not look like a name)')
    if args.get('business_name'):
        e['business'] = str(args['business_name']).strip()[:160]
    services = [s for s in args.get('services') or [] if s in SERVICE_CODES]
    if services:
        e['services'] = list(dict.fromkeys((e.get('services') or []) + services))
    if args.get('requirement'):
        e['message'] = str(args['requirement']).strip()[:1500]
    if args.get('timeline') in TIMELINES:
        e['timeline'] = args['timeline']
    if args.get('contact_method') in METHODS:
        e['method'] = args['contact_method']
    if args.get('email'):
        email = str(args['email']).strip()
        if bot.EMAIL_RE.match(email):
            e['email'] = email[:254]
        else:
            rejected.append('email (not a valid address, ask again)')
    if args.get('phone'):
        phone = bot.normalise_phone(args['phone'])
        if phone:
            e['phone'] = phone
        else:
            rejected.append('phone (not a valid number, ask again)')
    e['summary_shown'] = False
    still = enquiry_missing(e)
    optional = [label for key, label in (('timeline', 'when they want to start'), ('method', 'how to contact them'),
                                         ('business', 'business name')) if not e.get(key)]
    return {'saved': True, 'draft': enquiry_view(e), 'still_needed': still, 'not_asked_yet_optional': optional,
            'problems': rejected,
            'next': 'Ask for the missing details naturally.' if still else
                    'When timeline and contact method are asked, call show_enquiry_summary.'}


def tool_show_enquiry_summary(c, a, turn, args):
    e = a.get('enquiry')
    if not e:
        return {'error': 'No enquiry in progress. Collect the details first with save_enquiry_details.'}
    missing = enquiry_missing(e)
    if missing:
        return {'error': 'Ask for these first: ' + ', '.join(missing)}
    e['summary_shown'] = True
    turn.after.append(('enq_summary', dict(e)))
    return {'ok': True, 'note': 'The summary with Submit and Edit buttons is sent right after your reply. Reply with '
                                'ONE short sentence asking them to check it and tap Submit, or tell you what to change. '
                                'Do not repeat the details.'}


def tool_submit_enquiry(c, a, turn, args):
    e = a.get('enquiry')
    if not e:
        if a.get('last_enquiry_id'):
            return {'already_submitted': True, 'enquiry_id': a['last_enquiry_id']}
        return {'error': 'No enquiry in progress.'}
    if enquiry_missing(e):
        return {'error': 'Ask for these first: ' + ', '.join(enquiry_missing(e))}
    if not e.get('summary_shown'):
        return {'error': 'Call show_enquiry_summary first and let the customer confirm.'}
    enquiry_id = finish_enquiry(c, a)
    turn.acted = True
    turn.fallback.append(t(bot.lang(c), 'enq_done', name=e['name'].split()[0], id=enquiry_id))
    return {'ok': True, 'enquiry_id': enquiry_id,
            'note': f'Thank {e["name"].split()[0]}, give the enquiry number #{enquiry_id} and say our team will contact '
                    'them within 24 hours. You may offer a free call.'}


def finish_enquiry(c, a):
    e = a.pop('enquiry')
    data = {'name': e['name'], 'business': e.get('business') or '', 'services': e.get('services') or [],
            'timeline': e.get('timeline') or '', 'method': e.get('method') or '', 'email': e.get('email') or '',
            'phone': e.get('phone') or c['wa_id'], 'message': e.get('message') or '',
            'attachments': int(e.get('attachments') or 0)}
    enquiry_id = bot.save_enquiry(c, data)
    a['last_enquiry_id'] = enquiry_id
    return enquiry_id


def submit_enquiry_button(c):
    a = load(c)
    e = a.get('enquiry')
    if not e:
        if a.get('last_enquiry_id') or db.latest_enquiry(c['wa_id']):
            return bot.say(c, 'enq_already')
        return converse(c, note='The customer tapped Submit, but there is no enquiry in progress. Ask what they need.')
    if enquiry_missing(e):
        return converse(c, note='The customer tapped Submit, but some details are missing: '
                                f"{', '.join(enquiry_missing(e))}. Ask for them.")
    enquiry_id = finish_enquiry(c, a)
    save(c, a)
    bot.say(c, 'enq_done', name=e['name'].split()[0], id=enquiry_id)


def send_enquiry_summary(c, e, with_hint=False):
    L = bot.lang(c)
    dash = t(L, 'not_given')
    services = ', '.join(bot.service_label(c, s) for s in e.get('services') or []) or dash
    body = t(L, 'summary', name=e.get('name') or dash, business=e.get('business') or dash, services=services,
             timeline=t(L, f"tl_{e['timeline']}") if e.get('timeline') else dash,
             method=t(L, f"cm_{e['method']}") if e.get('method') else dash,
             phone=bot.phone_display(e.get('phone') or c['wa_id']) or dash, email=e.get('email') or dash,
             message=(e.get('message') or dash)[:500])
    if e.get('attachments'):
        body += f"\n📎 {e['attachments']}"
    if with_hint:
        body += '\n\n' + t(L, 'ai_check_summary')
    bot.buttons(c, body, [('ai:enq:submit', 'b_submit'), ('ai:enq:edit', 'b_edit')])


def tool_cancel_draft(c, a, turn, args):
    which = args.get('which')
    if which in ('enquiry', 'support') and a.pop(which, None) is not None:
        return {'ok': True, 'note': 'Cancelled. Tell them politely that they can come back anytime.'}
    return {'ok': True, 'note': 'Nothing was in progress.'}


# ---- calls -----------------------------------------------------------------
def tool_get_call_slots(c, a, turn, args):
    out = {'call_days': 'Monday to Saturday', 'call_hours': '10 AM to 7 PM India time'}
    existing = db.upcoming_booking(c['wa_id'])
    if existing:
        out['already_booked'] = f"{existing['call_date']:%A %d %b %Y} at {bot.time_label(existing['call_time'].strftime('%H:%M'))}"
    day = bot.to_date(args.get('date')) if args.get('date') else None
    if day:
        slots = bot.free_slots(day) if day.weekday() in config.CALL_WEEKDAYS else []
        out['date'] = f'{day:%A %d %b %Y}'
        out['free_times'] = [{'time': s, 'label': bot.time_label(s)} for s in slots]
        if not slots:
            out['note'] = 'No free time that day; suggest another day.'
        return out
    days = []
    for d, _ in bot.open_days()[:6]:
        slots = bot.free_slots(d)
        days.append({'date': d.isoformat(), 'day': f'{d:%A %d %b}', 'free_times': [bot.time_label(s) for s in slots],
                     'free_times_24h': slots})
    out['open_days'] = days
    if not days:
        out['note'] = 'All call times are full this week. Offer talk_to_team instead.'
    return out


def tool_book_call(c, a, turn, args):
    day = bot.to_date(args.get('date'))
    slot = str(args.get('time') or '')[:5]
    if not day:
        return {'error': 'Give the date as YYYY-MM-DD.'}
    if len(slot) == 4 and slot[1] == ':':
        slot = '0' + slot
    existing = db.upcoming_booking(c['wa_id'])
    if existing and not args.get('move_existing'):
        return {'error': 'They already have a call booked on '
                         f"{existing['call_date']:%A %d %b} at {bot.time_label(existing['call_time'].strftime('%H:%M'))}. "
                         'Ask if they want to move it; if yes, call book_call again with move_existing=true.'}
    if day.weekday() not in config.CALL_WEEKDAYS or slot not in bot.free_slots(day):
        free = bot.free_slots(day) if day.weekday() in config.CALL_WEEKDAYS else []
        return {'error': 'That time is not free.', 'free_times_that_day': [bot.time_label(s) for s in free],
                'note': 'Suggest one of the free times, or call get_call_slots for other days.'}
    name = bot.valid_name(args.get('name')) or bot.display_name(c)
    booking = bot.book_slot(c, name, day, slot, str(args.get('topic') or '')[:500],
                            replace_id=existing['id'] if existing else None)
    if not booking:
        return {'error': 'Someone just took that time. Suggest another free time.'}
    turn.acted = True
    when = bot.when_label(c, day, slot)
    turn.fallback.append(t(bot.lang(c), 'ai_booked', when=when, phone=bot.phone_display(c['wa_id'])))
    return {'ok': True, 'booked': f'{day:%A %d %B %Y} at {bot.time_label(slot)}',
            'we_will_call': bot.phone_display(c['wa_id']),
            'note': 'Confirm the day, time and the number we will call. Mention they can message here to change it.'}


def tool_cancel_call(c, a, turn, args):
    booking = db.upcoming_booking(c['wa_id'])
    if not booking:
        return {'error': 'They have no booked call.'}
    bot.cancel_booking(c, booking)
    turn.acted = True
    when = bot.when_label(c, booking['call_date'], booking['call_time'].strftime('%H:%M'))
    turn.fallback.append(t(bot.lang(c), 'bk_cancelled', when=when))
    return {'ok': True, 'cancelled': when}


# ---- support ---------------------------------------------------------------
def tool_prepare_support(c, a, turn, args):
    desc = ' '.join(str(args.get('description') or '').split())[:2000]
    if len(desc) < 3:
        return {'error': 'Ask what the problem or change is.'}
    projects = db.client_projects(c['wa_id'])
    project = None
    if args.get('project_id'):
        try:
            project = db.client_project(int(args['project_id']), c['wa_id'])     # only their own project
        except (TypeError, ValueError):
            project = None
        if not project:
            return {'error': 'That project is not linked to this WhatsApp number. Use only the projects in CUSTOMER DATA.'}
    elif len(projects) == 1:
        project = projects[0]
    elif len(projects) > 1:
        return {'error': 'They have more than one project. Ask which one: ' +
                         ', '.join(f"{p['title']} (id {p['id']})" for p in projects)}
    old = a.get('support') or {}
    a['support'] = {'desc': desc, 'priority': 'urgent' if args.get('urgent') else 'normal',
                    'project_id': project['id'] if project else None, 'project_title': project['title'] if project else '',
                    'attachments': int(old.get('attachments') or 0), 'summary_shown': True}
    turn.after.append(('sp_summary', dict(a['support'])))
    return {'ok': True, 'note': 'The summary with Submit and Edit buttons is sent right after your reply. Reply with '
                                'ONE short sentence asking them to check it and tap Submit.'}


def tool_submit_support(c, a, turn, args):
    sp = a.get('support')
    if not sp or not sp.get('summary_shown'):
        return {'error': 'Call prepare_support_request first and let the customer confirm.'}
    ticket = finish_support(c, a)
    turn.acted = True
    turn.fallback.append(t(bot.lang(c), 'sp_done', id=ticket['id']))
    return {'ok': True, 'request_id': ticket['id'],
            'note': f'Give the request number #{ticket["id"]} and say our team will update them right here.'}


def finish_support(c, a):
    sp = a.pop('support')
    ticket = bot.save_support(c, {'project_id': sp.get('project_id'), 'project_title': sp.get('project_title') or '',
                                  'desc': sp['desc'], 'attachments': int(sp.get('attachments') or 0),
                                  'priority': sp.get('priority') or 'normal'})
    a['last_ticket_id'] = ticket['id']
    return ticket


def submit_support_button(c):
    a = load(c)
    if not a.get('support'):
        if a.get('last_ticket_id'):
            return bot.say(c, 'sp_done', id=a['last_ticket_id'])
        return converse(c, note='The customer tapped Submit, but there is no support request in progress. Ask what the problem is.')
    ticket = finish_support(c, a)
    save(c, a)
    bot.say(c, 'sp_done', id=ticket['id'])


def send_support_summary(c, sp, with_hint=False):
    L = bot.lang(c)
    body = t(L, 'sp_confirm', project=sp.get('project_title') or t(L, 'not_given'), desc=sp['desc'][:700],
             priority=t(L, 'b_urgent' if sp.get('priority') == 'urgent' else 'b_normal'))
    if sp.get('attachments'):
        body += f"\n📎 {sp['attachments']}"
    if with_hint:
        body += '\n\n' + t(L, 'ai_check_summary')
    bot.buttons(c, body, [('ai:sp:submit', 'b_submit'), ('ai:sp:edit', 'b_edit')])


# ---- review, portfolio, menu, team, unanswered ----------------------------------
def tool_save_review(c, a, turn, args):
    try:
        rating = int(args.get('rating'))
    except (TypeError, ValueError):
        rating = 0
    text = str(args.get('review_text') or '').strip()
    if not 1 <= rating <= 5:
        return {'error': 'Ask for a star rating from 1 to 5.'}
    if len(text) < 3:
        return {'error': 'Ask them to write a few words about their experience.'}
    data = {'rating': rating, 'text': text[:2000], 'name': bot.valid_name(args.get('display_name')) or '',
            'business': str(args.get('business_name') or '')[:160], 'location': str(args.get('location') or '')[:120]}
    publish = bool(args.get('publish_on_website'))
    name = bot.save_review(c, data, publish)
    turn.acted = True
    key = 'rv_done_public' if publish else 'rv_done_private'
    turn.fallback.append(t(bot.lang(c), key, name=name.split()[0]))
    out = {'ok': True, 'published_after_owner_approval': publish,
           'note': 'Thank them warmly.' + (' Say it will appear on our website after a quick check.' if publish else '')}
    if publish and rating >= 4 and config.GOOGLE_REVIEW_URL:
        out['google_review_link'] = config.GOOGLE_REVIEW_URL
        out['note'] += ' Politely ask if they could also post it on Google using the link.'
    return out


def tool_send_project_photo(c, a, turn, args):
    try:
        project_id = int(args.get('project_id'))
    except (TypeError, ValueError):
        return {'error': 'Use a project id from OUR PORTFOLIO.'}
    if not db.get_project(project_id):
        return {'error': 'Use a project id from OUR PORTFOLIO.'}
    if sum(1 for k, _ in turn.after if k == 'project') >= 3:
        return {'error': 'Send at most 3 projects at a time.'}
    turn.after.append(('project', project_id))
    return {'ok': True, 'note': 'The photo and description are sent right after your reply. Keep your reply short.'}


def tool_show_menu(c, a, turn, args):
    turn.after.append(('menu', None))
    return {'ok': True, 'note': 'The menu is sent right after your reply. Reply with one short line, or nothing.'}


def tool_talk_to_team(c, a, turn, args):
    result = bot.talk_to_team(c, ' '.join(str(args.get('reason') or '').split())[:200], reply=False)
    turn.acted = True
    if result == 'again':
        turn.fallback.append(t(bot.lang(c), 'human_again'))
        return {'ok': True, 'note': 'They already asked recently; our team has been told. Reassure them that we will '
                                    'contact them within 24 hours, and keep helping.'}
    turn.fallback.append(t(bot.lang(c), 'human'))
    return {'ok': True, 'note': 'Our team has been told. Say we will contact them within 24 hours, and you can keep '
                                'helping meanwhile.'}


def tool_note_unanswered(c, a, turn, args):
    db.add_unanswered(c['wa_id'], args.get('question') or '')
    return {'ok': True}


TOOL_FUNCS = {
    'save_enquiry_details': tool_save_enquiry,
    'show_enquiry_summary': tool_show_enquiry_summary,
    'submit_enquiry': tool_submit_enquiry,
    'cancel_draft': tool_cancel_draft,
    'get_call_slots': tool_get_call_slots,
    'book_call': tool_book_call,
    'cancel_call': tool_cancel_call,
    'prepare_support_request': tool_prepare_support,
    'submit_support_request': tool_submit_support,
    'save_review': tool_save_review,
    'send_project_photo': tool_send_project_photo,
    'show_menu': tool_show_menu,
    'talk_to_team': tool_talk_to_team,
    'note_unanswered': tool_note_unanswered,
}


# ===========================================================================
# Replies to template buttons (old-lead follow-up, renewal reminder)
# ===========================================================================
def followup_reply(c, action):
    parts = action.split(':')
    e = bot._own_enquiry(c, parts[2]) if len(parts) == 3 else None
    choice = parts[1] if len(parts) > 1 else ''
    if e:
        db.followup_reply(e['id'], {'call': 'call', 'details': 'details', 'no': 'not_now'}.get(choice, choice)[:20])
    name = bot.display_name(c) or (e['name'] if e else 'A customer')
    services = ', '.join(e['services'] or []) if e else ''
    if choice == 'call':
        if e:
            db.queue_alert('lead_reply', f'{name} asked for a call after the follow-up (enquiry #{e["id"]})',
                           wa_id=c['wa_id'], customer_name=name, customer_phone=bot.phone_display(c['wa_id']), ref_id=e['id'])
        return converse(c, note='The customer replied to our follow-up and wants a call. Check get_call_slots and '
                                'suggest a few free times.')
    if choice == 'details':
        if e:
            db.queue_alert('lead_reply', f'{name} asked for more details after the follow-up (enquiry #{e["id"]})',
                           wa_id=c['wa_id'], customer_name=name, customer_phone=bot.phone_display(c['wa_id']), ref_id=e['id'])
            db.update_contact(c['wa_id'], needs_reply=True)
        return converse(c, note='The customer replied to our follow-up and wants more details' +
                                (f' about {services}' if services else '') + '. Explain how we can help (no prices) '
                                'and ask a question about their needs. Our team has also been told.')
    return bot.say(c, 'fu_not_now')


def renewal_reply(c, action):
    parts = action.split(':')
    r = db.get_renewal(int(parts[2])) if len(parts) == 3 and parts[2].isdigit() else None
    if not r or c['wa_id'] not in (r['wa_ids'] or []):
        return converse(c, note='The customer tapped an old button. Ask how you can help.')   # not this client's renewal
    name = bot.display_name(c) or r['client_name']
    what = f"{r['item']} {r['label']}".strip()
    when = f"{r['expiry_date'].day} {bot.MONTHS[r['expiry_date'].month - 1]} {r['expiry_date'].year}"
    db.queue_alert('renewal_reply', f'{name} wants to renew {what} (expires {when})', wa_id=c['wa_id'],
                   customer_name=name, customer_phone=bot.phone_display(c['wa_id']), ref_id=r['id'])
    db.update_contact(c['wa_id'], needs_reply=True)
    if parts[1] == 'call':
        return converse(c, note=f'The customer wants a call about renewing their {what}. Check get_call_slots and '
                                'suggest a few free times. Our team has been told.')
    return bot.say(c, 'rn_thanks')
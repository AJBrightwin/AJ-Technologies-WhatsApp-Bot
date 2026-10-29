"""
AJ's AI assistant on WhatsApp (upgrade v3).

Only messages from ADMIN_WA_NUMBER come here. AJ is the owner: he can ask about his business in his
own words and the AI answers with real data through the tools below, or do things for him
(change a lead's status, update a support request or project and tell the client, reply to a
customer, add a bot FAQ, track his own subscriptions ...). He can also ask general questions.
"""
import logging
from datetime import date

import admin
import ai
import bot
import config
import db
import subscriptions as subs

log = logging.getLogger('bot.admin_ai')

SYSTEM = """
You are AJ Technologies Assistant, the personal business assistant of the owner of AJ Technologies,
{owner} (Founder & CEO; call him AJ). You are chatting with HIM on WhatsApp, from his own number. He is your boss.

HOW TO HELP
- He can ask anything. Business questions: ALWAYS use the tools to get real data (never invent numbers, names or
  dates). General questions (technology, coding, ideas, writing, translations, anything): answer them helpfully.
- He may refer to "this lead", "him", "that request", "the last alert": find it in the recent chat (alerts and
  messages above contain #numbers, names and phone numbers), or look it up with the tools.
- Reply in the language he writes in. WhatsApp style: short and clear, *bold* for key facts, short lists are fine,
  no tables, no headings. Few emojis.
- If he just greets you ("hi", "good morning"), greet him back and give today's overview (get_today_overview).
- Times and dates are India time. Today is {today}.

ACTIONS
- Changing a status (lead, call, support request without telling the client, subscription renewed, FAQ) can be done
  straight away when he asks.
- Anything that sends a WhatsApp message to a customer (send_message_to_customer, update_support_request or
  update_client_project with notify_client=true): first show him exactly what will be sent and to whom, and ask
  "Shall I send it?" - unless his message already gives the exact words and clearly says to send it.
- Never send a customer anything he did not ask for. Never share one client's details with another client.
- After an action, confirm in one or two lines what was done (and if the client was told).

HIS OWN SUBSCRIPTIONS (Render, Supabase, Meta, OpenAI, domain, SSL ...)
- Use list_my_subscriptions / save_my_subscription / mark_subscription_renewed / check_subscriptions_now.
- Every day at {subs_at} India time he gets a reminder for anything renewing within {subs_days} days, until it is
  marked renewed. Domains and SSL are checked automatically (any domain can be added: check_kind "domain" with the
  domain name as check_target). Meta token and OpenAI credits are checked automatically too.

LINKS: dashboard {dashboard}, website {site}.
"""


def _fn(name, description, properties=None, required=None):
    params = {'type': 'object', 'properties': properties or {}}
    if required:
        params['required'] = required
    return {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': params}}


ENQ_STATUSES = ['new', 'contacted', 'quoted', 'won', 'closed']
TICKET_STATUSES = ['open', 'in_progress', 'waiting', 'resolved', 'closed']
STAGES = ['requirement', 'design', 'development', 'testing', 'launch', 'live', 'support', 'on_hold']

TOOLS = [
    _fn('get_today_overview', 'Today at a glance: new enquiries, chats waiting, calls today, open support requests, '
        'renewals, unanswered questions.'),
    _fn('weekly_report', 'The report for the last 7 days (enquiries, sources, wins, chats, calls, support, reviews).'),
    _fn('list_enquiries', 'Enquiries (leads) from the website and the bot.', {
        'status': {'type': 'string', 'enum': ENQ_STATUSES + ['any']},
        'days': {'type': 'integer', 'description': 'How many days back (default 30).'},
        'search': {'type': 'string', 'description': 'Name, business, phone, email or words in the message.'}}),
    _fn('get_enquiry', 'Full details of one enquiry.', {'enquiry_id': {'type': 'integer'}}, ['enquiry_id']),
    _fn('set_enquiry_status', "Change an enquiry's status.", {
        'enquiry_id': {'type': 'integer'}, 'status': {'type': 'string', 'enum': ENQ_STATUSES}}, ['enquiry_id', 'status']),
    _fn('list_calls', 'Calls booked through the bot.', {
        'date_from': {'type': 'string', 'description': 'YYYY-MM-DD (default today)'},
        'date_to': {'type': 'string', 'description': 'YYYY-MM-DD (default = date_from)'}}),
    _fn('set_call_status', 'Mark a booked call as done, missed or cancelled.', {
        'call_id': {'type': 'integer'}, 'status': {'type': 'string', 'enum': ['done', 'missed', 'cancelled', 'booked']}},
        ['call_id', 'status']),
    _fn('list_support_requests', 'Open support requests (tickets) from clients.'),
    _fn('get_support_request', 'Details of one support request.', {'request_id': {'type': 'integer'}}, ['request_id']),
    _fn('update_support_request', 'Change the status of a support request, optionally telling the client on WhatsApp.', {
        'request_id': {'type': 'integer'}, 'status': {'type': 'string', 'enum': TICKET_STATUSES},
        'note_for_client': {'type': 'string', 'description': 'Short note the client sees, e.g. "Fixed the menu".'},
        'notify_client': {'type': 'boolean'}}, ['request_id', 'status', 'notify_client']),
    _fn('list_client_projects', 'Client projects (for the clients\' project status).',
        {'search': {'type': 'string', 'description': 'Client, business or project name.'}}),
    _fn('update_client_project', 'Update a client project (stage, progress, note for the client), optionally telling '
        'the client on WhatsApp.', {
            'project_id': {'type': 'integer'}, 'stage': {'type': 'string', 'enum': STAGES},
            'progress': {'type': 'integer', 'minimum': 0, 'maximum': 100},
            'note_for_client': {'type': 'string'}, 'live_url': {'type': 'string'},
            'notify_client': {'type': 'boolean'}}, ['project_id', 'notify_client']),
    _fn('list_client_renewals', "Clients' domain / hosting / SSL / AMC renewals coming up.",
        {'days': {'type': 'integer', 'description': 'Default 30'}}),
    _fn('list_waiting_chats', 'Customers waiting for a reply from the team.'),
    _fn('find_customer', 'Find a customer by name, business or phone number (WhatsApp contacts and enquiries).',
        {'query': {'type': 'string'}}, ['query']),
    _fn('get_customer_chat', 'The recent WhatsApp chat with one customer.', {
        'phone': {'type': 'string'}, 'limit': {'type': 'integer', 'description': 'Messages (default 15)'}}, ['phone']),
    _fn('send_message_to_customer', 'Send a WhatsApp message to a customer as the team (only inside 24 hours of their '
        'last message). Only after AJ confirmed the exact text.', {
            'phone': {'type': 'string'}, 'message': {'type': 'string'}}, ['phone', 'message']),
    _fn('list_unanswered_questions', "Questions customers asked that the bot couldn't answer."),
    _fn('answer_unanswered_question', 'Save AJ\'s answer as a bot FAQ (the bot uses it within a minute).', {
        'question_id': {'type': 'integer'}, 'answer': {'type': 'string'},
        'question': {'type': 'string', 'description': 'Optional cleaner wording of the question.'}},
        ['question_id', 'answer']),
    _fn('ignore_unanswered_question', 'Ignore an unanswered question.', {'question_id': {'type': 'integer'}}, ['question_id']),
    _fn('list_bot_knowledge', 'FAQs, facts and offers the bot uses.'),
    _fn('add_bot_knowledge', 'Teach the bot a FAQ, a fact or a current offer.', {
        'kind': {'type': 'string', 'enum': ['faq', 'info', 'offer']},
        'question_or_title': {'type': 'string'}, 'answer': {'type': 'string'}}, ['kind', 'answer']),
    _fn('set_bot_knowledge_active', 'Switch a bot FAQ / fact / offer on or off.', {
        'knowledge_id': {'type': 'integer'}, 'active': {'type': 'boolean'}}, ['knowledge_id', 'active']),
    _fn('list_my_subscriptions', "AJ's own subscriptions and their renewal dates."),
    _fn('save_my_subscription', 'Add or change one of AJ\'s own subscriptions (leave subscription_id empty to add).', {
        'subscription_id': {'type': 'integer'}, 'name': {'type': 'string'},
        'renews_on': {'type': 'string', 'description': 'YYYY-MM-DD next renewal / expiry date'},
        'cycle': {'type': 'string', 'enum': ['monthly', 'yearly', 'none']},
        'auto_pay': {'type': 'boolean', 'description': 'True if the card is charged automatically.'},
        'check_kind': {'type': 'string', 'enum': ['none', 'domain', 'ssl', 'meta_token', 'openai']},
        'check_target': {'type': 'string', 'description': 'Domain name(s) for domain / ssl checks, comma separated.'},
        'amount': {'type': 'string'}, 'notes': {'type': 'string'},
        'active': {'type': 'boolean', 'description': 'False to stop tracking it.'}}),
    _fn('mark_subscription_renewed', 'AJ renewed / paid a subscription: move it to the next date and stop today\'s '
        'reminders.', {'subscription_id': {'type': 'integer'},
                       'next_date': {'type': 'string', 'description': 'YYYY-MM-DD, only if AJ said the new date.'}},
        ['subscription_id']),
    _fn('check_subscriptions_now', 'Run the automatic checks now (domain, SSL, Meta token, OpenAI) and list everything.'),
]


def _date(value, default=None):
    try:
        return date.fromisoformat(str(value)[:10]) if value else default
    except ValueError:
        return default


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ist(dt):
    return f'{dt.astimezone(config.TZ):%d %b %Y, %I:%M %p}' if dt else None


def run_tool(name, a):
    today = bot.now_ist().date()
    if name == 'get_today_overview':
        import jobs
        return {'text': jobs.daily_summary_text()[0]}
    if name == 'weekly_report':
        import jobs
        return {'text': jobs.weekly_report_text()}
    if name == 'list_enquiries':
        status = '' if a.get('status') in (None, '', 'any') else a['status']
        items = db.search_enquiries(status, _int(a.get('days')) or 30, (a.get('search') or '').strip(), 15)
        return {'count': len(items), 'enquiries': [
            {'id': e['id'], 'name': e['name'], 'business': e['business_name'] or None, 'phone': e['phone'],
             'services': e['services'], 'status': e['status'], 'source': e['source'], 'received': _ist(e['created_at'])}
            for e in items]}
    if name == 'get_enquiry':
        return {'text': admin.lead_text(_int(a.get('enquiry_id')) or 0)}
    if name == 'set_enquiry_status':
        if a.get('status') not in ENQ_STATUSES:
            return {'error': 'Unknown status'}
        return {'text': admin.set_status(_int(a.get('enquiry_id')) or 0, a['status'])}
    if name == 'list_calls':
        d1 = _date(a.get('date_from'), today)
        d2 = _date(a.get('date_to'), d1)
        items = db.calls_between(d1, d2, '')
        return {'from': f'{d1:%a %d %b}', 'to': f'{d2:%a %d %b}', 'calls': [
            {'id': b['id'], 'date': f"{b['call_date']:%a %d %b}", 'time': bot.time_label(b['call_time'].strftime('%H:%M')),
             'name': b['name'], 'phone': b['phone'], 'topic': b['topic'] or None, 'status': b['status']} for b in items]}
    if name == 'set_call_status':
        booking = db.get_booking(_int(a.get('call_id')) or 0)
        if not booking:
            return {'error': 'No such call'}
        if a.get('status') == 'cancelled':
            db.cancel_alerts('call_reminder', booking['id'])
            db.cancel_alerts('cust_call_reminder', booking['id'])
        db.set_booking_status(booking['id'], a.get('status'))
        return {'ok': True, 'note': 'The customer was not messaged.'}
    if name == 'list_support_requests':
        return {'text': admin.tickets_text()}
    if name == 'get_support_request':
        return {'text': admin.ticket_text(_int(a.get('request_id')) or 0)}
    if name == 'update_support_request':
        if a.get('status') not in TICKET_STATUSES:
            return {'error': 'Unknown status'}
        return {'text': admin.update_ticket(_int(a.get('request_id')) or 0, a['status'],
                                            str(a.get('note_for_client') or '').strip()[:500],
                                            notify=bool(a.get('notify_client')))}
    if name == 'list_client_projects':
        items = db.search_client_projects((a.get('search') or '').strip())
        return {'projects': [{'id': p['id'], 'client': p['client_name'], 'business': p['business_name'] or None,
                              'title': p['title'], 'stage': p['stage'], 'progress': p['progress'],
                              'note_for_client': p['client_note'] or None, 'live_url': p['live_url'] or None,
                              'whatsapp_numbers': [bot.phone_display(w) for w in p['wa_ids'] or []]} for p in items]}
    if name == 'update_client_project':
        p = db.get_client_project(_int(a.get('project_id')) or 0)
        if not p:
            return {'error': 'No such project'}
        stage = a.get('stage') if a.get('stage') in STAGES else None
        progress = _int(a.get('progress'))
        if progress is not None:
            progress = max(0, min(100, progress))
        if stage == 'live' and progress is None:
            progress = 100
        note = a.get('note_for_client')
        p = db.update_client_project(p['id'], stage, progress, note.strip()[:2000] if isinstance(note, str) else None,
                                     a.get('live_url').strip()[:300] if isinstance(a.get('live_url'), str) else None)
        out = {'ok': True, 'project': p['title'], 'stage': p['stage'], 'progress': p['progress']}
        if a.get('notify_client'):
            errors = bot.notify_project(p, (note or '').strip())
            out['client_told'] = not errors
            if errors:
                out['errors'] = errors
        else:
            out['client_told'] = False
        return out
    if name == 'list_client_renewals':
        return {'text': admin.renewals_text(_int(a.get('days')) or 30)}
    if name == 'list_waiting_chats':
        return {'chats': [{'name': w['name'] or w['profile_name'], 'phone': bot.phone_display(w['wa_id']),
                           'last_message': w['last_message_preview'], 'when': _ist(w['last_inbound_at'])}
                          for w in db.waiting_chats()]}
    if name == 'find_customer':
        q = (a.get('query') or '').strip()
        if len(q) < 2:
            return {'error': 'Give at least 2 letters or digits.'}
        contacts = db.find_contacts(q)
        enquiries = db.search_enquiries('', 3650, q, 5)
        return {'whatsapp_contacts': [{'name': x['name'] or x['profile_name'], 'business': x['business_name'] or None,
                                       'phone': bot.phone_display(x['wa_id']), 'last_message': _ist(x['last_inbound_at']),
                                       'waiting_for_reply': x['needs_reply'], 'sent_stop': x['opted_out']}
                                      for x in contacts],
                'enquiries': [{'id': e['id'], 'name': e['name'], 'phone': e['phone'], 'status': e['status'],
                               'services': e['services'], 'received': _ist(e['created_at'])} for e in enquiries]}
    if name == 'get_customer_chat':
        wa_id = bot.normalise_phone(a.get('phone') or '')
        if not wa_id:
            return {'error': 'That phone number does not look right.'}
        contact = db.get_contact(wa_id)
        if not contact:
            return {'error': 'This number has never chatted with the bot.'}
        msgs = db.recent_messages(wa_id, min(_int(a.get('limit')) or 15, 40))
        return {'customer': bot.display_name(contact) or bot.phone_display(wa_id),
                'can_message_now': db.window_open(contact),
                'messages': [{'from': 'customer' if m['direction'] == 'in' else m['sender'], 'when': _ist(m['created_at']),
                              'text': m['body'][:500]} for m in msgs]}
    if name == 'send_message_to_customer':
        text = str(a.get('message') or '').strip()
        if not text:
            return {'error': 'No message given'}
        return {'text': admin.reply_to_customer(a.get('phone') or '', text)}
    if name == 'list_unanswered_questions':
        return {'questions': [{'id': q['id'], 'question': q['question'], 'asked': _ist(q['created_at'])}
                              for q in db.unanswered_list(15)]}
    if name == 'answer_unanswered_question':
        answer = str(a.get('answer') or '').strip()
        if not answer:
            return {'error': 'No answer given'}
        kid = db.answer_unanswered(_int(a.get('question_id')) or 0, answer, str(a.get('question') or '').strip())
        return {'ok': bool(kid), 'note': 'Saved as a bot FAQ; the bot uses it within a minute.' if kid else 'No such question'}
    if name == 'ignore_unanswered_question':
        return {'ok': db.ignore_unanswered(_int(a.get('question_id')) or 0)}
    if name == 'list_bot_knowledge':
        return {'items': [{'id': k['id'], 'kind': k['kind'], 'question': k['question'], 'answer': k['answer'][:300],
                           'active': k['is_active']} for k in db.knowledge_list()]}
    if name == 'add_bot_knowledge':
        answer = str(a.get('answer') or '').strip()
        if not answer:
            return {'error': 'No answer given'}
        kind = a.get('kind') if a.get('kind') in ('faq', 'info', 'offer') else 'faq'
        kid = db.add_knowledge(kind, str(a.get('question_or_title') or '').strip(), answer)
        return {'ok': True, 'id': kid, 'note': 'The bot uses it within a minute.'}
    if name == 'set_bot_knowledge_active':
        k = db.set_knowledge(_int(a.get('knowledge_id')) or 0, active=bool(a.get('active')))
        return {'ok': bool(k)}
    if name == 'list_my_subscriptions':
        return {'subscriptions': [subs.describe(s) for s in db.subscriptions(active_only=False)],
                'reminder': f'Every day at {config.SUBS_ALERT_AT} India time, from {config.SUBS_ALERT_DAYS} days before.'}
    if name == 'save_my_subscription':
        fields = {}
        if a.get('name'):
            fields['name'] = str(a['name']).strip()[:120]
        if a.get('renews_on'):
            d = _date(a['renews_on'])
            if not d:
                return {'error': 'renews_on must be YYYY-MM-DD'}
            fields['renews_on'] = d
        for key, col in (('cycle', 'cycle'), ('check_kind', 'check_kind')):
            if a.get(key):
                fields[col] = a[key]
        if fields.get('cycle') not in (None, 'monthly', 'yearly', 'none') or \
                fields.get('check_kind') not in (None, 'none', 'domain', 'ssl', 'meta_token', 'openai'):
            return {'error': 'Unknown cycle or check_kind'}
        for key, col in (('auto_pay', 'auto_renew'), ('active', 'is_active')):
            if isinstance(a.get(key), bool):
                fields[col] = a[key]
        for key, col, size in (('check_target', 'check_target', 300), ('amount', 'amount_text', 60), ('notes', 'notes', 2000)):
            if isinstance(a.get(key), str):
                fields[col] = a[key].strip()[:size]
        sub_id = _int(a.get('subscription_id'))
        if sub_id and not db.get_subscription(sub_id):
            return {'error': 'No such subscription'}
        if not sub_id and not fields.get('name'):
            return {'error': 'Give a name for the new subscription'}
        s = db.save_subscription(sub_id, **fields)
        if s['check_kind'] != 'none' and (not sub_id or 'check_target' in fields or 'check_kind' in fields):
            s = subs.run_check(s)
        return {'ok': True, 'subscription': subs.describe(s)}
    if name == 'mark_subscription_renewed':
        s = db.get_subscription(_int(a.get('subscription_id')) or 0)
        if not s:
            return {'error': 'No such subscription; call list_my_subscriptions to find the id.'}
        nxt = _date(a.get('next_date')) if a.get('next_date') else None
        s, message = subs.mark_renewed(s, nxt)
        return {'ok': True, 'subscription': subs.describe(s), 'note': message}
    if name == 'check_subscriptions_now':
        items = subs.check_all()
        return {'subscriptions': [subs.describe(s) for s in items]}
    return {'error': f'Unknown tool {name}'}


def answer(c, text, image=None):
    history = ai.history_messages(db.recent_messages(c['wa_id'], 24))
    if not history or history[-1]['role'] != 'user':
        history.append({'role': 'user', 'content': text or '(photo)'})
    now = bot.now_ist()
    system = SYSTEM.format(owner=config.OWNER_NAME, today=f'{now:%A %d %B %Y, %I:%M %p}', subs_at=config.SUBS_ALERT_AT,
                           subs_days=config.SUBS_ALERT_DAYS, dashboard=config.DASHBOARD_URL, site=config.SITE_URL)
    return ai.run_agent(system, history, TOOLS, run_tool, image=image, max_rounds=6, max_tokens=900, temperature=0.3)
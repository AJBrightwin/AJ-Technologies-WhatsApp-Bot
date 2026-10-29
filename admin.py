"""
Commands AJ can send to the bot from his own WhatsApp number (ADMIN_WA_NUMBER).

Nobody else can use these: messages from any other number go to the normal customer bot.
"""
import re
from datetime import timedelta

import bot
import config
import db
import whatsapp as wa

HELP = """🤖 *Commands you can send me*

📊 *summary* · today at a glance
📥 *leads* · new enquiries not contacted yet
🔎 *lead 12* · details of enquiry #12
✏️ *12 contacted* · *12 quoted* · *12 won* · *12 closed* · change an enquiry's status
📅 *calls* · *calls tomorrow* · booked calls
🛠️ *tickets* · open support requests
🔎 *ticket 5* · details of request #5
✅ *ticket 5 progress* · *ticket 5 resolved Fixed the menu* · update a request (the client is told)
🔁 *renewals* · renewals in the next 30 days
❓ *questions* · questions the bot couldn't answer
📈 *report* · this week's report now
💬 *reply 919876543210 Your message* · reply to a customer (within 24 hours of their last message)"""

ENQ_STATUSES = ('new', 'contacted', 'quoted', 'won', 'closed')
TICKET_WORDS = {'open': 'open', 'received': 'open', 'progress': 'in_progress', 'in progress': 'in_progress',
                'working': 'in_progress', 'waiting': 'waiting', 'resolved': 'resolved', 'done': 'resolved',
                'fixed': 'resolved', 'closed': 'closed', 'close': 'closed'}
SOURCE = {'home': '🌐 home page', 'contact': '🌐 contact page', 'bot': '🤖 bot'}


def ago(dt):
    secs = (db.now() - dt).total_seconds()
    if secs < 3600:
        return f'{max(1, int(secs // 60))} min ago'
    if secs < 86400:
        return f'{int(secs // 3600)} hr ago'
    return f'{int(secs // 86400)} d ago'


def ist(dt):
    return dt.astimezone(config.TZ)


def reply(c, text):
    wa.send_text(c['wa_id'], text, sender='bot')


def handle(c, text):
    raw = (text or '').strip()
    low = ' '.join(raw.lower().split()).rstrip('.!?')
    try:
        out = route(raw, low)
    except Exception:
        bot.log.exception('Admin command failed: %s', raw)
        out = '⚠️ Something went wrong with that command. Please try again, or use the dashboard.'
    reply(c, out)


def route(raw, low):
    if low in ('', 'hi', 'hello', 'hey', 'summary', 'today', 'status', 'vanakkam', 'good morning'):
        return bot.admin_summary_text()
    if low in ('help', 'commands', 'menu', '?'):
        return HELP
    if low in ('leads', 'lead', 'new leads', 'enquiries', 'new'):
        return leads_text()
    m = re.fullmatch(r'(?:lead|enquiry|enq)\s*#?(\d+)', low)
    if m:
        return lead_text(int(m.group(1)))
    m = (re.fullmatch(r'(?:mark\s+)?#?(\d+)\s+(?:as\s+)?(new|contacted|quoted|won|closed)', low)
         or re.fullmatch(r'(?:mark\s+)?(new|contacted|quoted|won|closed)\s+#?(\d+)', low))
    if m:
        a, b = m.groups()
        number, status = (a, b) if a.isdigit() else (b, a)
        return set_status(int(number), status)
    m = re.fullmatch(r'calls?(?:\s+(today|tomorrow))?', low)
    if m:
        day = bot.now_ist().date() + timedelta(days=1 if m.group(1) == 'tomorrow' else 0)
        return calls_text(day)
    if low in ('tickets', 'ticket', 'requests', 'support'):
        return tickets_text()
    m = re.fullmatch(r'ticket\s*#?(\d+)', low)
    if m:
        return ticket_text(int(m.group(1)))
    m = re.match(r'ticket\s*#?(\d+)\s+(in progress|progress|working|open|received|waiting|resolved|done|fixed|closed|close)\b\s*(.*)',
                 raw, re.I | re.S)
    if m:
        return update_ticket(int(m.group(1)), TICKET_WORDS[m.group(2).lower()], m.group(3).strip())
    if low in ('renewals', 'renewal', 'expiry', 'expiring'):
        return renewals_text()
    if low in ('questions', 'unanswered', 'faq', 'faqs'):
        return questions_text()
    if low in ('report', 'weekly report', 'week'):
        import jobs
        return jobs.weekly_report_text()
    m = re.match(r'reply\s+(\+?[\d\s-]{10,18})\s+(.+)', raw, re.I | re.S)
    if m:
        return reply_to_customer(m.group(1), m.group(2).strip())
    return "Sorry, I didn't understand that command.\n\n" + HELP


def leads_text():
    items = db.new_enquiries(10)
    if not items:
        return '📥 No new enquiries waiting. All caught up! 🎉'
    lines = [f'📥 *New enquiries not contacted yet* ({len(items)})', '']
    for e in items:
        lines.append(f"*#{e['id']}* · {e['name']} · {', '.join(e['services'] or []) or 'service not given'}")
        lines.append(f"   {e['phone']} · {ago(e['created_at'])} · {SOURCE.get(e['source'], e['source'])}")
    lines.append('\nType *lead 12* for details or *12 contacted* to update.')
    return '\n'.join(lines)


def lead_text(enquiry_id):
    e = db.get_enquiry(enquiry_id)
    if not e:
        return f'No enquiry #{enquiry_id}.'
    timeline = {'asap': 'As soon as possible', '1m': 'Within a month', '3m': '1-3 months', 'explore': 'Just exploring'}
    return '\n'.join([
        f"🔎 *Enquiry #{e['id']}* · {e['status'].upper()}",
        f"👤 {e['name']}" + (f" · {e['business_name']}" if e['business_name'] else ''),
        f"📱 {e['phone']}" + (f" · ✉️ {e['email']}" if e['email'] else ''),
        f"🛠️ {', '.join(e['services'] or []) or '-'}",
        f"⏱️ {timeline.get(e['timeline'], '-')} · prefers {e['contact_method'] or '-'}",
        f"📝 {e['message'] or '-'}",
        f"🕒 {ist(e['created_at']):%d %b %Y, %I:%M %p} · {SOURCE.get(e['source'], e['source'])}",
        f"💬 https://wa.me/{config.digits(e['phone']) if len(config.digits(e['phone'])) > 10 else '91' + config.digits(e['phone'])}",
    ])


def set_status(enquiry_id, status):
    e = db.set_enquiry_status(enquiry_id, status)
    if not e:
        return f'No enquiry #{enquiry_id}.'
    return f"✅ Enquiry #{e['id']} ({e['name']}) is now *{status}*."


def calls_text(day):
    items = db.calls_on(day)
    label = 'today' if day == bot.now_ist().date() else f'{day:%a %d %b}'
    if not items:
        return f'📅 No calls booked {label}.'
    lines = [f'📅 *Calls {label}* ({len(items)})', '']
    for b in items:
        lines.append(f"*{bot.time_label(b['call_time'].strftime('%H:%M'))}* · {b['name'] or 'Customer'} · {b['phone']}")
        if b['topic']:
            lines.append(f"   {b['topic'][:120]}")
    return '\n'.join(lines)


TICKET_LABEL = {'open': 'Received', 'in_progress': 'In progress', 'waiting': 'Waiting for client',
                'resolved': 'Resolved', 'closed': 'Closed'}


def tickets_text():
    items = db.open_tickets(15)
    if not items:
        return '🛠️ No open support requests. 🎉'
    lines = [f'🛠️ *Open support requests* ({len(items)})', '']
    for tk in items:
        lines.append(f"{'🔴 ' if tk['priority'] == 'urgent' else ''}*#{tk['id']}* · {tk['client_name'] or 'Customer'}"
                     f" · {TICKET_LABEL[tk['status']]} · {ago(tk['created_at'])}")
        lines.append(f"   {' '.join(tk['description'].split())[:100]}")
    lines.append('\nType *ticket 5 resolved Your note* to update and tell the client.')
    return '\n'.join(lines)


def ticket_text(ticket_id):
    tk = db.get_ticket(ticket_id)
    if not tk:
        return f'No support request #{ticket_id}.'
    return '\n'.join([
        f"🛠️ *Support request #{tk['id']}* · {TICKET_LABEL[tk['status']]}{' · 🔴 URGENT' if tk['priority'] == 'urgent' else ''}",
        f"👤 {tk['client_name'] or 'Customer'} · 📱 {bot.phone_display(tk['wa_id'])}",
        f"📁 {tk['project_title'] or 'No project'}",
        f"📝 {tk['description']}",
        f"🕒 {ist(tk['created_at']):%d %b %Y, %I:%M %p}" + (f" · 📎 {tk['attachments']} file(s)" if tk['attachments'] else ''),
    ] + ([f"💬 Last note to client: {tk['client_update']}"] if tk['client_update'] else []))


def update_ticket(ticket_id, status, note):
    tk = db.get_ticket(ticket_id)
    if not tk:
        return f'No support request #{ticket_id}.'
    tk = db.set_ticket_status(ticket_id, status, note)
    _, error = bot.notify_ticket(tk, note)
    told = f'⚠️ Could not message the client: {error}' if error else '📨 The client has been told.'
    return f"✅ Request #{ticket_id} is now *{TICKET_LABEL[status]}*.\n{told}"


def renewals_text():
    items = db.upcoming_renewals(30)
    if not items:
        return '🔁 No renewals in the next 30 days.'
    today = bot.now_ist().date()
    lines = [f'🔁 *Renewals in the next 30 days* ({len(items)})', '']
    for r in items:
        days = (r['expiry_date'] - today).days
        when = 'EXPIRED' if days < 0 else 'today' if days == 0 else f'in {days} days'
        lines.append(f"*{r['expiry_date']:%d %b}* ({when}) · {r['item']} {r['label']} · {r['client_name']}"
                     + (f" · {r['amount_text']}" if r['amount_text'] else ''))
    return '\n'.join(lines)


def questions_text():
    items = db.pending_unanswered(10)
    if not items:
        return '❓ No unanswered questions. 🎉'
    lines = [f"❓ *Questions the bot couldn't answer* ({len(items)})", '']
    for q in items:
        lines.append(f"• {q['question'][:150]}  _({ago(q['created_at'])})_")
    lines.append(f'\nAnswer them in Dashboard > Bot knowledge, and the bot will know next time:\n{config.DASHBOARD_URL}')
    return '\n'.join(lines)


def reply_to_customer(number, message):
    wa_id = bot.normalise_phone(number)
    if not wa_id:
        return 'That number does not look right. Use the full number, e.g. *reply 919876543210 Hello*.'
    if wa_id == config.ADMIN_WA_NUMBER:
        return 'That is your own number.'
    contact = db.get_contact(wa_id)
    if not contact:
        return f'{bot.phone_display(wa_id)} has never messaged the bot, so WhatsApp only allows a template. Use the dashboard.'
    if not db.window_open(contact):
        return (f"More than 24 hours since {bot.display_name(contact) or bot.phone_display(wa_id)} last messaged, "
                'so WhatsApp only allows an approved template. Use the dashboard > WhatsApp > Send template.')
    _, error = wa.send_text(wa_id, message, sender='admin')
    if error:
        return f'⚠️ Not sent: {error}'
    db.update_contact(wa_id, needs_reply=False, unread_count=0)
    return f'✅ Sent to {bot.display_name(contact) or bot.phone_display(wa_id)}.'
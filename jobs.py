"""
Background jobs, run every WORKER_SECONDS (and by /cron/tick):

  * alerts and reminders to AJ (new enquiry, still-new enquiry, call booked, call soon ...)
  * call reminders to customers (only while their 24-hour window is open, so no template is needed)
  * a "continue?" message to customers who stopped halfway (sent before their 24-hour window closes)
  * offer broadcasts queued from the admin dashboard

Everything is claimed row by row in the database, so nothing is sent twice even
if two copies of the bot run for a moment during a deploy.
"""
import json
import logging
import threading
import time
from datetime import timedelta

import bot
import config
import db
import whatsapp as wa
from texts import t

log = logging.getLogger('bot.jobs')
_started = False
_start_lock = threading.Lock()
_tick_lock = threading.Lock()

ADMIN_KINDS = {'new_enquiry', 'enquiry_reminder', 'call_booked', 'call_reminder', 'call_cancelled', 'call_request',
               'human_request', 'new_review', 'private_feedback', 'test', 'new_ticket', 'lead_reply', 'renewal_reply',
               'openai_problem'}
ICONS = {'new_enquiry': '📥', 'enquiry_reminder': '⏰', 'call_booked': '📅', 'call_reminder': '⏰',
         'call_cancelled': '❌', 'call_request': '📞', 'human_request': '🙋', 'new_review': '⭐',
         'private_feedback': '💬', 'test': '✅', 'new_ticket': '🛠️', 'lead_reply': '📣', 'renewal_reply': '🔁',
         'openai_problem': '⚠️', 'admin_file': '📎'}


def admin_contact():
    return db.ensure_contact(config.ADMIN_WA_NUMBER, 'AJ (alerts)')


def send_admin_alert(alert):
    """Free message when AJ's 24-hour window is open, otherwise the approved template."""
    admin = admin_contact()
    if db.window_open(admin):
        lines = [f"{ICONS.get(alert['kind'], '🔔')} *{alert['summary']}*"]
        if alert['customer_name'] or alert['customer_phone']:
            lines.append(f"👤 {alert['customer_name'] or '-'} · 📱 {alert['customer_phone'] or '-'}")
        if alert['detail']:
            lines.append('')
            lines.append(alert['detail'][:2500])
        if alert['customer_phone']:
            lines.append(f"\nChat: https://wa.me/{config.digits(alert['customer_phone'])}")
        lines.append(f'Dashboard: {config.DASHBOARD_URL}')
        lines.append('_Reply here if you want me to do anything about it._')
        return wa.send_text(config.ADMIN_WA_NUMBER, '\n'.join(lines), sender='system')
    params = [alert['summary'], alert['customer_name'] or '-', alert['customer_phone'] or '-']
    preview = (f"{alert['summary']}\nCustomer: {params[1]}\nPhone: {params[2]}")
    return wa.send_template(config.ADMIN_WA_NUMBER, config.ADMIN_TEMPLATE_NAME, config.ADMIN_TEMPLATE_LANG,
                            params, preview=preview, sender='system')


def process_alert(alert):
    kind = alert['kind']
    if kind == 'enquiry_reminder' and db.enquiry_status(alert['ref_id']) != 'new':
        return db.finish_alert(alert['id'], 'skipped', 'Enquiry already handled')
    if kind in ('call_reminder', 'cust_call_reminder'):
        booking = db.get_booking(alert['ref_id']) if alert['ref_id'] else None
        if not booking or booking['status'] != 'booked':
            return db.finish_alert(alert['id'], 'skipped', 'Call no longer booked')
    if kind == 'cust_call_reminder':
        contact = db.get_contact(alert['wa_id'])
        if not contact or not db.window_open(contact):
            return db.finish_alert(alert['id'], 'skipped', '24-hour window closed (no free message allowed)')
        text = t(bot.lang(contact), 'bk_reminder', time=bot.time_label(booking['call_time'].strftime('%H:%M')),
                 phone=bot.phone_display(contact['wa_id']))
        _, error = wa.send_text(contact['wa_id'], text)
    elif kind == 'admin_file':
        _, error = send_admin_file(alert)
    elif kind in ADMIN_KINDS:
        _, error = send_admin_alert(alert)
    else:
        return db.finish_alert(alert['id'], 'skipped', f'Unknown kind {kind}')
    if not error:
        return db.finish_alert(alert['id'], 'sent')
    if alert['attempts'] < 3:
        return db.retry_alert(alert['id'], error, minutes=5 * alert['attempts'])
    db.finish_alert(alert['id'], 'failed', error)


def render_preview(body, params):
    for i, value in enumerate(params, start=1):
        body = body.replace('{{%d}}' % i, str(value))
    return body


def process_broadcasts():
    for r in db.claim_broadcast_recipients(config.BROADCAST_PER_TICK):
        if r['broadcast_status'] == 'cancelled':
            db.finish_recipient(r['id'], 'skipped', 'Broadcast cancelled')
            continue
        if r['opted_out']:
            db.finish_recipient(r['id'], 'skipped', 'Customer sent STOP')
            continue
        if r['wa_id'] == config.ADMIN_WA_NUMBER:
            db.finish_recipient(r['id'], 'skipped', 'Your own number')
            continue
        name = (r['name'] or r['profile_name'] or '').split(' ')[0] or \
            ('நண்பரே' if r['template_language'].startswith('ta') else 'there')
        params = [str(p).replace('{name}', name) for p in (r['params'] or [])]
        if r['opted_out'] is None:
            db.ensure_contact(r['wa_id'])
        wamid, error = wa.send_template(r['wa_id'], r['template_name'], r['template_language'], params,
                                        header_image=r['header_image_url'] or '',
                                        preview=render_preview(r['body_preview'] or f"[Template: {r['template_name']}]", params),
                                        sender='system')
        db.finish_recipient(r['id'], 'failed' if error else 'sent', error, wamid or '')
    db.refresh_broadcasts()


def tick():
    """One round of all jobs. Safe to call often."""
    if not _tick_lock.acquire(blocking=False):
        return {'ok': True, 'skipped': 'already running'}
    done = {'alerts': 0, 'nudges': 0, 'errors': []}
    try:
        try:
            for alert in db.claim_alerts(10):
                try:
                    process_alert(alert)
                    done['alerts'] += 1
                except Exception as e:
                    log.exception('Alert %s failed', alert['id'])
                    db.retry_alert(alert['id'], str(e), minutes=10)
        except Exception as e:
            log.exception('Alerts job failed')
            done['errors'].append(f'alerts: {e}')
        try:
            for contact in db.claim_nudges(config.NUDGE_AFTER_HOURS):
                try:
                    with bot._lock(contact['wa_id']):
                        bot.send_nudge(contact)
                    done['nudges'] += 1
                except Exception:
                    log.exception('Follow-up to %s failed', contact['wa_id'])
        except Exception as e:
            log.exception('Follow-up job failed')
            done['errors'].append(f'follow-ups: {e}')
        try:
            process_broadcasts()
        except Exception as e:
            log.exception('Broadcast job failed')
            done['errors'].append(f'broadcasts: {e}')
        import subscriptions
        for name, job in (('summary', run_daily_reports), ('acks', process_enquiry_acks),
                          ('follow-ups', process_followups), ('renewals', process_renewals),
                          ('subscriptions', subscriptions.run_daily)):
            try:
                job()
            except Exception as e:
                log.exception('%s job failed', name)
                done['errors'].append(f'{name}: {e}')
    finally:
        _tick_lock.release()
    done['ok'] = not done['errors']
    return done


def _loop():
    time.sleep(5)
    while True:
        tick()
        time.sleep(config.WORKER_SECONDS)


def start():
    global _started
    with _start_lock:
        if _started or not config.RUN_WORKER or config.check():
            return
        _started = True
    threading.Thread(target=_loop, name='jobs', daemon=True).start()
    log.info('Background jobs started (every %s seconds)', config.WORKER_SECONDS)



# ===========================================================================
# Upgrade v2 jobs. All times are India time (config.TZ = Asia/Kolkata), so it does not
# matter that the server / database run in another time zone (Render and Supabase store UTC).
# ===========================================================================
def now_ist():
    return bot.now_ist()


def in_hours(window):
    start, end = window
    return start <= now_ist().hour < end


def send_admin_text(text, one_line):
    """A full message when AJ's 24-hour window is open, otherwise one line through the alert template."""
    admin = admin_contact()
    if db.window_open(admin):
        return wa.send_text(config.ADMIN_WA_NUMBER, text, sender='system')
    return wa.send_template(config.ADMIN_WA_NUMBER, config.ADMIN_TEMPLATE_NAME, config.ADMIN_TEMPLATE_LANG,
                            [one_line, 'AJ Technologies', 'Reply here to see more or ask me anything'],
                            preview=text, sender='system')


# ---- O: daily summary at 9 AM India time, P: weekly report on Mondays ----
def daily_summary_text():
    s = db.daily_summary_data()
    today = now_ist()
    lines = [f"☀️ *Good morning AJ!* {today:%A, %d %b %Y}", '']
    lines.append(f"📥 New enquiries yesterday: *{s['leads_yesterday']}*" + (f" ({s['bot_yesterday']} from the bot)" if s['bot_yesterday'] else ''))
    lines.append(f"⏳ Enquiries not contacted yet: *{s['not_contacted']}*")
    lines.append(f"💬 Chats waiting for your reply: *{s['waiting']}*")
    lines.append(f"👥 People who chatted yesterday: *{s['chats_yesterday']}*")
    if s['calls']:
        lines.append(f"📅 Calls today: *{len(s['calls'])}*")
        for b in s['calls'][:6]:
            lines.append(f"   • {bot.time_label(b['call_time'].strftime('%H:%M'))} · {b['name'] or 'Customer'} · {b['phone']}")
    else:
        lines.append('📅 Calls today: *0*')
    lines.append(f"🛠️ Open support requests: *{s['open_tickets']}*" + (f" (🔴 {s['urgent_tickets']} urgent)" if s['urgent_tickets'] else ''))
    if s['renewals']:
        lines.append(f"🔁 Renewals in the next 7 days: *{len(s['renewals'])}*")
        for r in s['renewals'][:5]:
            lines.append(f"   • {r['expiry_date']:%d %b} · {r['item']} {r['label']} · {r['client_name']}")
    if s['unanswered']:
        lines.append(f"❓ Questions the bot couldn't answer: *{s['unanswered']}* (Dashboard > Bot knowledge)")
    for f in s['failures']:
        lines.append(f"⚠️ A {f['what']} message failed: {f['error'][:120]}")
    lines.append(f"\nDashboard: {config.DASHBOARD_URL}")
    one = (f"Daily summary: {s['leads_yesterday']} new enquiries yesterday, {s['not_contacted']} not contacted, "
           f"{s['waiting']} chats waiting, {len(s['calls'])} calls today, {s['open_tickets']} open requests, "
           f"{len(s['renewals'])} renewals this week")
    return '\n'.join(lines), one


def _pct(a, b):
    return f'{round(a / b * 100)}%' if b else '-'


def weekly_report_text(with_line=False):
    r = db.weekly_report_data()
    end = now_ist().date() - timedelta(days=1)
    start = end - timedelta(days=6)
    change = r['leads'] - r['leads_prev']
    trend = f"{'▲' if change > 0 else '▼' if change < 0 else '='} {abs(change)} vs the week before"
    lines = [f"📈 *Weekly report* · {start:%d %b} – {end:%d %b %Y}", '',
             f"📥 Enquiries: *{r['leads']}* ({trend})",
             f"   🤖 Bot {r['from_bot']} · 🏠 Home page {r['from_home']} · 📄 Contact page {r['from_contact']}"
             + (f" · 💬 WhatsApp button {r['via_wa_button']}" if r['via_wa_button'] else ''),
             f"📞 Contacted: *{r['contacted']}* of {r['leads']} ({_pct(r['contacted'], r['leads'])})",
             f"🏆 Won this week: *{r['won']}* · overall win rate {_pct(r['won_all'], r['decided_all'])}"]
    if r['services']:
        lines.append('🛠️ Most asked: ' + ', '.join(f"{x['name']} ({x['n']})" for x in r['services']))
    lines.append(f"💬 New chats: *{r['new_chats']}* · messages from customers: *{r['messages_in']}*")
    if r['busiest_hour'] is not None:
        h = r['busiest_hour']
        lines.append(f"⏰ Busiest time: {bot.time_label(f'{h:02d}:00')}–{bot.time_label(f'{(h + 1) % 24:02d}:00')}"
                     + (f" · busiest day: {r['busiest_day']}" if r['busiest_day'] else ''))
    lines.append(f"📅 Calls: *{r['calls']}* booked · {r['calls_done']} done")
    lines.append(f"🛠️ Support: *{r['tickets_new']}* new · {r['tickets_resolved']} resolved")
    lines.append(f"⭐ New reviews: *{r['reviews']}*")
    lines.append(f"\nDashboard: {config.DASHBOARD_URL}")
    text = '\n'.join(lines)
    if with_line:
        one = (f"Weekly report: {r['leads']} enquiries ({trend}), {r['won']} won, {r['new_chats']} new chats, "
               f"{r['calls']} calls, {r['tickets_new']} support requests, {r['reviews']} reviews")
        return text, one
    return text


def run_daily_reports():
    now = now_ist()
    h, m = map(int, config.DAILY_SUMMARY_AT.split(':'))
    if (now.hour, now.minute) < (h, m):
        return
    today = now.date().isoformat()
    late = now.hour >= 21                       # missed it (bot was off all day): skip until tomorrow
    if db.claim_state('daily_summary', today) and not late:
        text, one = daily_summary_text()
        _, error = send_admin_text(text, one)
        if error:
            log.warning('Daily summary not sent: %s', error)
    if now.weekday() == config.WEEKLY_REPORT_WEEKDAY and db.claim_state('weekly_report', today) and not late:
        text, one = weekly_report_text(with_line=True)
        _, error = send_admin_text(text, one)
        if error:
            log.warning('Weekly report not sent: %s', error)


# ---- S: website enquiry -> instant WhatsApp "we got your enquiry" ----------
def first_name(name):
    return (name or '').strip().split(' ')[0] or 'there'


def template_lang(enquiry_language):
    return config.TPL_LANG_TA if enquiry_language == 'ta' and config.TPL_LANG_TA else config.TPL_LANG


def process_enquiry_acks():
    if not config.ACK_WEBSITE_ENQUIRIES or not in_hours(config.ACK_HOURS):
        return
    for e in db.claim_enquiry_acks(config.ACK_MAX_AGE_HOURS):
        wa_id = bot.normalise_phone(e['phone'])
        if not wa_id or wa_id == config.ADMIN_WA_NUMBER:
            db.finish_ack(e['id'], 'skipped', 'No valid WhatsApp number')
            continue
        contact = db.get_contact(wa_id)
        if contact and contact['opted_out']:
            db.finish_ack(e['id'], 'skipped', 'Customer sent STOP')
            continue
        contact = contact or db.ensure_contact(wa_id, e['name'])
        if not contact['name']:
            db.update_contact(wa_id, name=e['name'][:120])
        services = ', '.join(e['services'] or []) or 'your project'
        _, error = wa.send_template(wa_id, config.TPL_ENQUIRY_RECEIVED, template_lang(e['language']),
                                    [first_name(e['name']), services], quick_reply_payloads=['m:call', 'm:menu'],
                                    preview=f'[Template {config.TPL_ENQUIRY_RECEIVED}] Thank you {first_name(e["name"])}, '
                                            f'we received your enquiry about {services}.', sender='system')
        db.finish_ack(e['id'], 'failed' if error else 'sent', error)


# ---- E: polite follow-up for enquiries still New / Quoted after 7 days -----
def process_followups():
    if not in_hours(config.FOLLOWUP_HOURS):
        return
    for e in db.claim_followups(config.FOLLOWUP_AFTER_DAYS, config.FOLLOWUP_MAX_AGE_DAYS):
        wa_id = bot.normalise_phone(e['phone'])
        if not wa_id or wa_id == config.ADMIN_WA_NUMBER:
            db.finish_followup(e['id'], 'skipped', 'No valid WhatsApp number')
            continue
        contact = db.get_contact(wa_id)
        if contact and contact['opted_out']:
            db.finish_followup(e['id'], 'skipped', 'Customer sent STOP')
            continue
        recent = contact and contact['last_outbound_at'] and db.now() - contact['last_outbound_at'] < timedelta(days=3)
        if recent or (contact and db.window_open(contact)):
            db.finish_followup(e['id'], 'skipped', 'Already in touch on WhatsApp recently')
            continue
        contact = contact or db.ensure_contact(wa_id, e['name'])
        if not contact['name']:
            db.update_contact(wa_id, name=e['name'][:120])
        services = ', '.join(e['services'] or []) or 'your project'
        _, error = wa.send_template(wa_id, config.TPL_LEAD_FOLLOWUP, template_lang(e['language']),
                                    [first_name(e['name']), services],
                                    quick_reply_payloads=[f"fu:call:{e['id']}", f"fu:details:{e['id']}", f"fu:no:{e['id']}"],
                                    preview=f'[Template {config.TPL_LEAD_FOLLOWUP}] Follow-up on enquiry #{e["id"]} ({services})',
                                    sender='system')
        db.finish_followup(e['id'], 'failed' if error else 'sent', error)


# ---- H: renewal reminders 30, 7 and 1 day before expiry --------------------
def process_renewals():
    if not in_hours(config.RENEWAL_HOURS):
        return
    for r in db.due_renewals():
        days = int(r['days_left'])
        when = f"{r['expiry_date'].day} {bot.MONTHS[r['expiry_date'].month - 1]} {r['expiry_date'].year}"
        label = r['label'] or r['project_title']
        errors = []
        for wa_id in r['wa_ids'] or []:
            contact = db.ensure_contact(wa_id, r['client_name'])
            if contact['opted_out'] and days > 1:
                continue                         # STOP is for offers; we still send the final 1-day notice
            if db.window_open(contact):
                L = bot.lang(contact)
                _, error = bot.buttons(contact, t(L, 'rn_reminder', item=t(L, 'item_' + r['item']), label=label,
                                                  date=when, days=days),
                                       [(f"rn:yes:{r['id']}", 'b_renew'), (f"rn:call:{r['id']}", 'b_call_me')])
            else:
                _, error = wa.send_template(wa_id, config.TPL_RENEWAL_REMINDER, config.TPL_LANG,
                                            [first_name(contact['name'] or r['client_name']), t('en', 'item_' + r['item']),
                                             label, when],
                                            quick_reply_payloads=[f"rn:yes:{r['id']}", f"rn:call:{r['id']}"],
                                            preview=f'[Template {config.TPL_RENEWAL_REMINDER}] {r["item"]} {label} expires {when}',
                                            sender='system')
            if error:
                errors.append(error)
        db.mark_renewal_reminded(r['id'], days)
        if errors:
            db.queue_alert('renewal_reply', f"Renewal reminder for {r['item']} {label} ({r['client_name']}) failed",
                           customer_name=r['client_name'], detail=errors[0], ref_id=r['id'])


# ===========================================================================
# Upgrade v3: a file (PDF, Word, Excel ...) a customer sent goes to AJ with the file attached
# ===========================================================================
def send_admin_file(alert):
    """Free document message when AJ's 24 hours are open, otherwise the aj_file_alert template (document header).
    If the file cannot be sent, AJ still gets a normal alert and can open the file in the dashboard chat."""
    try:
        info = json.loads(alert['detail'] or '{}')
    except ValueError:
        info = {}
    filename = info.get('filename') or 'file'
    caption = (f"📎 {alert['customer_name'] or 'A customer'} ({alert['customer_phone'] or '-'}) sent this file"
               + (f": {info['caption']}" if info.get('caption') else '') + '\nReply here if you want me to do anything about it.')
    plain = dict(alert, detail=f"File: {filename}" + (f"\nMessage: {info['caption']}" if info.get('caption') else '')
                 + '\nOpen the chat in the dashboard to download it.')
    data, mime = wa.download_media(info.get('media_id') or '', max_bytes=60 * 1024 * 1024) if info.get('media_id') else (None, '')
    if not data:
        return send_admin_alert(plain)
    media_id, error = wa.upload_media(data, mime or info.get('mime') or 'application/octet-stream', filename)
    if error:
        log.warning('Could not upload the file for AJ: %s', error)
        return send_admin_alert(plain)
    if db.window_open(admin_contact()):
        wamid, error = wa.send_document(config.ADMIN_WA_NUMBER, media_id, filename, caption)
        if not error:
            return wamid, error
    wamid, error = wa.send_template(config.ADMIN_WA_NUMBER, config.TPL_ADMIN_FILE, config.ADMIN_TEMPLATE_LANG,
                                    [alert['customer_name'] or 'A customer', alert['customer_phone'] or '-', filename],
                                    header_document={'id': media_id, 'filename': filename},
                                    preview=f"[Template {config.TPL_ADMIN_FILE}] {caption}", sender='system')
    if error:
        log.warning('File template not sent (%s); sending a normal alert', error)
        return send_admin_alert(plain)
    return wamid, error
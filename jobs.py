"""
Background jobs, run every WORKER_SECONDS (and by /cron/tick):

  * alerts and reminders to AJ (new enquiry, still-new enquiry, call booked, call soon ...)
  * call reminders to customers (only while their 24-hour window is open, so no template is needed)
  * a "continue?" message to customers who stopped halfway (sent before their 24-hour window closes)
  * offer broadcasts queued from the admin dashboard

Everything is claimed row by row in the database, so nothing is sent twice even
if two copies of the bot run for a moment during a deploy.
"""
import logging
import threading
import time

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
               'human_request', 'new_review', 'private_feedback', 'test'}
ICONS = {'new_enquiry': '📥', 'enquiry_reminder': '⏰', 'call_booked': '📅', 'call_reminder': '⏰',
         'call_cancelled': '❌', 'call_request': '📞', 'human_request': '🙋', 'new_review': '⭐',
         'private_feedback': '💬', 'test': '✅'}


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

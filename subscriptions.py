"""
Reminders for AJ's OWN subscriptions (upgrade v3): Render, Supabase, Meta, OpenAI, domain, SSL ...

Every day at SUBS_ALERT_AT (12:00 PM India time) the bot:
  1. checks what it can by itself:
       domain      expiry date from the public domain registry (RDAP), so no GoDaddy login is needed
       ssl         expiry date of the HTTPS certificate of each site
       meta_token  whether the WhatsApp access token still works (and if it has an expiry date)
       openai      whether the OpenAI key and credits still work
  2. sends AJ one WhatsApp message listing everything that renews / expires within SUBS_ALERT_DAYS (7) days,
     or is already overdue, plus any problem found. It repeats every day until AJ says it is renewed.

Items with auto_renew (card charged automatically, like Render) move to the next date by themselves once the date passes.
"""
import calendar
import logging
import socket
import ssl
from datetime import date, datetime, timedelta, timezone

import requests

import config
import db

log = logging.getLogger('bot.subs')
TIMEOUT = 15


def today():
    return datetime.now(config.TZ).date()


def add_cycle(d, cycle, times=1):
    if cycle == 'yearly':
        try:
            return d.replace(year=d.year + times)
        except ValueError:                       # 29 Feb
            return d.replace(year=d.year + times, day=28)
    if cycle == 'monthly':
        m = d.month - 1 + times
        y, m = d.year + m // 12, m % 12 + 1
        return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))
    return d


def fmt(d):
    return f'{d:%a %d %b %Y}'


def days_text(d):
    n = (d - today()).days
    if n < 0:
        return f'*EXPIRED {-n} day{"s" if n != -1 else ""} ago*'
    if n == 0:
        return '*today*'
    if n == 1:
        return '*tomorrow*'
    return f'in {n} days'


# ---------------------------------------------------------------------------
# Automatic checks
# ---------------------------------------------------------------------------
def check_domain(target):
    """Expiry date of a domain from RDAP (the public registry). Returns (date, note, problem)."""
    domain = target.strip().lower().removeprefix('https://').removeprefix('http://').split('/')[0]
    if not domain:
        return None, '', 'No domain name set'
    tld = domain.rsplit('.', 1)[-1]
    url = (f'https://rdap.verisign.com/{tld}/v1/domain/{domain}' if tld in ('com', 'net')
           else f'https://rdap.org/domain/{domain}')            # rdap.org forwards to the right registry
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={'Accept': 'application/rdap+json'})
    except requests.RequestException as e:
        return None, f'Could not check today ({type(e).__name__}); will try again tomorrow', ''
    if r.status_code == 404:
        return None, '', f'{domain} was not found in the registry. Is it still registered?'
    if r.status_code >= 400:
        return None, f'Domain registry answered {r.status_code}; will try again tomorrow', ''
    try:
        events = r.json().get('events') or []
    except ValueError:
        return None, 'Domain registry sent an unreadable answer; will try again tomorrow', ''
    for ev in events:
        if ev.get('eventAction') == 'expiration' and ev.get('eventDate'):
            expires = datetime.fromisoformat(ev['eventDate'].replace('Z', '+00:00')).astimezone(config.TZ).date()
            return expires, f'{domain} expires on {fmt(expires)} (registry)', ''
    return None, '', f'The registry did not give an expiry date for {domain}'


def ssl_expiry(host):
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 443), timeout=TIMEOUT) as sock:
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(cert['notAfter']), tz=timezone.utc).astimezone(config.TZ).date()


def check_ssl(target):
    hosts = [h.strip().lower() for h in target.split(',') if h.strip()]
    earliest, notes, problems = None, [], []
    for host in hosts:
        try:
            d = ssl_expiry(host)
        except ssl.SSLCertVerificationError as e:
            problems.append(f'{host}: the HTTPS certificate is not valid ({e.verify_message})')
            continue
        except Exception as e:
            notes.append(f'{host} not checked today ({type(e).__name__})')
            continue
        notes.append(f'{host} {d:%d %b %Y}')
        earliest = d if not earliest or d < earliest else earliest
    return earliest, ', '.join(notes), '; '.join(problems)


def check_meta_token(_target=''):
    if not config.META_ACCESS_TOKEN:
        return None, '', 'META_ACCESS_TOKEN is not set on Render'
    try:
        r = requests.get(f'{config.GRAPH_BASE}/{config.GRAPH_VERSION}/debug_token', timeout=TIMEOUT,
                         params={'input_token': config.META_ACCESS_TOKEN, 'access_token': config.META_ACCESS_TOKEN})
    except requests.RequestException as e:
        return None, f'Could not check today ({type(e).__name__}); will try again tomorrow', ''
    try:
        data = r.json().get('data') or {}
    except ValueError:
        data = {}
    if r.status_code >= 400 or not data.get('is_valid', False):
        try:
            message = r.json().get('error', {}).get('message', '') or (data.get('error') or {}).get('message', '')
        except ValueError:
            message = ''
        return None, '', ('The WhatsApp access token is NOT working, so the bot cannot send messages. Create a new '
                          'token (Meta Business Settings > System users > Generate token) and update '
                          f'META_ACCESS_TOKEN on Render. {message}').strip()
    expires = int(data.get('expires_at') or 0)
    if expires:
        d = datetime.fromtimestamp(expires, tz=timezone.utc).astimezone(config.TZ).date()
        return d, f'Token works; it expires on {fmt(d)}', ''
    return None, 'Token works and never expires', ''


def check_openai(_target=''):
    if not config.OPENAI_API_KEY:
        return None, '', 'OPENAI_API_KEY is not set on Render, so the bot answers with menus only'
    import ai
    try:
        ai.client().chat.completions.create(model=config.OPENAI_MODEL, max_tokens=1,
                                            messages=[{'role': 'user', 'content': 'hi'}])
    except Exception as e:
        kind = ai.problem_kind(e)
        if kind == 'quota':
            return None, '', ('OpenAI credits are finished, so the bot answers with menus only. Recharge at '
                              'platform.openai.com > Settings > Billing.')
        if kind == 'key':
            return None, '', 'The OpenAI API key is not working. Check OPENAI_API_KEY on Render.'
        return None, f'Could not check today ({type(e).__name__}); will try again tomorrow', ''
    return None, 'OpenAI key and credits work', ''


CHECKS = {'domain': check_domain, 'ssl': check_ssl, 'meta_token': check_meta_token, 'openai': check_openai}


def run_check(sub):
    fn = CHECKS.get(sub['check_kind'])
    if not fn:
        return sub
    try:
        found, note, problem = fn(sub['check_target'] or '')
    except Exception as e:
        log.exception('Check of %s failed', sub['name'])
        found, note, problem = None, f'Could not check today ({type(e).__name__})', ''
    return db.set_subscription_check(sub['id'], found, note, problem) or sub


def roll_forward(sub):
    """Auto-paid items (card charged automatically) move to their next date once the date has passed."""
    d = sub['renews_on']
    if not d or not sub['auto_renew'] or sub['cycle'] == 'none' or d >= today():
        return sub
    while d < today():
        d = add_cycle(d, sub['cycle'])
    return db.save_subscription(sub['id'], renews_on=d) or sub


def check_all():
    out = []
    for sub in db.subscriptions():
        sub = run_check(sub)
        out.append(roll_forward(sub))
    return out


# ---------------------------------------------------------------------------
# The daily reminder
# ---------------------------------------------------------------------------
def due(subs):
    limit = today() + timedelta(days=config.SUBS_ALERT_DAYS)
    return [s for s in subs if s['renews_on'] and s['renews_on'] <= limit]


def reminder_text(subs, monday=False):
    """(full text, one line) or (None, None) when there is nothing to say."""
    soon = sorted(due(subs), key=lambda s: s['renews_on'])
    problems = [s for s in subs if s['last_problem']]
    unset = [s for s in subs if not s['renews_on'] and s['cycle'] != 'none' and s['check_kind'] == 'none'] if monday else []
    if not soon and not problems and not unset:
        return None, None
    lines = ['🔔 *Subscription reminder*', '']
    if soon:
        lines.append(f'Renews / expires within {config.SUBS_ALERT_DAYS} days:')
        for s in soon:
            extra = ' · auto-pay' if s['auto_renew'] else ''
            amount = f" · {s['amount_text']}" if s['amount_text'] else ''
            lines.append(f"• *{s['name']}*: {fmt(s['renews_on'])} ({days_text(s['renews_on'])}){amount}{extra}")
        lines.append('')
    for s in problems:
        lines.append(f"⚠️ *{s['name']}*: {s['last_problem']}")
    if problems:
        lines.append('')
    if unset:
        lines.append('📅 No date set yet for: ' + ', '.join(s['name'] for s in unset) +
                     '. Tell me the date and I will remind you.')
        lines.append('')
    if soon:
        lines.append('After you renew, just tell me (e.g. "Render renewed") and I will stop reminding you. '
                     'Domain and SSL dates update by themselves.')
    text = '\n'.join(lines).strip()
    first = soon[0] if soon else None
    one = (f"Subscription reminder: {first['name']} on {first['renews_on']:%d %b} ({days_text(first['renews_on']).strip('*')})"
           + (f' and {len(soon) - 1} more' if len(soon) > 1 else '') if first else
           f"Subscription problem: {problems[0]['name']}: {problems[0]['last_problem']}" if problems else
           'Some subscriptions have no renewal date yet')
    return text, one[:280]


def run_daily():
    """Called by jobs.tick() every 20 seconds; does its work once a day at SUBS_ALERT_AT (India time)."""
    now = datetime.now(config.TZ)
    h, m = map(int, config.SUBS_ALERT_AT.split(':'))
    if (now.hour, now.minute) < (h, m) or now.hour >= 21:
        return
    if not db.claim_state('subs_alert', now.date().isoformat()):
        return
    subs = check_all()
    text, one = reminder_text(subs, monday=now.weekday() == 0)
    if text:
        import jobs
        _, error = jobs.send_admin_text(text, one)
        if error:
            log.warning('Subscription reminder not sent: %s', error)


# ---------------------------------------------------------------------------
# Used by AJ's assistant (admin.py)
# ---------------------------------------------------------------------------
def describe(s):
    out = {'id': s['id'], 'name': s['name'], 'renews_on': f"{s['renews_on']:%a %d %b %Y}" if s['renews_on'] else None,
           'cycle': s['cycle'], 'auto_pay': s['auto_renew'], 'auto_check': s['check_kind'],
           'amount': s['amount_text'] or None, 'notes': s['notes'] or None}
    if s['renews_on']:
        out['when'] = days_text(s['renews_on']).replace('*', '')
    if s['last_check_note']:
        out['last_check'] = s['last_check_note']
    if s['last_problem']:
        out['problem'] = s['last_problem']
    return out


def mark_renewed(sub, next_date=None):
    """Move to the next renewal date. Returns (subscription, message)."""
    if sub['check_kind'] in ('domain', 'ssl', 'meta_token', 'openai'):
        fresh = run_check(sub)
        if sub['check_kind'] in ('domain', 'ssl'):
            if fresh['renews_on'] and fresh['renews_on'] > (sub['renews_on'] or date.min):
                return fresh, f"Checked: the new date is {fmt(fresh['renews_on'])}."
            if not next_date:
                return fresh, ('The registry still shows the old date. It can take a day to update; I will check '
                               'again tomorrow at 12 PM.')
        elif not next_date:
            return fresh, fresh['last_problem'] or fresh['last_check_note'] or 'Checked.'
    if next_date:
        d = next_date
    elif sub['renews_on'] and sub['cycle'] != 'none':
        d = add_cycle(sub['renews_on'], sub['cycle'])
        while d <= today():
            d = add_cycle(d, sub['cycle'])
    else:
        return sub, 'Tell me the new renewal / expiry date, so I can remind you next time.'
    fresh = db.save_subscription(sub['id'], renews_on=d)
    return fresh, f'Next renewal: {fmt(d)}. I will remind you from {fmt(d - timedelta(days=config.SUBS_ALERT_DAYS))}.'
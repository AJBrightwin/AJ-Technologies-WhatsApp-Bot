"""
Database access for the bot (Supabase PostgreSQL through DATABASE_URL).

Every query lives here, so the rest of the bot never writes SQL.
Tables: see supabase_whatsapp.sql (wa_*) and the website's supabase_schema.sql.
"""
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

import config

log = logging.getLogger('bot.db')
_pool = None
_pool_lock = threading.Lock()


def _conninfo():
    url = config.DATABASE_URL
    if config.DATABASE_SSL and 'sslmode=' not in url:
        url += ('&' if '?' in url else '?') + 'sslmode=require'
    return url


def pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    _conninfo(), min_size=1, max_size=4, timeout=20, open=True,
                    kwargs={'autocommit': True, 'row_factory': dict_row, 'prepare_threshold': None,
                            'connect_timeout': 10},
                    check=ConnectionPool.check_connection, name='bot')
    return _pool


def rows(sql, params=()):
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def one(sql, params=()):
    with pool().connection() as conn:
        return conn.execute(sql, params).fetchone()


def run(sql, params=()):
    with pool().connection() as conn:
        return conn.execute(sql, params).rowcount


def ping():
    return one('SELECT 1 AS ok')['ok'] == 1


def now():
    return datetime.now(timezone.utc)


def preview(text):
    return ' '.join(str(text or '').split())[:200]


# ---------------------------------------------------------------------------
# Contacts + messages
# ---------------------------------------------------------------------------
def save_inbound(wa_id, profile_name, wamid, msg_type, body, sent_at,
                 media_id='', media_mime='', media_filename='', count_unread=True):
    """Save a customer's message. Returns (contact, message_id), or (None, None) if it is a duplicate."""
    with pool().connection() as conn:
        with conn.transaction():
            conn.execute(
                """INSERT INTO wa_contacts (wa_id, profile_name) VALUES (%s, %s)
                   ON CONFLICT (wa_id) DO UPDATE
                   SET profile_name = COALESCE(NULLIF(EXCLUDED.profile_name, ''), wa_contacts.profile_name)""",
                (wa_id, (profile_name or '')[:120]))
            msg = conn.execute(
                """INSERT INTO wa_messages (wa_id, direction, sender, msg_type, body, media_id, media_mime,
                                            media_filename, wamid, status, created_at)
                   VALUES (%s, 'in', 'customer', %s, %s, %s, %s, %s, %s, 'received', %s)
                   ON CONFLICT (wamid) DO NOTHING RETURNING id""",
                (wa_id, msg_type[:20], body or '', media_id[:100], media_mime[:100], media_filename[:200],
                 wamid, sent_at)).fetchone()
            if not msg:
                return None, None
            contact = conn.execute(
                """UPDATE wa_contacts
                   SET unread_count = unread_count + %s,
                       last_inbound_at = GREATEST(COALESCE(last_inbound_at, %s), %s),
                       last_message_at = GREATEST(COALESCE(last_message_at, %s), %s),
                       last_message_preview = %s
                   WHERE wa_id = %s RETURNING *""",
                (1 if count_unread else 0, sent_at, sent_at, sent_at, sent_at,
                 preview(body or f'[{msg_type}]'), wa_id)).fetchone()
            return contact, msg['id']


def set_message_body(message_id, body):
    run('UPDATE wa_messages SET body = %s WHERE id = %s', (body or '', message_id))
    run("""UPDATE wa_contacts c SET last_message_preview = %s
           FROM wa_messages m WHERE m.id = %s AND c.wa_id = m.wa_id""", (preview(body), message_id))


def get_contact(wa_id):
    return one('SELECT * FROM wa_contacts WHERE wa_id = %s', (wa_id,))


def ensure_contact(wa_id, profile_name=''):
    run("""INSERT INTO wa_contacts (wa_id, profile_name) VALUES (%s, %s)
           ON CONFLICT (wa_id) DO NOTHING""", (wa_id, profile_name[:120]))
    return get_contact(wa_id)


CONTACT_FIELDS = {'name', 'business_name', 'email', 'language', 'language_locked', 'opted_out',
                  'opted_out_at', 'needs_reply', 'state', 'nudged_at', 'bot_enabled', 'unread_count'}


def update_contact(wa_id, **fields):
    fields = {k: v for k, v in fields.items() if k in CONTACT_FIELDS}
    if not fields:
        return get_contact(wa_id)
    sets, values = [], []
    for key, value in fields.items():
        sets.append(f'{key} = %s')
        values.append(Jsonb(value) if key == 'state' else value)
    values.append(wa_id)
    return one(f'UPDATE wa_contacts SET {", ".join(sets)} WHERE wa_id = %s RETURNING *', values)


def save_outbound(wa_id, sender, msg_type, body, wamid=None, status='sent', error=''):
    at = now()
    msg = one("""INSERT INTO wa_messages (wa_id, direction, sender, msg_type, body, wamid, status, error, created_at)
                 VALUES (%s, 'out', %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
              (wa_id, sender, msg_type, body or '', wamid, status, error or '', at))
    if status != 'failed':
        run("""UPDATE wa_contacts SET last_outbound_at = %s, last_message_at = %s, last_message_preview = %s
               WHERE wa_id = %s""", (at, at, preview(body), wa_id))
    return msg['id']


STATUS_RANK = {'sent': 1, 'delivered': 2, 'read': 3}


def update_message_status(wamid, status, error=''):
    """Delivery receipts from WhatsApp. Never moves backwards (read stays read)."""
    if status == 'failed':
        run("UPDATE wa_messages SET status = 'failed', error = %s WHERE wamid = %s", (error[:1000], wamid))
        run("UPDATE wa_broadcast_recipients SET status = 'failed', error = %s WHERE wamid = %s AND status = 'sent'",
            (error[:1000], wamid))
        return
    rank = STATUS_RANK.get(status)
    if not rank:
        return
    run("""UPDATE wa_messages SET status = %s
           WHERE wamid = %s AND status <> 'failed'
             AND (CASE status WHEN 'sent' THEN 1 WHEN 'delivered' THEN 2 WHEN 'read' THEN 3 ELSE 0 END) < %s""",
        (status, wamid, rank))


def recent_messages(wa_id, limit=16):
    got = rows("""SELECT direction, sender, msg_type, body, created_at FROM wa_messages
                  WHERE wa_id = %s AND body <> '' ORDER BY id DESC LIMIT %s""", (wa_id, limit))
    return list(reversed(got))


def window_open(contact):
    """True when the customer messaged within 24 hours, so free-form messages are allowed."""
    last = contact and contact.get('last_inbound_at')
    return bool(last) and now() - last < timedelta(hours=23, minutes=50)


# ---------------------------------------------------------------------------
# Enquiries (contact_enquiries, the same table as the website forms)
# ---------------------------------------------------------------------------
def insert_enquiry(name, phone, email, business_name, services, timeline, contact_method, message, language):
    row = one("""INSERT INTO contact_enquiries
                 (name, phone, email, business_name, services, timeline, contact_method, message,
                  source, submitted_via, language, status)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'bot', 'bot', %s, 'new') RETURNING id""",
              (name[:120], phone[:30], email[:254], business_name[:160], Jsonb(list(services)), timeline,
               contact_method, message[:5000], 'ta' if language == 'ta' else 'en'))
    return row['id']


def enquiry_status(enquiry_id):
    row = one('SELECT status FROM contact_enquiries WHERE id = %s', (enquiry_id,))
    return row['status'] if row else None


def latest_enquiry(phone_digits):
    return one("""SELECT * FROM contact_enquiries
                  WHERE regexp_replace(phone, '\\D', '', 'g') IN (%s, %s)
                  ORDER BY created_at DESC LIMIT 1""", (phone_digits, phone_digits[-10:]))


# ---------------------------------------------------------------------------
# Portfolio (showcase_projects; only real, published projects)
# ---------------------------------------------------------------------------
def real_projects(limit=10):
    return rows("""SELECT * FROM showcase_projects WHERE is_published AND NOT is_sample
                   ORDER BY sort_order, created_at DESC LIMIT %s""", (limit,))


def get_project(project_id):
    return one('SELECT * FROM showcase_projects WHERE id = %s AND is_published AND NOT is_sample', (project_id,))


# ---------------------------------------------------------------------------
# Call bookings
# ---------------------------------------------------------------------------
def booked_slots(day_from, day_to):
    got = rows("""SELECT call_date, call_time FROM wa_bookings
                  WHERE status = 'booked' AND call_date BETWEEN %s AND %s""", (day_from, day_to))
    return {(r['call_date'], r['call_time'].strftime('%H:%M')) for r in got}


def insert_booking(wa_id, name, phone, topic, call_date, call_time, enquiry_id=None):
    """Returns the new booking, or None when someone else took the slot a moment ago."""
    try:
        return one("""INSERT INTO wa_bookings (wa_id, name, phone, topic, call_date, call_time, enquiry_id)
                      VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                   (wa_id, name[:120], phone[:30], topic[:500], call_date, call_time, enquiry_id))
    except psycopg.errors.UniqueViolation:
        return None


def upcoming_booking(wa_id):
    return one("""SELECT * FROM wa_bookings WHERE wa_id = %s AND status = 'booked'
                    AND (call_date + call_time) >= (now() AT TIME ZONE 'Asia/Kolkata') - interval '30 minutes'
                  ORDER BY call_date, call_time LIMIT 1""", (wa_id,))


def get_booking(booking_id):
    return one('SELECT * FROM wa_bookings WHERE id = %s', (booking_id,))


def set_booking_status(booking_id, status):
    return one('UPDATE wa_bookings SET status = %s WHERE id = %s RETURNING *', (status, booking_id))


# ---------------------------------------------------------------------------
# Reviews (client_reviews; saved hidden, you publish them from the dashboard)
# ---------------------------------------------------------------------------
def insert_review(client_name, business_name, location, rating, review_en, review_ta):
    row = one("""INSERT INTO client_reviews (client_name, business_name, location, rating, review_en, review_ta,
                                             source, is_published, sort_order)
                 VALUES (%s, %s, %s, %s, %s, %s, 'whatsapp', false,
                         COALESCE((SELECT max(sort_order) + 10 FROM client_reviews), 10))
                 RETURNING id""",
              (client_name[:120], business_name[:160], location[:120], rating, review_en[:2000], review_ta[:2000]))
    return row['id']


# ---------------------------------------------------------------------------
# Alerts / reminders (wa_admin_alerts works as a small outbox)
# ---------------------------------------------------------------------------
def queue_alert(kind, summary, wa_id='', customer_name='', customer_phone='', detail='', ref_id=None, due_at=None):
    row = one("""INSERT INTO wa_admin_alerts (kind, ref_id, wa_id, summary, customer_name, customer_phone, detail, due_at)
                 VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
              (kind, ref_id, wa_id, summary[:300], customer_name[:120], customer_phone[:30], detail, due_at or now()))
    return row['id']


def recent_alert(kind, wa_id, hours):
    return one("""SELECT id FROM wa_admin_alerts WHERE kind = %s AND wa_id = %s
                  AND created_at > now() - make_interval(hours => %s) LIMIT 1""", (kind, wa_id, hours)) is not None


def claim_alerts(limit=10):
    # rows stuck in "sending" (the bot restarted mid-send) go back to the queue
    run("UPDATE wa_admin_alerts SET status = 'pending' WHERE status = 'sending' AND due_at < now() - interval '10 minutes'")
    return rows("""UPDATE wa_admin_alerts SET status = 'sending', attempts = attempts + 1, due_at = now()
                   WHERE id IN (SELECT id FROM wa_admin_alerts WHERE status = 'pending' AND due_at <= now()
                                ORDER BY due_at LIMIT %s FOR UPDATE SKIP LOCKED)
                   RETURNING *""", (limit,))


def finish_alert(alert_id, status, error=''):
    run("""UPDATE wa_admin_alerts SET status = %s, error = %s,
                  sent_at = CASE WHEN %s = 'sent' THEN now() ELSE sent_at END
           WHERE id = %s""", (status, error[:1000], status, alert_id))


def retry_alert(alert_id, error, minutes=5):
    run("""UPDATE wa_admin_alerts SET status = 'pending', error = %s, due_at = now() + make_interval(mins => %s)
           WHERE id = %s""", (error[:1000], minutes, alert_id))


def cancel_alerts(kind, ref_id):
    run("""UPDATE wa_admin_alerts SET status = 'skipped', error = 'No longer needed'
           WHERE kind = %s AND ref_id = %s AND status = 'pending'""", (kind, ref_id))


# ---------------------------------------------------------------------------
# Follow-ups for customers who stopped halfway
# ---------------------------------------------------------------------------
def claim_nudges(after_hours, limit=20):
    return rows("""UPDATE wa_contacts SET nudged_at = now()
                   WHERE wa_id IN (
                       SELECT wa_id FROM wa_contacts
                       WHERE bot_enabled AND state ? 'flow'
                         AND last_inbound_at < now() - make_interval(hours => %s)
                         AND last_inbound_at > now() - interval '23 hours 40 minutes'
                         AND (nudged_at IS NULL OR nudged_at < last_inbound_at)
                       LIMIT %s FOR UPDATE SKIP LOCKED)
                   RETURNING *""", (after_hours, limit))


# ---------------------------------------------------------------------------
# Broadcasts
# ---------------------------------------------------------------------------
def claim_broadcast_recipients(limit):
    run("""UPDATE wa_broadcast_recipients SET status = 'queued'
           WHERE status = 'sending' AND id IN (
               SELECT r.id FROM wa_broadcast_recipients r JOIN wa_broadcasts b ON b.id = r.broadcast_id
               WHERE b.status = 'sending' AND b.started_at < now() - interval '15 minutes'
                 AND r.status = 'sending' AND r.sent_at IS NULL)""")
    got = rows("""UPDATE wa_broadcast_recipients SET status = 'sending'
                  WHERE id IN (
                      SELECT r.id FROM wa_broadcast_recipients r
                      JOIN wa_broadcasts b ON b.id = r.broadcast_id
                      WHERE r.status = 'queued' AND b.status IN ('queued', 'sending')
                      ORDER BY b.id, r.id LIMIT %s FOR UPDATE OF r SKIP LOCKED)
                  RETURNING id, broadcast_id, wa_id""", (limit,))
    if not got:
        return []
    ids = [r['id'] for r in got]
    run("""UPDATE wa_broadcasts SET status = 'sending', started_at = COALESCE(started_at, now())
           WHERE status = 'queued' AND id IN (SELECT DISTINCT broadcast_id FROM wa_broadcast_recipients WHERE id = ANY(%s))""",
        (ids,))
    return rows("""SELECT r.id, r.wa_id, r.broadcast_id, b.template_name, b.template_language, b.params,
                          b.header_image_url, b.body_preview, b.status AS broadcast_status,
                          c.name, c.profile_name, c.opted_out
                   FROM wa_broadcast_recipients r
                   JOIN wa_broadcasts b ON b.id = r.broadcast_id
                   LEFT JOIN wa_contacts c ON c.wa_id = r.wa_id
                   WHERE r.id = ANY(%s) ORDER BY r.id""", (ids,))


def finish_recipient(recipient_id, status, error='', wamid=''):
    run("""UPDATE wa_broadcast_recipients SET status = %s, error = %s, wamid = %s,
                  sent_at = CASE WHEN %s = 'sent' THEN now() ELSE sent_at END
           WHERE id = %s""", (status, error[:1000], wamid, status, recipient_id))


def refresh_broadcasts():
    """Update the sent / failed counters and close finished broadcasts."""
    run("""UPDATE wa_broadcasts b SET
               total = s.total, sent = s.sent, failed = s.failed,
               status = CASE WHEN b.status = 'sending' AND s.open = 0 THEN 'done' ELSE b.status END,
               finished_at = CASE WHEN b.status = 'sending' AND s.open = 0 THEN now() ELSE b.finished_at END
           FROM (SELECT broadcast_id, count(*) AS total,
                        count(*) FILTER (WHERE status = 'sent') AS sent,
                        count(*) FILTER (WHERE status IN ('failed', 'skipped')) AS failed,
                        count(*) FILTER (WHERE status IN ('queued', 'sending')) AS open
                 FROM wa_broadcast_recipients GROUP BY broadcast_id) s
           WHERE s.broadcast_id = b.id AND b.status IN ('queued', 'sending', 'cancelled')""")


# ---------------------------------------------------------------------------
# Summary for AJ (when he messages the bot himself)
# ---------------------------------------------------------------------------
def admin_summary():
    return one("""SELECT
        (SELECT count(*) FROM contact_enquiries WHERE status = 'new') AS new_enquiries,
        (SELECT count(*) FROM contact_enquiries WHERE source = 'bot' AND created_at > now() - interval '24 hours') AS bot_today,
        (SELECT count(*) FROM wa_contacts WHERE needs_reply) AS needs_reply,
        (SELECT count(*) FROM wa_bookings WHERE status = 'booked'
            AND call_date = (now() AT TIME ZONE 'Asia/Kolkata')::date) AS calls_today,
        (SELECT count(*) FROM wa_bookings WHERE status = 'booked'
            AND call_date > (now() AT TIME ZONE 'Asia/Kolkata')::date) AS calls_later""")


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str)


# ===========================================================================
# Upgrade v2 (supabase_upgrade_v2.sql)
# ===========================================================================
# ---- once-a-day jobs ------------------------------------------------------
def claim_state(key, value):
    """True only for the first caller that stores this value (e.g. today's date) for this key."""
    return one("""INSERT INTO bot_state (key, value) VALUES (%s, %s)
                  ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                  WHERE bot_state.value IS DISTINCT FROM EXCLUDED.value
                  RETURNING key""", (key, value)) is not None


def get_state(key):
    row = one('SELECT value FROM bot_state WHERE key = %s', (key,))
    return row['value'] if row else ''


# ---- client data: ALWAYS filtered by the exact WhatsApp number -----------
def client_projects(wa_id, limit=5):
    return rows("""SELECT * FROM client_projects WHERE %s = ANY(wa_ids) AND is_active
                   ORDER BY updated_at DESC LIMIT %s""", (wa_id, limit))


def client_project(project_id, wa_id):
    """A project only if it belongs to this number (never another client's)."""
    return one('SELECT * FROM client_projects WHERE id = %s AND %s = ANY(wa_ids)', (project_id, wa_id))


def client_renewals(project_ids, days=60):
    if not project_ids:
        return []
    return rows("""SELECT * FROM client_renewals WHERE project_id = ANY(%s) AND status = 'active'
                   AND expiry_date <= (now() AT TIME ZONE 'Asia/Kolkata')::date + %s
                   ORDER BY expiry_date""", (list(project_ids), days))


def client_tickets(wa_id, limit=5, open_only=False):
    return rows(f"""SELECT t.*, p.title AS project_title FROM support_tickets t
                    LEFT JOIN client_projects p ON p.id = t.project_id
                    WHERE t.wa_id = %s {"AND t.status NOT IN ('resolved', 'closed')" if open_only else ''}
                    ORDER BY t.created_at DESC LIMIT %s""", (wa_id, limit))


def create_ticket(wa_id, project_id, client_name, description, attachments, priority):
    return one("""INSERT INTO support_tickets (wa_id, project_id, client_name, description, attachments, priority)
                  VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
               (wa_id, project_id, client_name[:120], description[:4000], attachments, priority))


def get_ticket(ticket_id):
    return one("""SELECT t.*, p.title AS project_title FROM support_tickets t
                  LEFT JOIN client_projects p ON p.id = t.project_id WHERE t.id = %s""", (ticket_id,))


def set_ticket_status(ticket_id, status, client_update=''):
    return one("""UPDATE support_tickets SET status = %s,
                         client_update = CASE WHEN %s <> '' THEN %s ELSE client_update END,
                         resolved_at = CASE WHEN %s IN ('resolved', 'closed') THEN COALESCE(resolved_at, now()) ELSE NULL END
                  WHERE id = %s RETURNING *""", (status, client_update, client_update, status, ticket_id))


# ---- knowledge -------------------------------------------------------------
def knowledge():
    return rows("""SELECT kind, question, answer FROM bot_knowledge WHERE is_active
                   ORDER BY sort_order, id LIMIT 80""")


def add_unanswered(wa_id, question):
    question = ' '.join(str(question or '').split())[:1000]
    if not question:
        return
    run("""INSERT INTO bot_unanswered (wa_id, question)
           SELECT %s, %s WHERE NOT EXISTS (
               SELECT 1 FROM bot_unanswered WHERE status = 'pending' AND lower(question) = lower(%s)
                 AND created_at > now() - interval '14 days')""", (wa_id, question, question))


# ---- website enquiry acknowledgements (S) ----------------------------------
def claim_enquiry_acks(max_age_hours, limit=10):
    return rows("""WITH c AS (
                       INSERT INTO wa_enquiry_acks (enquiry_id, status)
                       SELECT id, 'sending' FROM contact_enquiries
                       WHERE source IN ('home', 'contact')
                         AND created_at > now() - make_interval(hours => %s)
                         AND length(regexp_replace(phone, '\\D', '', 'g')) >= 10
                       ORDER BY created_at LIMIT %s
                       ON CONFLICT (enquiry_id) DO NOTHING RETURNING enquiry_id)
                   SELECT e.* FROM contact_enquiries e JOIN c ON c.enquiry_id = e.id""", (max_age_hours, limit))


def finish_ack(enquiry_id, status, error=''):
    run('UPDATE wa_enquiry_acks SET status = %s, error = %s WHERE enquiry_id = %s', (status, error[:1000], enquiry_id))


# ---- old-lead follow-ups (E) -----------------------------------------------
def claim_followups(after_days, max_age_days, limit=10):
    return rows("""WITH c AS (
                       INSERT INTO wa_lead_followups (enquiry_id, status)
                       SELECT id, 'sending' FROM contact_enquiries
                       WHERE status IN ('new', 'quoted')
                         AND created_at < now() - make_interval(days => %s)
                         AND created_at > now() - make_interval(days => %s)
                         AND length(regexp_replace(phone, '\\D', '', 'g')) >= 10
                       ORDER BY created_at LIMIT %s
                       ON CONFLICT (enquiry_id) DO NOTHING RETURNING enquiry_id)
                   SELECT e.* FROM contact_enquiries e JOIN c ON c.enquiry_id = e.id""",
                (after_days, max_age_days, limit))


def finish_followup(enquiry_id, status, error=''):
    run('UPDATE wa_lead_followups SET status = %s, error = %s WHERE enquiry_id = %s', (status, error[:1000], enquiry_id))


def followup_reply(enquiry_id, reply):
    run('UPDATE wa_lead_followups SET reply = %s WHERE enquiry_id = %s', (reply, enquiry_id))


def get_enquiry(enquiry_id):
    return one('SELECT * FROM contact_enquiries WHERE id = %s', (enquiry_id,))


def set_enquiry_status(enquiry_id, status):
    return one('UPDATE contact_enquiries SET status = %s WHERE id = %s RETURNING *', (status, enquiry_id))


# ---- renewals (H) ----------------------------------------------------------
def due_renewals(limit=30):
    """Renewals that reached the 30 / 7 / 1 day mark and were not reminded for it yet."""
    return rows("""SELECT r.*, p.client_name, p.business_name, p.wa_ids, p.title AS project_title,
                          (r.expiry_date - (now() AT TIME ZONE 'Asia/Kolkata')::date) AS days_left
                   FROM client_renewals r JOIN client_projects p ON p.id = r.project_id
                   WHERE r.status = 'active' AND r.auto_remind AND p.is_active
                     AND r.expiry_date >= (now() AT TIME ZONE 'Asia/Kolkata')::date
                     AND ((r.expiry_date - (now() AT TIME ZONE 'Asia/Kolkata')::date <= 1 AND r.reminded_1_at IS NULL)
                       OR (r.expiry_date - (now() AT TIME ZONE 'Asia/Kolkata')::date <= 7 AND r.reminded_7_at IS NULL)
                       OR (r.expiry_date - (now() AT TIME ZONE 'Asia/Kolkata')::date <= 30 AND r.reminded_30_at IS NULL))
                   ORDER BY r.expiry_date LIMIT %s""", (limit,))


def mark_renewal_reminded(renewal_id, days_left):
    """Marks this mark and every earlier one, so a reminder is never sent twice."""
    run("""UPDATE client_renewals SET
               reminded_30_at = COALESCE(reminded_30_at, now()),
               reminded_7_at  = CASE WHEN %s <= 7 THEN COALESCE(reminded_7_at, now()) ELSE reminded_7_at END,
               reminded_1_at  = CASE WHEN %s <= 1 THEN COALESCE(reminded_1_at, now()) ELSE reminded_1_at END
           WHERE id = %s""", (days_left, days_left, renewal_id))


def get_renewal(renewal_id):
    return one("""SELECT r.*, p.client_name, p.wa_ids, p.title AS project_title FROM client_renewals r
                  JOIN client_projects p ON p.id = r.project_id WHERE r.id = %s""", (renewal_id,))


# ---- summaries for AJ (O, P, N) -------------------------------------------
IST_TODAY = "(now() AT TIME ZONE 'Asia/Kolkata')::date"
IST_DAY = "(created_at AT TIME ZONE 'Asia/Kolkata')::date"


def daily_summary_data():
    s = one(f"""SELECT
        (SELECT count(*) FROM contact_enquiries WHERE {IST_DAY} = {IST_TODAY} - 1) AS leads_yesterday,
        (SELECT count(*) FROM contact_enquiries WHERE {IST_DAY} = {IST_TODAY} - 1 AND source = 'bot') AS bot_yesterday,
        (SELECT count(*) FROM contact_enquiries WHERE status = 'new') AS not_contacted,
        (SELECT count(*) FROM wa_contacts WHERE needs_reply AND wa_id <> %s) AS waiting,
        (SELECT count(DISTINCT wa_id) FROM wa_messages WHERE direction = 'in' AND wa_id <> %s
            AND {IST_DAY} = {IST_TODAY} - 1) AS chats_yesterday,
        (SELECT count(*) FROM support_tickets WHERE status NOT IN ('resolved', 'closed')) AS open_tickets,
        (SELECT count(*) FROM support_tickets WHERE status NOT IN ('resolved', 'closed') AND priority = 'urgent') AS urgent_tickets,
        (SELECT count(*) FROM bot_unanswered WHERE status = 'pending') AS unanswered""",
        (config.ADMIN_WA_NUMBER, config.ADMIN_WA_NUMBER))
    s['calls'] = rows(f"""SELECT name, phone, call_time, topic FROM wa_bookings
                          WHERE status = 'booked' AND call_date = {IST_TODAY} ORDER BY call_time""")
    s['renewals'] = rows(f"""SELECT r.item, r.label, r.expiry_date, p.client_name FROM client_renewals r
                             JOIN client_projects p ON p.id = r.project_id
                             WHERE r.status = 'active' AND r.expiry_date BETWEEN {IST_TODAY} AND {IST_TODAY} + 7
                             ORDER BY r.expiry_date""")
    s['failures'] = rows("""SELECT 'follow-up' AS what, error FROM wa_lead_followups
                                WHERE status = 'failed' AND created_at > now() - interval '1 day'
                            UNION ALL
                            SELECT 'website thank-you', error FROM wa_enquiry_acks
                                WHERE status = 'failed' AND created_at > now() - interval '1 day'
                            LIMIT 5""")
    return s


def weekly_report_data():
    """Last 7 full days (India time) compared with the 7 days before."""
    week = f"{IST_DAY} BETWEEN {IST_TODAY} - 7 AND {IST_TODAY} - 1"
    prev = f"{IST_DAY} BETWEEN {IST_TODAY} - 14 AND {IST_TODAY} - 8"
    r = one(f"""SELECT
        (SELECT count(*) FROM contact_enquiries WHERE {week}) AS leads,
        (SELECT count(*) FROM contact_enquiries WHERE {prev}) AS leads_prev,
        (SELECT count(*) FROM contact_enquiries WHERE {week} AND source = 'bot') AS from_bot,
        (SELECT count(*) FROM contact_enquiries WHERE {week} AND source = 'home') AS from_home,
        (SELECT count(*) FROM contact_enquiries WHERE {week} AND source = 'contact') AS from_contact,
        (SELECT count(*) FROM contact_enquiries WHERE {week} AND submitted_via = 'whatsapp') AS via_wa_button,
        (SELECT count(*) FROM contact_enquiries WHERE {week} AND status <> 'new') AS contacted,
        (SELECT count(*) FROM contact_enquiries WHERE status = 'won' AND (updated_at AT TIME ZONE 'Asia/Kolkata')::date
            BETWEEN {IST_TODAY} - 7 AND {IST_TODAY} - 1) AS won,
        (SELECT count(*) FROM contact_enquiries WHERE status = 'won') AS won_all,
        (SELECT count(*) FROM contact_enquiries WHERE status IN ('won', 'closed')) AS decided_all,
        (SELECT count(*) FROM wa_contacts WHERE {week} AND wa_id <> %s) AS new_chats,
        (SELECT count(*) FROM wa_messages WHERE {week} AND direction = 'in' AND wa_id <> %s) AS messages_in,
        (SELECT count(*) FROM wa_bookings WHERE call_date BETWEEN {IST_TODAY} - 7 AND {IST_TODAY} - 1) AS calls,
        (SELECT count(*) FROM wa_bookings WHERE call_date BETWEEN {IST_TODAY} - 7 AND {IST_TODAY} - 1 AND status = 'done') AS calls_done,
        (SELECT count(*) FROM support_tickets WHERE {week}) AS tickets_new,
        (SELECT count(*) FROM support_tickets WHERE (resolved_at AT TIME ZONE 'Asia/Kolkata')::date
            BETWEEN {IST_TODAY} - 7 AND {IST_TODAY} - 1) AS tickets_resolved,
        (SELECT count(*) FROM client_reviews WHERE {week}) AS reviews""",
        (config.ADMIN_WA_NUMBER, config.ADMIN_WA_NUMBER))
    r['services'] = rows(f"""SELECT s AS name, count(*) AS n FROM contact_enquiries, jsonb_array_elements_text(services) s
                             WHERE {week} GROUP BY s ORDER BY n DESC LIMIT 5""")
    busy = one(f"""SELECT extract(hour FROM created_at AT TIME ZONE 'Asia/Kolkata')::int AS h, count(*) AS n
                   FROM wa_messages WHERE {week} AND direction = 'in' AND wa_id <> %s
                   GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", (config.ADMIN_WA_NUMBER,))
    r['busiest_hour'] = busy['h'] if busy else None
    day = one(f"""SELECT to_char(created_at AT TIME ZONE 'Asia/Kolkata', 'FMDay') AS d, count(*) AS n
                  FROM wa_messages WHERE {week} AND direction = 'in' AND wa_id <> %s
                  GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", (config.ADMIN_WA_NUMBER,))
    r['busiest_day'] = day['d'] if day else None
    return r


# ---- admin commands (N) ----------------------------------------------------
def new_enquiries(limit=10):
    return rows("SELECT * FROM contact_enquiries WHERE status = 'new' ORDER BY created_at DESC LIMIT %s", (limit,))


def calls_on(day):
    return rows("""SELECT * FROM wa_bookings WHERE status = 'booked' AND call_date = %s ORDER BY call_time""", (day,))


def open_tickets(limit=15):
    return rows("""SELECT t.*, p.title AS project_title FROM support_tickets t
                   LEFT JOIN client_projects p ON p.id = t.project_id
                   WHERE t.status NOT IN ('resolved', 'closed')
                   ORDER BY (t.priority = 'urgent') DESC, t.created_at LIMIT %s""", (limit,))


def upcoming_renewals(days=30):
    return rows(f"""SELECT r.*, p.client_name FROM client_renewals r JOIN client_projects p ON p.id = r.project_id
                    WHERE r.status = 'active' AND r.expiry_date <= {IST_TODAY} + %s ORDER BY r.expiry_date""", (days,))


def pending_unanswered(limit=10):
    return rows("""SELECT * FROM bot_unanswered WHERE status = 'pending' ORDER BY created_at DESC LIMIT %s""", (limit,))
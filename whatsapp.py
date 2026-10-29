"""
WhatsApp Cloud API (Meta Graph API): sending messages, typing indicator and media.

Every message the bot sends goes through here and is saved in wa_messages,
so the admin dashboard shows the full conversation.
"""
import logging

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
import db

log = logging.getLogger('bot.wa')

_session = requests.Session()
_session.mount('https://', HTTPAdapter(max_retries=Retry(total=2, connect=2, read=0, backoff_factor=0.5,
                                                          allowed_methods=None, status_forcelist=())))
TIMEOUT = 20

# WhatsApp limits (characters)
LIMIT = {'button': 20, 'row': 24, 'row_desc': 72, 'list_button': 20, 'section': 24,
         'header': 60, 'footer': 60, 'body': 1024, 'text': 4096, 'caption': 1024}


def _url(path):
    return f'{config.GRAPH_BASE}/{config.GRAPH_VERSION}/{path}'


def _headers():
    return {'Authorization': f'Bearer {config.META_ACCESS_TOKEN}'}


def clip(text, limit):
    text = str(text or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def error_text(response):
    try:
        err = response.json().get('error', {})
    except ValueError:
        return f'HTTP {response.status_code}: {response.text[:200]}'
    details = (err.get('error_data') or {}).get('details', '')
    msg = f"{err.get('code', response.status_code)}: {err.get('message', 'Unknown error')}"
    return f'{msg} ({details})' if details and details not in msg else msg


def _post(payload):
    """Send one message. Returns (wamid, error)."""
    if not config.META_ACCESS_TOKEN or not config.PHONE_NUMBER_ID:
        return None, 'META_ACCESS_TOKEN / PHONE_NUMBER_ID not set'
    try:
        r = _session.post(_url(f'{config.PHONE_NUMBER_ID}/messages'), headers=_headers(),
                          json={'messaging_product': 'whatsapp', 'recipient_type': 'individual', **payload},
                          timeout=TIMEOUT)
    except requests.RequestException as e:
        return None, f'Network error: {e}'
    if r.status_code >= 400:
        return None, error_text(r)
    try:
        return r.json()['messages'][0]['id'], ''
    except (ValueError, KeyError, IndexError):
        return None, f'Unexpected reply from WhatsApp: {r.text[:200]}'


def _send(to, payload, log_type, log_body, sender='bot', record=True):
    wamid, error = _post({'to': to, **payload})
    if error:
        log.warning('Send to %s failed: %s', to, error)
    if record:
        try:
            db.save_outbound(to, sender, log_type, log_body, wamid=wamid,
                             status='failed' if error else 'sent', error=error)
        except Exception:
            log.exception('Could not save outgoing message')
    return wamid, error


# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------
def send_text(to, text, sender='bot', record=True):
    text = clip(text, LIMIT['text'])
    return _send(to, {'type': 'text', 'text': {'body': text, 'preview_url': 'http' in text}},
                 'text', text, sender, record)


def send_buttons(to, body, buttons, header='', footer='', sender='bot'):
    """buttons: up to 3 (id, title) pairs."""
    body = clip(body, LIMIT['body'])
    interactive = {
        'type': 'button',
        'body': {'text': body},
        'action': {'buttons': [{'type': 'reply', 'reply': {'id': bid[:256], 'title': clip(title, LIMIT['button'])}}
                               for bid, title in buttons[:3]]},
    }
    if header:
        interactive['header'] = {'type': 'text', 'text': clip(header, LIMIT['header'])}
    if footer:
        interactive['footer'] = {'text': clip(footer, LIMIT['footer'])}
    shown = ' · '.join(clip(t, LIMIT['button']) for _, t in buttons[:3])
    return _send(to, {'type': 'interactive', 'interactive': interactive}, 'interactive',
                 f'{body}\n[{shown}]', sender)


def send_list(to, body, button, rows, header='', footer='', section='', sender='bot'):
    """rows: up to 10 (id, title, description) tuples."""
    body = clip(body, LIMIT['body'])
    rows = rows[:10]
    interactive = {
        'type': 'list',
        'body': {'text': body},
        'action': {
            'button': clip(button, LIMIT['list_button']),
            'sections': [{
                'title': clip(section or button, LIMIT['section']),
                'rows': [{'id': rid[:200], 'title': clip(title, LIMIT['row']),
                          **({'description': clip(desc, LIMIT['row_desc'])} if desc else {})}
                         for rid, title, desc in rows],
            }],
        },
    }
    if header:
        interactive['header'] = {'type': 'text', 'text': clip(header, LIMIT['header'])}
    if footer:
        interactive['footer'] = {'text': clip(footer, LIMIT['footer'])}
    shown = '\n'.join(f'• {clip(t, LIMIT["row"])}' for _, t, _ in rows)
    return _send(to, {'type': 'interactive', 'interactive': interactive}, 'interactive',
                 f'{body}\n{shown}', sender)


def send_image(to, link, caption='', sender='bot'):
    caption = clip(caption, LIMIT['caption'])
    return _send(to, {'type': 'image', 'image': {'link': link, **({'caption': caption} if caption else {})}},
                 'image', caption or '[image]', sender)


def send_document(to, media_id, filename, caption='', sender='system'):
    caption = clip(caption, LIMIT['caption'])
    doc = {'id': media_id, 'filename': clip(filename or 'file', 200)}
    if caption:
        doc['caption'] = caption
    return _send(to, {'type': 'document', 'document': doc}, 'document', caption or f'[file: {filename}]', sender)


def template_param(value):
    """Template values may not contain new lines, tabs or more than 4 spaces in a row."""
    text = ' '.join(str(value if value not in (None, '') else '-').split())
    return clip(text, 300) or '-'


def send_template(to, name, language, body_params=(), header_image='', quick_reply_payloads=(),
                  preview='', sender='system', record=True, header_document=None):
    components = []
    if header_image:
        components.append({'type': 'header', 'parameters': [{'type': 'image', 'image': {'link': header_image}}]})
    if header_document:                           # {'id': uploaded media id, 'filename': 'quote.pdf'}
        components.append({'type': 'header', 'parameters': [{'type': 'document', 'document': header_document}]})
    if body_params:
        components.append({'type': 'body', 'parameters': [{'type': 'text', 'text': template_param(p)}
                                                          for p in body_params]})
    for index, payload in enumerate(quick_reply_payloads):
        components.append({'type': 'button', 'sub_type': 'quick_reply', 'index': str(index),
                           'parameters': [{'type': 'payload', 'payload': payload}]})
    template = {'name': name, 'language': {'code': language}}
    if components:
        template['components'] = components
    if quick_reply_payloads:
        # if the approved template has no / fewer quick-reply buttons, send it again without our button ids
        wamid, error = _send(to, {'type': 'template', 'template': template}, 'template',
                             preview or f'[Template: {name}]', sender, record=False)
        if not error or 'button' not in error.lower():
            if record:
                _record(to, sender, preview or f'[Template: {name}]', wamid, error)
            return wamid, error
        template['components'] = [c for c in components if c['type'] != 'button']
        if not template['components']:
            template.pop('components')
    return _send(to, {'type': 'template', 'template': template}, 'template',
                 preview or f'[Template: {name}]', sender, record)


def _record(to, sender, body, wamid, error):
    try:
        db.save_outbound(to, sender, 'template', body, wamid=wamid, status='failed' if error else 'sent', error=error)
    except Exception:
        log.exception('Could not save outgoing message')


def mark_read_and_typing(message_id):
    """Blue ticks + "typing…" on the customer's phone while the bot works on the reply."""
    if not message_id or not config.META_ACCESS_TOKEN:
        return
    try:
        _session.post(_url(f'{config.PHONE_NUMBER_ID}/messages'), headers=_headers(), timeout=10,
                      json={'messaging_product': 'whatsapp', 'status': 'read', 'message_id': message_id,
                            'typing_indicator': {'type': 'text'}})
    except requests.RequestException as e:
        log.info('Typing indicator not shown: %s', e)


# ---------------------------------------------------------------------------
# Media (images, voice notes, documents the customer sends)
# ---------------------------------------------------------------------------
def download_media(media_id, max_bytes=16 * 1024 * 1024):
    """Returns (bytes, mime_type) or (None, '') when it cannot be downloaded."""
    try:
        info = _session.get(_url(media_id), headers=_headers(), timeout=TIMEOUT)
        if info.status_code >= 400:
            log.warning('Media %s info failed: %s', media_id, error_text(info))
            return None, ''
        meta = info.json()
        if int(meta.get('file_size') or 0) > max_bytes:
            return None, meta.get('mime_type', '')
        file = _session.get(meta['url'], headers=_headers(), timeout=60)
        if file.status_code >= 400 or len(file.content) > max_bytes:
            return None, meta.get('mime_type', '')
        return file.content, meta.get('mime_type', '') or file.headers.get('Content-Type', '')
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning('Media %s download failed: %s', media_id, e)
        return None, ''


def upload_media(data, mime, filename='file'):
    """Upload a file to WhatsApp so it can be sent on. Returns (media_id, error)."""
    if not config.META_ACCESS_TOKEN or not config.PHONE_NUMBER_ID:
        return None, 'META_ACCESS_TOKEN / PHONE_NUMBER_ID not set'
    mime = (mime or 'application/octet-stream').split(';')[0].strip()
    try:
        r = _session.post(_url(f'{config.PHONE_NUMBER_ID}/media'), headers=_headers(), timeout=90,
                          data={'messaging_product': 'whatsapp', 'type': mime},
                          files={'file': (filename or 'file', data, mime)})
    except requests.RequestException as e:
        return None, f'Network error: {e}'
    if r.status_code >= 400:
        return None, error_text(r)
    try:
        return r.json()['id'], ''
    except (ValueError, KeyError):
        return None, f'Unexpected reply from WhatsApp: {r.text[:200]}'
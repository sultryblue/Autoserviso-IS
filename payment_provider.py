"""Local payment simulation only: no card input, network calls or real money.

The adapter produces authenticated result messages. main.process_payment_result
validates and applies those messages for both the demo and technical HTTP route.
The random process secret is never returned to browsers. After restart the mock
can produce a fresh signed result for an operation stored in the database.
"""
import hashlib
import hmac
import json
import secrets

_SECRET = secrets.token_bytes(32)
_FIELDS = {'operation_id', 'order_id', 'amount_cents', 'currency', 'status'}
STATUSES = ('Laukia', 'Sėkmingas', 'Nesėkmingas')

def new_operation():
    return 'mock_' + secrets.token_hex(16)

def _signature(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return hmac.new(_SECRET, encoded, hashlib.sha256).hexdigest()

def result(payment, status):
    if status not in STATUSES:
        raise ValueError('Nežinoma mokėjimo imitacijos būsena.')
    payload = {k: payment[k] for k in ('operation_id', 'order_id', 'amount_cents')}
    payload.update(currency='EUR', status=status)
    return {**payload, 'signature': _signature(payload)}

def verified(message):
    if set(message) != _FIELDS | {'signature'} or not isinstance(message['signature'], str):
        return False
    payload = {k: message[k] for k in _FIELDS}
    return hmac.compare_digest(message['signature'], _signature(payload))

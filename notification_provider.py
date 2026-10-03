"""SMS / email imitation. No network access and no real messages.

A stable request key models provider deduplication. Modes are demonstration
controls only; they reset to success when the local server restarts.
"""
import hashlib
import json
import threading

_LOCK = threading.Lock()
_MODE = 'success'
_ACCEPTED = {}
MODES = ('success', 'failure', 'timeout')

def configure(mode):
    global _MODE
    if mode not in MODES:
        raise ValueError('Nežinomas pranešimų imitacijos režimas.')
    with _LOCK: _MODE = mode

def mode():
    with _LOCK: return _MODE

def send(*, request_key, channel, recipient, content):
    fingerprint=hashlib.sha256(json.dumps([channel,recipient,content],ensure_ascii=False).encode()).hexdigest()
    with _LOCK:
        previous=_ACCEPTED.get(request_key)
        if previous:
            if previous[0]!=fingerprint:
                return {'result':'Siuntimo klaida','provider_id':None,'error_code':'MOCK_KEY_CONFLICT'}
            return {'result':'Perduotas tiekėjui','provider_id':previous[1],'error_code':''}
        if _MODE=='timeout': raise TimeoutError('Imituojamas laiko viršijimas.')
        if _MODE=='failure':
            return {'result':'Siuntimo klaida','provider_id':None,'error_code':'MOCK_UNAVAILABLE'}
        provider_id='mock_msg_'+hashlib.sha256(request_key.encode()).hexdigest()[:24]
        _ACCEPTED[request_key]=(fingerprint,provider_id)
        return {'result':'Perduotas tiekėjui','provider_id':provider_id,'error_code':''}

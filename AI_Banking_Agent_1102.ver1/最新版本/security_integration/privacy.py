"""Pseudonymous ownership keys for new logs; do not log the session credential."""
import hashlib

def session_tag(sid):
    return 'session-sha256:'+hashlib.sha256(sid.encode('utf-8')).hexdigest()

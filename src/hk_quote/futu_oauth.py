"""Loopback OAuth for read-only Futu HTTP quotes."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
from tempfile import NamedTemporaryFile
import threading
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

BASE = 'https://webapi.futunn.com'
lock = threading.Lock()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = build_opener(NoRedirect())


def post(endpoint, fields, registration=False):
    content_type = 'application/json' if registration else 'application/x-www-form-urlencoded'
    body = json.dumps(fields) if registration else urlencode(fields)
    request = Request(BASE + endpoint, data=body.encode(), headers={'Content-Type': content_type})
    try:
        with opener.open(request, timeout=10) as response:
            return json.load(response)
    except (URLError, OSError, ValueError):
        raise ValueError('富途授权请求失败，请稍后重新授权。') from None


def token_path(database):
    return Path(database).parent / 'futu-oauth.json'


def save_token(database, client, response):
    try:
        token = response['access_token']
        refresh = response['refresh_token']
        expiry = int(response['expires_in'])
        if not token or not refresh or expiry <= 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError('富途未返回可续期的行情令牌。') from None
    path = token_path(database)
    with NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(dict(client_id=client, access_token=token, refresh_token=refresh,
                           expires_at=time.time()+expiry), output)
            output.flush()
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
    return token


def managed_token(database):
    path = token_path(database)
    with lock:
        try:
            if path.stat().st_mode & 0o077:
                raise ValueError('富途授权文件需设为仅本人可读写。')
            saved = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError):
            raise ValueError('无法读取本地富途授权，请重新授权。') from None
        if saved['expires_at'] > time.time() + 60:
            return saved['access_token']
        response = post('/oauth2/token', dict(grant_type='refresh_token',
                        client_id=saved['client_id'], refresh_token=saved['refresh_token']))
        response.setdefault('refresh_token', saved['refresh_token'])
        return save_token(database, saved['client_id'], response)


class LocalAuthorization:
    def __init__(self, database, port):
        self.database = database
        self.redirect = f'http://localhost:{port}/auth/futu/callback'
        self.pending = None
        self.client = None

    def start(self):
        with lock:
            if not self.client:
                response = post('/oauth2/register', dict(redirect_uris=[self.redirect],
                    token_endpoint_auth_method='none', grant_types=['authorization_code','refresh_token'],
                    response_types=['code'], client_name='HK Quote Dashboard', scope='quote:read'), registration=True)
                self.client = response.get('client_id')
                if not self.client:
                    raise ValueError('富途未返回 OAuth 应用编号。')
            state = secrets.token_urlsafe(32)
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            self.pending = state, verifier, time.monotonic()+600
            return BASE + '/oauth2/authorize/confirm?' + urlencode(dict(client_id=self.client,
                redirect_uri=self.redirect, response_type='code', state=state, scope='quote:read',
                code_challenge=challenge, code_challenge_method='S256'))

    def finish(self, state, code):
        with lock:
            pending = self.pending
            if not pending or pending[2] < time.monotonic() or not state.isascii() or not secrets.compare_digest(pending[0], state):
                raise ValueError('富途授权已过期或回调无效，请重新开始。')
            self.pending = None
            if not code:
                raise ValueError('富途未授予行情读取权限。')
            response = post('/oauth2/token', dict(grant_type='authorization_code', code=code,
                            client_id=self.client, redirect_uri=self.redirect, code_verifier=pending[1]))
            save_token(self.database, self.client, response)

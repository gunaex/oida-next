import hashlib
import importlib.util
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from oida_next.control import create_app
from oida_next.identity_bridge import IdentityConfig


def exchange_class():
    path = Path(__file__).resolve().parents[2] / 'ecosystem/OIODA/services/account-again/account_again/oida_owner.py'
    spec = importlib.util.spec_from_file_location('owner_exchange', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.OwnerExchange


def test_private_exchange_rejects_identity_selection_and_wrong_capability():
    calls = []
    exchange = exchange_class()(FastAPI(), hashlib.sha256(b'private-capability').hexdigest(),
                                'fixed-owner', lambda owner: calls.append(owner) or {'ok': True})
    c = TestClient(exchange)
    route = '/api/v1/oida/owner-token'
    assert c.post(route).status_code == 401
    headers = {'Authorization': 'Bearer private-capability'}
    assert c.post(route, headers=headers, json={'subject': 'another-user'}).status_code == 400
    assert c.post(route + '?subject=another-user', headers=headers).status_code == 400
    assert c.get(route, headers=headers).status_code == 405
    assert calls == []
    r = c.post(route, headers=headers)
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'no-store'
    assert calls == ['fixed-owner']


def test_owner_login_automatically_connects_and_logout_revokes(tmp_path, monkeypatch):
    calls = []
    def remote(request):
        calls.append(request)
        assert request.url.path == '/api/v1/oida/owner-token'
        assert request.headers['Authorization'] == 'Bearer private-capability'
        assert request.content == b''
        return httpx.Response(200, json={'email': 'owner@example.com', 'accessToken': 'private-token',
                                        'tokenType': 'Bearer', 'expiresIn': 300,
                                        'mustChangePassword': False})
    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda **kw: httpx.MockTransport(remote))
    app = create_app(tmp_path / 'control.db', identity_config=IdentityConfig(
        'https://identity.test', 'https://pm.test', 'https://qa.test',
        account_socket='/private/account.sock', owner_exchange_token=SecretStr('private-capability')))
    app.state.store.initialize_password('owner-password-long-enough')
    c = TestClient(app)
    assert c.get('/api/v1/identity').status_code == 401
    assert calls == []
    token = c.post('/api/v1/login', json={'password': 'owner-password-long-enough'}).json()['access_token']
    c.headers['Authorization'] = 'Bearer ' + token
    r = c.get('/api/v1/identity')
    assert r.status_code == 200 and r.json()['connected'] and r.json()['sso']
    assert 'private-token' not in r.text and 'private-capability' not in r.text
    assert c.get('/api/v1/identity').json()['connected']
    assert len(calls) == 1
    assert c.post('/api/v1/identity', json={'email': 'attacker@example.com', 'password': 'x'}).status_code == 409
    assert c.post('/api/v1/logout').status_code == 200
    assert c.get('/api/v1/identity').status_code == 401
    assert len(calls) == 1

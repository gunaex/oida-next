import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../deployment/pages-worker.js', import.meta.url), 'utf8');
const {moduleRequest, unifiedModuleRequest, default: worker} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const host = 'https://oida-next.kanphong.com';

test('unified gateway forwards only owner cookie to fixed OIDA service', async () => {
  const response = await unifiedModuleRequest(new Request(host + '/modules/qa/api/projects?archived=true', {
    headers: {Cookie: '__Host-oida_session=owner; access_token=qa; __Secure-oida-pm-access_token=pm',
      Authorization: 'Bearer attacker', 'X-Actor': 'administrator'},
  }), 'qa', '/api/projects', async request => {
    assert.equal(request.url, 'https://api-oida-next.kanphong.com/api/v1/modules/qa/proxy/projects?archived=true');
    assert.equal(request.headers.get('cookie'), '__Host-oida_session=owner');
    assert.equal(request.headers.get('authorization'), null);
    assert.equal(request.headers.get('x-actor'), null);
    return new Response('[]', {headers: {'Set-Cookie': 'secret=not-for-browser'}});
  });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('set-cookie'), null);
});

test('unified gateway denies missing owner session and cross-origin writes', async () => {
  const send = () => assert.fail('must not forward');
  assert.equal((await unifiedModuleRequest(new Request(host + '/modules/qa/api/projects'), 'qa', '/api/projects', send)).status, 401);
  assert.equal((await unifiedModuleRequest(new Request(host + '/modules/qa/api/projects', {
    method: 'POST', headers: {Cookie: '__Host-oida_session=owner', Origin: 'https://evil.test'},
  }), 'qa', '/api/projects', send)).status, 403);
});

test('module gateway isolates credentials and response cookies', async () => {
  const request = new Request(host + '/modules/qa/api/projects', {headers: {
    Cookie: '__Secure-oida-qa-access_token=qa-value; __Secure-oida-pm-access_token=pm-value; access_token=other',
    Authorization: 'Bearer oida-session',
  }});
  const response = await moduleRequest(request, 'qa', '/api/projects', async upstream => {
    assert.equal(upstream.url, 'https://api-qaagain.kanphong.com/api/projects');
    assert.equal(upstream.headers.get('cookie'), 'access_token=qa-value');
    assert.equal(upstream.headers.get('authorization'), null);
    const headers = new Headers({'Content-Type': 'application/json'});
    headers.append('Set-Cookie', 'access_token=fresh; Domain=kanphong.com; Path=/; HttpOnly; Max-Age=1800');
    headers.append('Set-Cookie', 'refresh_token=refresh; Path=/api/auth; Max-Age=604800');
    headers.append('Set-Cookie', 'unrelated=blocked');
    return new Response('[]', {headers});
  });
  assert.equal(response.status, 200);
  const cookies = response.headers.getSetCookie();
  assert.equal(cookies.length, 2);
  for (const cookie of cookies) {
    assert.match(cookie, /^__Secure-oida-qa-/);
    assert.match(cookie, /Path=\/modules\/qa\/api/);
    assert.match(cookie, /Secure; HttpOnly; SameSite=Strict/);
    assert.doesNotMatch(cookie, /Domain=/);
  }
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

test('cross-origin mutations never reach a module', async () => {
  for (const origin of ['https://attacker.test', null]) {
    const headers = origin ? {Origin: origin} : {};
    const response = await moduleRequest(new Request(host + '/modules/qa/api/projects', {
      method: 'POST', headers,
    }), 'qa', '/api/projects', () => assert.fail('must not forward'));
    assert.equal(response.status, 403);
  }
});

test('same-origin POST preserves payload and Origin', async () => {
  const response = await moduleRequest(new Request(host + '/modules/pm/api/projects', {
    method: 'POST', headers: {Origin: host, 'Content-Type': 'application/json'}, body: '{"name":"test"}',
  }), 'pm', '/api/projects', async request => {
    assert.equal(request.headers.get('origin'), host);
    assert.equal(await request.text(), '{"name":"test"}');
    return new Response('{}');
  });
  assert.equal(response.status, 200);
});

test('untrusted paths, modules and redirects fail closed', async () => {
  const request = new Request(host + '/modules/qa/api/projects');
  for (const [module, path] of [['unknown', '/api/projects'], ['qa', '/api/%2fsecret'], ['qa', '/api/../secret'], ['qa', '//evil.test']]) {
    assert.equal((await moduleRequest(request, module, path, () => assert.fail())).status, 400);
  }
  const redirect = await moduleRequest(request, 'qa', '/api/projects', async () => new Response(null, {
    status: 302, headers: {Location: 'https://other.test', 'Set-Cookie': 'access_token=secret'},
  }));
  assert.equal(redirect.status, 502);
  assert.equal(redirect.headers.get('set-cookie'), null);
});

test('logout expiry remains scoped to its module', async () => {
  const request = new Request(host + '/modules/qa/api/auth/logout', {method: 'POST', headers: {Origin: host}});
  const response = await moduleRequest(request, 'qa', '/api/auth/logout', async () => new Response('{}', {
    headers: {'Set-Cookie': 'access_token=""; Max-Age=0; Path=/'},
  }));
  assert.match(response.headers.get('set-cookie'), /Max-Age=0/);
  assert.match(response.headers.get('set-cookie'), /__Secure-oida-qa-access_token/);
});

test('module page deep links resolve to the correct bundle', async () => {
  for (const path of ['/qa/login', '/pm/projects/alpha', '/qa/', '/pm', '/documents/', '/infra/']) {
    let requested;
    const response = await worker.fetch(new Request(host + path), {ASSETS: {fetch: async request => {
      requested = new URL(request.url).pathname;
      return new Response('module html');
    }}});
    assert.equal(response.status, 200);
    assert.equal(requested, `/${path.split('/')[1]}/index.html`);
  }
});

test('every public response receives browser security headers', async () => {
  const response = await worker.fetch(new Request(host + '/'), {
    ASSETS: {fetch: async () => new Response('home')},
  });
  assert.equal(response.headers.get('strict-transport-security'), 'max-age=31536000; includeSubDomains');
  assert.equal(response.headers.get('x-frame-options'), 'DENY');
  assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
  assert.equal(response.headers.get('permissions-policy'), 'camera=(), microphone=(), geolocation=()');
  assert.match(response.headers.get('content-security-policy'), /frame-ancestors 'none'/);
});

test('module gateway remains disabled without explicit deployment setting', async () => {
  const response = await worker.fetch(new Request(host + '/modules/qa/api/projects'), {});
  assert.equal(response.status, 503);
});

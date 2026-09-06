const API_ORIGIN = "https://api-oida-next.kanphong.com";
const MODULE_ORIGINS = {
  pm: "https://api-pmagain.kanphong.com",
  qa: "https://api-qaagain.kanphong.com",
};

// Unified mode sends only the owner session to OIDA; the server supplies the
// module identity after authorization. Never send a browser-selected identity.
export async function unifiedModuleRequest(request, module, apiPath, send = fetch) {
  const url = new URL(request.url);
  if (!["pm", "qa", "document", "infra"].includes(module) || !apiPath.startsWith("/api/") || /[%\\]/.test(apiPath) || apiPath.includes("..")) {
    return Response.json({detail: "Invalid module route"}, {status: 400});
  }
  if (!["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"].includes(request.method)) return new Response(null, {status: 405});
  if (!["GET", "HEAD"].includes(request.method) && request.headers.get("Origin") !== url.origin) {
    return Response.json({detail: "Same-origin request required"}, {status: 403});
  }
  const headers = new Headers();
  for (const name of ["accept", "content-type", "origin", "range", "if-none-match"]) {
    if (request.headers.has(name)) headers.set(name, request.headers.get(name));
  }
  const session = (request.headers.get("cookie") || "").split(";").map(x => x.trim())
    .filter(x => x.startsWith("__Host-oida_session="));
  if (session.length !== 1) return Response.json({detail: "Unlock OIDA first"}, {status: 401});
  headers.set("cookie", session[0]);
  try {
    const upstream = await send(new Request(`${API_ORIGIN}/api/v1/modules/${module}/proxy/${apiPath.slice(5)}${url.search}`, {
      method: request.method, headers, redirect: "manual", duplex: "half",
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    }));
    if (upstream.status >= 300 && upstream.status < 400 && upstream.status !== 304) {
      return Response.json({detail: "Unexpected gateway redirect"}, {status: 502});
    }
    const output = new Headers(upstream.headers);
    output.delete("set-cookie"); output.delete("location");
    output.set("Cache-Control", "no-store");
    return new Response(upstream.body, {status: upstream.status, headers: output});
  } catch {
    return Response.json({detail: "Module gateway unavailable"}, {status: 502});
  }
}

// Transitional same-origin gateway. Each module retains its own session until
// shared identity is verified. Never give one module another module's cookie.
export async function moduleRequest(request, module, apiPath, send = fetch) {
  const origin = Object.hasOwn(MODULE_ORIGINS, module) ? MODULE_ORIGINS[module] : null;
  if (!origin || !apiPath.startsWith("/api/") || /[%\\]/.test(apiPath) || apiPath.includes("..")) {
    return Response.json({detail: "Invalid module route"}, {status: 400});
  }
  const url = new URL(request.url);
  if (!["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"].includes(request.method)) {
    return new Response(null, {status: 405});
  }
  if (!["GET", "HEAD"].includes(request.method) && request.headers.get("Origin") !== url.origin) {
    return Response.json({detail: "Same-origin request required"}, {status: 403});
  }
  const headers = new Headers();
  for (const name of ["accept", "content-type", "origin", "if-none-match", "range"]) {
    if (request.headers.has(name)) headers.set(name, request.headers.get(name));
  }
  const prefix = `__Secure-oida-${module}-`;
  const cookies = [];
  for (const item of (request.headers.get("cookie") || "").split(";")) {
    const trimmed = item.trim();
    const split = trimmed.indexOf("=");
    const name = trimmed.slice(0, split);
    if ([prefix + "access_token", prefix + "refresh_token"].includes(name)) {
      cookies.push(name.slice(prefix.length) + trimmed.slice(split));
    }
  }
  if (cookies.length) headers.set("cookie", cookies.join("; "));
  let upstream;
  try {
    upstream = await send(new Request(origin + apiPath + url.search, {
      method: request.method, headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      redirect: "manual", duplex: "half",
    }));
  } catch {
    return Response.json({detail: "Module unavailable"}, {status: 502});
  }
  // No module can navigate or set cookies outside its namespace.
  if (upstream.status >= 300 && upstream.status < 400 && upstream.status !== 304) {
    return Response.json({detail: "Unexpected module redirect"}, {status: 502});
  }
  const output = new Headers();
  for (const name of ["content-type", "content-disposition", "etag", "content-range", "accept-ranges"]) {
    if (upstream.headers.has(name)) output.set(name, upstream.headers.get(name));
  }
  output.set("Cache-Control", "no-store");
  output.set("X-Content-Type-Options", "nosniff");
  const setCookies = typeof upstream.headers.getSetCookie === "function"
    ? upstream.headers.getSetCookie() : upstream.headers.getAll("Set-Cookie");
  for (const cookie of setCookies) {
    const [pair, ...attributes] = cookie.split(";");
    const split = pair.indexOf("=");
    const name = pair.slice(0, split).trim();
    if (!["access_token", "refresh_token"].includes(name)) continue;
    const expiry = attributes.filter(a => /^\s*(max-age|expires)=/i.test(a));
    output.append("Set-Cookie", `${prefix}${name}${pair.slice(split)}; Path=/modules/${module}/api; Secure; HttpOnly; SameSite=Strict${expiry.length ? ";" + expiry.join(";") : ""}`);
  }
  return new Response(upstream.body, {status: upstream.status, headers: output});
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const moduleRoute = url.pathname.match(/^\/modules\/(pm|qa|document|infra)(\/api\/.*)$/);
    if (moduleRoute) {
      if (env.ENABLE_UNIFIED_MODULES === "true") return unifiedModuleRequest(request, moduleRoute[1], moduleRoute[2]);
      if (env.ENABLE_LEGACY_MODULES !== "true") return Response.json({detail: "Module gateway not enabled"}, {status: 503});
      return moduleRequest(request, moduleRoute[1], moduleRoute[2]);
    }
    if (url.pathname.startsWith("/modules/")) return new Response(null, {status: 404});
    const modulePage = url.pathname.match(/^\/(pm|qa|documents|infra)(\/.*)?$/);
    if (modulePage && !url.pathname.split("/").pop().includes(".")) {
      if (request.method !== "GET" && request.method !== "HEAD") return new Response(null, {status: 405});
      const asset = new URL(`/${modulePage[1]}/index.html`, url.origin);
      return env.ASSETS.fetch(new Request(asset, {method: request.method, headers: request.headers}));
    }
    if (url.pathname.startsWith("/api/") || ["/health", "/ready"].includes(url.pathname)) {
      // Bootstrap remains localhost-only even when a Pages origin is authenticated later.
      if (url.pathname === "/api/v1/setup") return Response.json({detail:"Initial setup is available only on the Ubuntu machine."},{status:403});
      const upstream = new URL(url.pathname + url.search, API_ORIGIN);
      return fetch(new Request(upstream, {method:request.method, headers:request.headers,
        body:["GET","HEAD"].includes(request.method)?undefined:request.body, redirect:"manual"}));
    }
    return env.ASSETS.fetch(request);
  }
};

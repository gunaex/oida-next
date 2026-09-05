const API_ORIGIN = "https://api-oida-next.kanphong.com";
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
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

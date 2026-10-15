// Cognito hosted UI login: OAuth 2.0 authorization code flow with PKCE (public client, no secret).
// Tokens live in sessionStorage only (cleared when the tab closes).
(function () {
  const C = window.STOCK_CONFIG;
  const store = {
    get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* storage blocked */ } },
    del(k) { try { sessionStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };

  function b64url(bytes) {
    let s = "";
    bytes.forEach((b) => (s += String.fromCharCode(b)));
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function randomString(n) {
    const a = new Uint8Array(n);
    crypto.getRandomValues(a);
    return b64url(a);
  }
  async function sha256(s) {
    return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  }
  function decodeJwt(t) {
    const p = t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(p))));
  }

  async function login() {
    const verifier = randomString(48);
    const state = randomString(16);
    store.set("pkce_verifier", verifier);
    store.set("oauth_state", state);
    const challenge = b64url(await sha256(verifier));
    const q = new URLSearchParams({
      client_id: C.clientId, response_type: "code", scope: "openid email",
      redirect_uri: C.redirectUri, state, code_challenge: challenge, code_challenge_method: "S256",
    });
    window.location.assign(`${C.cognitoDomain}/oauth2/authorize?${q}`);
  }

  async function handleCallback() {
    const q = new URLSearchParams(window.location.search);
    const code = q.get("code");
    if (!code) return false;
    const state = q.get("state");
    const verifier = store.get("pkce_verifier");
    history.replaceState({}, "", C.redirectUri);
    if (!verifier || state !== store.get("oauth_state")) throw new Error("Login state mismatch. Please sign in again.");
    store.del("pkce_verifier");
    store.del("oauth_state");
    const r = await fetch(`${C.cognitoDomain}/oauth2/token`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "authorization_code", client_id: C.clientId, code,
        redirect_uri: C.redirectUri, code_verifier: verifier,
      }),
    });
    if (!r.ok) throw new Error(`Token exchange failed (${r.status})`);
    const tok = await r.json();
    store.set("id_token", tok.id_token);
    return true;
  }

  function token() {
    const t = store.get("id_token");
    if (!t) return null;
    try {
      if (decodeJwt(t).exp * 1000 < Date.now() + 30000) { store.del("id_token"); return null; }
    } catch (e) { store.del("id_token"); return null; }
    return t;
  }

  function user() {
    const t = token();
    return t ? decodeJwt(t).email || decodeJwt(t)["cognito:username"] : null;
  }

  function logout() {
    store.del("id_token");
    const q = new URLSearchParams({ client_id: C.clientId, logout_uri: C.redirectUri });
    window.location.assign(`${C.cognitoDomain}/logout?${q}`);
  }

  window.StockAuth = { login, logout, handleCallback, token, user };
})();

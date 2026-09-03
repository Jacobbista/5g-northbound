# Authentication

Every service authenticates against the same Keycloak realm (`5g-testbed`). The
browser apps reach that realm through **two patterns**, chosen per app according
to what the app does. Both are standard OpenID Connect. They differ in where the
token lives.

## The two patterns

### 1. In-browser OIDC (`keycloak-js`) - location-app

The app runs the OIDC Authorization Code + PKCE flow itself, in the browser.
`keycloak-js` redirects to Keycloak, receives the token, and holds it in
JavaScript memory. The app then attaches it as a `Bearer` header on every REST
call to the CAMARA gateway, and in the `Sec-WebSocket-Protocol` header when it
opens the live positions WebSocket (browsers cannot set an Authorization header
on a WS handshake, and a bearer token must not go in the URL).

- The frontend **has** the access token and its claims (roles, org, expiry).
- Keycloak client: **public**, PKCE (`S256`), no client secret.

### 2. Proxy-gated / BFF (`oauth2-proxy`) - placement-editor

A reverse proxy (`oauth2-proxy`) sits in front of the app. It runs the OIDC flow
on the server side, stores the session in an **encrypted, httpOnly cookie**, and
proxies already-authenticated requests to the app. The app frontend contains
**no auth code** and never sees the token.

- The token lives in the cookie, **out of JavaScript's reach**.
- Keycloak client: **confidential** (proxy holds a client secret).
- This is the Backend-For-Frontend (BFF) pattern.

## Why two

The split follows each app's job:

| | location-app | placement-editor |
|---|---|---|
| Role | CAMARA API **consumer** | self-contained authoring **tool** |
| Talks to | the CAMARA gateway (REST) + a live **WebSocket** | its own backend, same origin |
| Needs the token in JS? | **Yes** - `Bearer` on fetch + `Sec-WebSocket-Protocol` on the WS | No |
| Pattern | `keycloak-js` (token in JS) | `oauth2-proxy` (BFF, token in cookie) |
| Keycloak client | public + PKCE | confidential |

location-app must present a Keycloak-issued JWT that the gateway validates
against a realm role, and it opens an authenticated WebSocket. Both require the
token *in the page*, so `keycloak-js` is the fit. It is also the canonical
picture for this project: a CAMARA consumer that holds and presents a CAMARA
token is exactly what the profile exposes.

placement-editor only calls its own backend through the proxy. Gating it wholesale
at `oauth2-proxy` protects the entire app (static assets included) with zero
frontend auth code, and keeps the token out of the browser.

## Security posture

Both are secure. Current guidance (IETF *OAuth 2.0 for Browser-Based Apps*)
favours the BFF pattern because the token never reaches JavaScript, which
removes a class of XSS token-theft risk. location-app uses `keycloak-js` for the
Bearer and WebSocket needs described above.

## Refresh behaviour and the silent SSO check

With `keycloak-js`, a page refresh re-validates the session. Under
`onLoad: "login-required"` that is a full-page redirect round-trip - instant
(the SSO cookie means no password) but visible as a brief splash. location-app
uses `onLoad: "check-sso"` with a **silent iframe** instead
(`public/silent-check-sso.html`, the official same-origin snippet): the session
is checked in a hidden iframe with no visible redirect. When no session exists
the app calls `keycloak.login()` explicitly.

For the silent check to work, the location-app Keycloak client must list
`<app-origin>/silent-check-sso.html` in **Valid Redirect URIs** and the app
origin in **Web Origins**. If a browser blocks the iframe's third-party cookie,
`keycloak-js` falls back to the full-page redirect.

`oauth2-proxy` needs no equivalent: it validates the session cookie server-side
on each request and serves the app directly, with no redirect unless the cookie
has expired.

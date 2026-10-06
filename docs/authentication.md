# Authentication

The browser applications sign in against the Keycloak realm `5g-testbed` with
OpenID Connect, in two ways that differ in where the token lives. The rules the
gateway applies to a token are in the
[profile](https://github.com/Jacobbista/5g-northbound/blob/main/spec/private-profile/README.md#4-authorisation-2-legged-organisation-scoped).

| | location-app | placement-editor |
|---|---|---|
| Role | CAMARA consumer | operator tool |
| Calls | the gateway's REST API and position stream | its own backend, same origin |
| Flow | authorisation code with PKCE, in the browser (`keycloak-js`) | authorisation code, in `oauth2-proxy` in front of the service |
| Token | in the page's memory | in an encrypted httpOnly cookie held by the proxy |
| Keycloak client | public, PKCE `S256` | confidential, with a client secret |

## location-app

The application needs the token itself: it sends it as `Bearer` on every call
to the gateway, and as the subprotocol `bearer.jwt, <jwt>` when it opens the
position stream, since a browser cannot set `Authorization` on a WebSocket and
a token does not belong in a URL.

`keycloak-js` starts with `onLoad: "check-sso"`: a hidden iframe loads
`public/silent-check-sso.html` and checks the session without a visible
redirect. Without a session the application calls `keycloak.login()`. The
Keycloak client lists `<origin>/silent-check-sso.html` among its valid redirect
URIs and the origin among its web origins. A browser that blocks the iframe's
third-party cookie gets a full-page redirect instead.

The access token lives about five minutes. The application calls
`updateToken(60)` periodically, which renews the token when less than 60 s
remain, reloads the data and reconnects the stream with the new token. A failed
renewal sends the user back to the login. A stream closed with `4401` is not
reopened until the token changes.

## placement-editor

`oauth2-proxy` runs the flow on the server, keeps the session in its cookie,
and forwards authenticated requests. The editor contains no authentication code
and never sees a token. Everything behind the proxy is protected, static files
included, which matters because the editor's routes reach the WiFi bindings
with their BSSIDs.

The IETF guidance on OAuth for browser-based applications prefers this pattern,
because a token that never reaches JavaScript cannot be taken by a script
injected into the page. The location-app needs the token in the page for the
reasons above.

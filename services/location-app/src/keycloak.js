import Keycloak from "keycloak-js";
import { KEYCLOAK_CLIENT_ID, KEYCLOAK_REALM, KEYCLOAK_URL } from "./config";

const keycloak = new Keycloak({
  url: KEYCLOAK_URL,
  realm: KEYCLOAK_REALM,
  clientId: KEYCLOAK_CLIENT_ID,
});

// `check-sso` validates an existing SSO session in a hidden iframe (see
// public/silent-check-sso.html) instead of a full-page redirect, so a refresh
// no longer flashes the login round-trip. When there is no session the app
// calls keycloak.login() explicitly (see App.jsx). Falls back to a redirect if
// the browser blocks the iframe's third-party cookie.
export const initOptions = {
  onLoad: "check-sso",
  silentCheckSsoRedirectUri:
    typeof window !== "undefined" ? `${window.location.origin}/silent-check-sso.html` : undefined,
  pkceMethod: "S256",
};

export default keycloak;

# Private user sessions with Cloudflare Access

Use Cloudflare Access for browser sign-in and Cloudflare Tunnel for connectivity.
MRCAT validates the Access JWT's RSA signature, issuer, application audience and
expiry before serving the console or API. An unsigned email header is not an
identity. Human-user tokens must include a nonempty subject and email; service
tokens without a human identity cannot open this console.

## Configure and start

1. Create a Cloudflare Access **Self-hosted** application for the complete MRCAT
   hostname, including every path. Add an Allow policy for the intended users and
   an identity provider, such as email one-time PIN. Do not use a Bypass policy.
2. Find the Access team domain and the application's Audience (AUD) tag in the
   Cloudflare dashboard. These values are not the tunnel token or API keys.
3. Install this checkout's Python dependencies (`python -m pip install -e .`) and
   set the following in the server's environment or its `--env-file`:

   ```dotenv
   MRCAT_AUTH_MODE=cloudflare
   MRCAT_ACCESS_TEAM_DOMAIN=https://YOUR-TEAM.cloudflareaccess.com
   MRCAT_ACCESS_AUD=YOUR-APPLICATION-AUD-TAG
   ```

4. Start a dedicated shared instance with its own artifact directory and port:

   ```bash
   python -m mrcat.web.server --auth cloudflare \
     --host 127.0.0.1 --port 7882 \
     --artifact-dir runtime_multi_user --env-file /path/to/config.env
   ```

5. Route the protected hostname through Cloudflare Tunnel to
   `http://127.0.0.1:7882`. Keep the existing local console on its original port.
   Keep both the application and `cloudflared` running as supervised services.
6. Test with two separate Cloudflare logins. Each should start with an empty task
   list, create a task, and see only its own task after a reload. A session URL
   copied from one account must return 404 for the other, including download,
   progress, reply, stop, study setup and fork URLs.

Missing configuration prevents authenticated-mode startup. Missing, forged or
expired tokens return 401; inability to retrieve verification keys returns 503.
There is no anonymous fallback. Progress streams end when their sign-in expires.
Responses are private and not cacheable. Do not override this with a Cloudflare
Cache Everything rule or a browser/service-worker cache.

Official references: [Access JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
and [Tunnel setup](https://developers.cloudflare.com/tunnel/get-started/).

## Session ownership and existing tasks

Authenticated users' sessions are stored under
`ARTIFACT_DIR/.users/SHA256([issuer, subject])/session_SESSION_ID/`. The signed
issuer and subject select the store; the browser cannot choose a username or
owner. An email change with the same subject retains the user's tasks. A different
subject is a different owner, even if the email is the same.

New sessions and copies use `session_` IDs. Existing `bridge_` session IDs,
directories and checkpoints stay unchanged and use the same `/api/sessions/{sid}`
endpoints and ownership checks. The API uses `session_id` and a `session` envelope
for create, reply, stop, setup and fork responses.

All API operations, background workers, view caches and forks use that user's
store. Session state continues to live in LangGraph checkpoints; no separate
ownership database or front-end filtering is needed. Linked session directories
are excluded from authenticated lists and rejected by authenticated session APIs.
Artifact paths and symlinks cannot escape their session through the download API.

Existing tasks in the original artifact directory remain in the local console.
They are not assigned to the first person who signs in. An administrator can
explicitly copy an idle historical session into the intended user's store with
`python -m mrcat.fork SOURCE_SESSION --artifact-dir USER_STORE`. Determine the
user store from that user's newly created task; never guess ownership from email.
Keep the original unless the owner explicitly requests its removal.

## Execution boundary

This change isolates web access and session storage. Generated Python/R/shell
code still runs with the server OS account's permissions, and model credentials
and compute capacity still belong to the server operator. It does not create an
OS sandbox or per-user billing. Use this instance for trusted research users.
Running untrusted tenants requires separate OS/container permissions and secrets
for their execution workers before claiming filesystem or process isolation.

Local mode remains available for the administrator's SSH-forwarded localhost
console. Its CLI refuses non-loopback binding, and Access JWT requests to local
mode are rejected to catch a misconfigured Tunnel target. Local mode itself is
not a multi-user endpoint and must not be exposed by ngrok or a public tunnel.

# Deployment

TS-Courser can run locally with `ts_courser.settings`. A production process must
use `DJANGO_SETTINGS_MODULE=ts_courser.settings_production` and provide a secret
key and host list through the environment. Copy `.env.example` as a starting
point, generate a unique random `DJANGO_SECRET_KEY`, and keep the real file
outside version control. Production settings fail during startup when either
required value is absent. The app does not automatically load `.env`; configure
these environment variables in the process manager or hosting platform.

The application should be served over HTTPS by a reverse proxy or platform
ingress. Production enables HTTPS redirects, secure session and CSRF cookies,
HSTS, content type sniffing protection, and same-origin referrer policy. Set
`DJANGO_USE_PROXY_SSL_HEADER=true` only when the trusted TLS terminating proxy
sets `X-Forwarded-Proto: https`; otherwise leave it disabled. Add the public
HTTPS origins to `DJANGO_CSRF_TRUSTED_ORIGINS` when requests come from a
separate origin.

Do not configure the reverse proxy to serve `/protected-media/` directly from
disk. That route must reach Django so authentication, pending-account, and
course-enrollment checks run before uploaded PDFs, answer keys, thumbnails, or
avatars are returned. Only public static assets under `/static/` should bypass
Django.

Configure a production WSGI server to load `ts_courser.wsgi:application`;
`manage.py runserver` is only for development. After exporting the production
environment, run the release checks before starting the service:

```bash
export DJANGO_SETTINGS_MODULE=ts_courser.settings_production
uv sync
npm install
uv run python manage.py migrate
uv run python manage.py collectstatic --noinput
uv run python manage.py check --deploy
```

HSTS preload is deliberately opt-in. `security.W021` is expected while preload
is disabled; enable preload only after confirming the domain meets its
requirements. Confirm all affected subdomains support HTTPS before enabling
HSTS include-subdomains; both options are configurable.

Static assets include ES modules, Monaco files, and the Pyodide JavaScript and
WASM runtime. `collectstatic` must copy the `static/` tree and the configured
`node_modules/monaco-editor` and `node_modules/pyodide` directories into
`STATIC_ROOT`; do not serve these files through a transformation that strips
`.mjs` or `.wasm` content types. The interactive Python worker requires the
response headers `Cross-Origin-Opener-Policy: same-origin` and
`Cross-Origin-Embedder-Policy: credentialless` on the application and static
responses. Verify those headers and that `.wasm` files are served successfully
after every proxy/CDN change.

Back up the production SQLite database and uploaded media together, using a
consistent snapshot while the service is quiesced. Store backups encrypted,
retain several generations, and periodically test restoring to a separate
database before relying on the backup. The application does not configure
external object storage or database services; those choices remain deployment
specific.

## Microsoft Entra ID sign-in

The production app is registered in the Microsoft global cloud as a
single-tenant **Web** application. Use these non-secret values:

| Setting | Value |
| --- | --- |
| Tenant ID | `7222912a-435d-423b-b22b-74b909c3bf8b` |
| Client ID | `5910709e-99db-4cc0-9468-88497aa32f23` |
| School sign-in domain | `tsinglan.org` |
| Redirect URI | `https://courser.tsinglan.top/accounts/microsoft/callback/` |

In the Entra app registration:

1. Select **Accounts in this organizational directory only**.
2. Add the exact redirect above under **Authentication > Web**. Do not enable
   implicit access-token or ID-token issuance.
3. Under **Token configuration**, add the optional ID-token claim `acct`. The
   application fails closed unless `acct=0`, which excludes guest accounts.
4. Create a client secret (or replace it with a certificate in a later release)
   and place it in the deployment secret store. Never add it to `.env.example`
   or the repository.
5. If **Assignment required** is enabled on the enterprise application, assign
   all eligible students and teachers; otherwise Entra blocks their first login
   before the platform can create a student account or teacher approval request.

Set the following production environment values in addition to the Django
settings above:

```bash
export DJANGO_ALLOWED_HOSTS=courser.tsinglan.top
export DJANGO_CSRF_TRUSTED_ORIGINS=https://courser.tsinglan.top
export MS_ENTRA_TENANT_ID=7222912a-435d-423b-b22b-74b909c3bf8b
export MS_ENTRA_CLIENT_ID=5910709e-99db-4cc0-9468-88497aa32f23
export MS_ENTRA_CLIENT_SECRET='<from the deployment secret store>'
export MS_ENTRA_SCHOOL_DOMAIN=tsinglan.org
export MS_ENTRA_REDIRECT_URI=https://courser.tsinglan.top/accounts/microsoft/callback/
```

Create the first platform administrator only from the deployment shell:

```bash
uv run python manage.py createsuperuser
```

The custom user manager marks this account as a local platform administrator.
There is no public registration or automatic "first visitor" promotion.
Administrators issue local student accounts at `/accounts/manage/`; each initial
password is displayed once and expires after seven days by default. Teachers
and students choose their role only after their first verified Microsoft sign-in.
That choice is then bound to the Microsoft identity and is not shown on later
sign-ins. Teachers appear on the management page and cannot enter the platform
until approved. Directory disable/removal synchronization is outside the first
release, so administrators must also deactivate departed users locally.

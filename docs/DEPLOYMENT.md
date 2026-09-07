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

Microsoft login is not part of this release configuration and remains pending.

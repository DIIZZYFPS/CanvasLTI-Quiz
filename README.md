# CanvasLTI-Quiz

Turns quiz questions written as plain text (or in a Word, PDF or Markdown file) into a Canvas-ready
**QTI 1.2** package. No AI involved: a deterministic parser reads the questions, shows you a preview
with any problems flagged, and then either downloads the package or, when launched from Canvas,
uploads it straight into your course.

It runs two ways:

- **Standalone** - open the site, paste or upload questions, download the `.zip`, import it into any
  Canvas course yourself (Settings > Import Course Content > QTI .zip file).
- **As an LTI 1.3 tool inside Canvas** - the same page, plus an *Upload to Canvas* button that creates
  the quiz in the course it was launched from.

Question types: multiple choice, multiple answers, true/false, short answer, fill in multiple blanks,
essay, plus the Respondus legacy format. See the [formatting guide](app/public/Instructions.txt)
(also downloadable from the app).

## Run it locally

Needs Python 3.10+ and Node 20+.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # set SECRET_KEY (see Configuration)
FLASK_DEBUG=1 python main.py         # http://127.0.0.1:5000
```

That serves the committed frontend build, which is enough for standalone use. To work on the
frontend with hot reload, run the Vite dev server alongside it (it proxies `/api` to port 5000):

```bash
cd Frontend
npm ci
npm run dev                          # http://localhost:5173
```

Session cookies are `Secure` and `SameSite=None` (Canvas shows the tool in an iframe), so a browser
has to accept `Secure` cookies from `localhost` - Chrome and Firefox do; for anything else, or to try
the Canvas integration end to end, use HTTPS.

`main.py` only enables Flask's debugger when you set `FLASK_DEBUG=1`; never do that on a server.

### Tests and checks

```bash
python -m pytest unit_tests/                          # backend
ruff check app unit_tests main.py                     # lint (unused imports, undefined names)
cd Frontend && npm test && npm run lint && npm run build
```

CI runs the same commands (`.github/workflows/ci.yml`).

### The frontend build is committed

Flask serves the built bundle from `app/assets/` (see `app/utils/vite_manifest.py`), so there is no Node
step on the server. `npm run build` writes there; commit the result with your source change.
`.github/workflows/rebuild-frontend.yml` also rebuilds and commits it after changes to `Frontend/` land
on `main` (put `[skip rebuild]` in a commit message to skip that).

## Configuration

Settings come from environment variables; `.env` is loaded automatically.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | **Required in production.** Signs the session cookie and encrypts the Canvas token stored in it. Generate one with `python -c "import secrets; print(secrets.token_hex(32))"`. If unset, a random key is generated at startup, which breaks logins across restarts and workers. Rotating it just makes people re-authorise. |
| `CANVAS_DOMAIN` | Your Canvas URL, e.g. `https://school.instructure.com`. Base for the API and OAuth calls. |
| `CANVAS_API_CLIENT_ID`, `CANVAS_API_CLIENT_SECRET` | The Canvas REST API developer key used to upload quizzes (a separate key from the LTI one). |
| `CANVAS_OAUTH_REDIRECT_URI` | `https://<your-host>/api/auth/callback`; must match the API key's redirect URI. |
| `LTI_PRIVATE_KEY` | Optional. PEM text of the tool's private key, used only when `app/config/private.key` does not exist. |
| `CACHE_DIR` | Where LTI launch state is cached (default `/tmp/flask_cache`). |
| `MAX_UPLOAD_MB` | Largest accepted upload or pasted quiz (default `10`). |
| `FRAME_ANCESTORS` | Optional. Space-separated hosts allowed to embed the tool, e.g. `https://school.instructure.com`. Sends `Content-Security-Policy: frame-ancestors 'self' ...`. Off by default because the right hosts depend on your Canvas setup (a vanity domain differs from `CANVAS_DOMAIN`). |
| `FLASK_DEBUG` | `1` enables Flask's debugger. Development only. |

## Setting it up in Canvas

Standalone use needs none of this.

1. **Keys.** `python -m app.config.keys` writes `app/config/private.key` (keep it secret; it refuses to
   overwrite existing keys without `--force`) and `public.key`.
2. **Tool config.** Copy `app/config/config.json.example` to `app/config/config.json` and fill in your
   Canvas issuer, `client_id` and deployment IDs. Both files are git-ignored.
3. **LTI developer key** (Canvas Admin > Developer Keys > LTI Key):
   OIDC login `https://<host>/login/`, redirect `https://<host>/launch/`, public JWK URL
   `https://<host>/jwks/`. Add the custom field `canvas_course_id=$Canvas.course.id`: the launch reads the
   numeric course ID from it. Without it the tool cannot tell which course it was opened from, and uploading
   is unavailable (downloading still works).
4. **REST API developer key** for uploads: redirect URI `https://<host>/api/auth/callback`, with the scopes
   `url:POST|/api/v1/courses/:course_id/content_migrations`, `url:GET|/api/v1/progress/:id` and
   `url:POST|/api/v1/courses/:course_id/files`. Put its ID and secret in `CANVAS_API_CLIENT_ID` /
   `CANVAS_API_CLIENT_SECRET`.

When a launch finds no Canvas token in the session, it sends the user through Canvas authorisation. The token
lives in the session for up to an hour; the header badge reads "Canvas Connected" while it is valid and
"Canvas session expired" afterwards (relaunch from the course to reconnect).

## Deploying

Run it behind an HTTPS reverse proxy with gunicorn, as in `app/Procfile`:

```bash
gunicorn main:app --bind 0.0.0.0:$PORT --workers 1 --threads 2
```

- Set `SECRET_KEY` (the same value for every worker) and the Canvas variables above.
- Use HTTPS: the session cookie is `Secure`.
- If the proxy caps request bodies (nginx defaults to 1 MB), raise the cap to at least `MAX_UPLOAD_MB`.
- Updating dependencies: `requirements.txt` bounds each package to the major version the app is tested
  with; widen a bound deliberately, after running the tests.

## Project layout

```
main.py                 entry point (gunicorn main:app)
app/
  __init__.py           app factory: config, security headers, API/SPA routing
  routes/               api.py (preview/download/canvas), auth.py (Canvas OAuth), lti.py (LTI 1.3)
  utils/                parser.py + respondus_parser.py, exporter.py (QTI), file_reader.py + docx_reader.py
  config/               LTI keys script and config.json.example
  public/Instructions.txt   the formatting guide served by the app
  assets/               built frontend (committed, generated)
Frontend/               React + TypeScript + Vite + Tailwind (see Frontend/README.md)
unit_tests/             pytest suite
Tests/                  sample quizzes (txt, docx, pdf) for manual testing
```

## Limitations

- Each question needs a blank line before the next one. Word documents and pasted text are handled
  (Word's automatic lists too); PDFs often lose those blank lines, so check the preview.
- The package holds one quiz. It has no `imsmanifest.xml`: Canvas imports it as-is, but other LMSs may require one.
- Uploads are limited to 10 MB by default.

# Sample Test Questions

You can use these questions to test the converter. These examples use single-line formatting:

```
1. Which of these is a JavaScript framework? (2 points)
A) Django
B) Laravel
C) React
D) Flask
Answer: C

2. Essay: Describe the difference between a list and a tuple in Python. Points: 5

3. The chemical symbol for Gold is Au. (1 point) (T/F) Answer: True 

4. SA: What is the name of the galaxy that contains our Solar System? (1 point) Answer: Milky Way

5. To infinity, and _____! (3 points) Answer: beyond

6. Python is a statically-typed language. (1 point) (True/False) Answer: False 

7. What is the powerhouse of the cell? (1 point)
A) Nucleus
B) Ribosome
C) Mitochondrion
D) Endoplasmic Reticulum
Answer: C

8. What planet is known as the Red Planet? [Short Answer] (1 point) Answer: Mars

9. Essay: Explain the importance of version control in software development.

10. A ____ in time saves nine. (1 point) Answer: stitch
```

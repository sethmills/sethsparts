# Running this yourself

Everything below is optional except the first section. The app runs fine on a laptop
with no lights, no label printer and no interest in the community map — those pieces
appear when you configure them and stay hidden until you do.

Whichever route you take, the first thing you see when you open it is a setup wizard.
It creates your account, asks what your workshop is called and which timezone you're
in, and offers the optional pieces one at a time. Every step is skippable, and every
step stays available afterwards under **Settings** — a wizard you can only run once is
a wizard people work around.

---

## Docker (recommended, works on Linux, macOS and Windows)

You need Docker Desktop (or Docker Engine plus the Compose plugin). Nothing else — no
Python, no database, no build tools.

```bash
git clone https://github.com/sethmills/sethsparts.git
cd sethsparts

# Two secrets are required. Generate them rather than inventing them.
cat > .env <<EOF
DJANGO_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
EOF

docker compose up -d
```

Then open <http://localhost:3200>.

`DJANGO_ALLOWED_HOSTS` is the list of names Django will answer to. Add your domain to
it when you have one — Django refuses requests claiming a host it doesn't recognise.

Your data lives in `./data/` next to the compose file: `db.sqlite3` for the database
and `media/` for uploaded files and archived documents. Backing up is copying that
folder.

---

## Without Docker

You need **Python 3.12 or newer** — Django 6.1 requires it, and 3.11 will not work.
This is the most common stumbling block; check with `python3 --version` first.

```bash
git clone https://github.com/sethmills/sethsparts.git
cd sethsparts

python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py runserver
```

Then open <http://127.0.0.1:8000>. For anything beyond your own machine, use a real
server rather than `runserver`:

```bash
# Linux and macOS
gunicorn config.wsgi:application --bind 0.0.0.0:3200

# Windows — gunicorn needs fork(), which Windows doesn't have.
# The Windows-capable server is already in requirements.txt for that reason.
waitress-serve --listen=0.0.0.0:3200 config.wsgi:application
```

### Windows notes

Two things that catch people out, both already handled:

- **No gunicorn.** It needs `fork()`. `waitress` is installed automatically on Windows
  and is what you should run, as above.
- **Text encoding.** Every file the app reads or writes names its encoding explicitly,
  because Windows otherwise defaults to a legacy codepage and mangles the `µ` and `Ω`
  in part names. If you add code that touches files, pass `encoding="utf-8"`.

---

## Reaching it from outside

Optional. Everything works on your home network without it — but a phone or another
workshop needs an address the internet can get to.

The setup wizard walks through **Cloudflare Tunnel**, which is what this was built
around: a real domain with a valid certificate and **no open ports on your router**,
because the tunnel makes outbound connections. The short version:

1. Put your domain on Cloudflare's free plan.
2. Zero Trust → Networks → Tunnels → Create a tunnel, Docker connector.
3. Point its public hostname at `http://sethsparts:3200`.
4. Put the token in `.env` as `TUNNEL_TOKEN=…`.
5. Set `DJANGO_ALLOWED_HOSTS` to your domain.
6. `docker compose up -d`.

Any reverse proxy works just as well — nginx, Caddy, Traefik, a Tailscale funnel. Two
things matter: forward the `X-Forwarded-Proto` header, which the app already expects,
and set `DJANGO_ALLOWED_HOSTS`.

---

## Adding the hardware, later

Both are optional and neither is needed to use the app.

**LEDs.** A Raspberry Pi with the controller in `led-controller/` and a strip of
addressable LEDs along each cabinet. The wizard takes the controller's address, tests
the connection, and stores which LEDs belong to which drawer. The Pi's own
`strip_map.json` still has to be edited on the Pi, because only you can see which strip
is wired to which output.

**Label printer.** A Pi with the print bridge in `label-printer/`, next to the printer.
The app renders the label and sends the finished bytes; nothing needs a driver on the
machine running the app. Zebra/ZPL is what this was built and tested against — the
settings page also offers Brother QL, Dymo and a generic CUPS route.

---

## Things worth doing once it's running

```bash
# Start with a reference library — 27 charts, pinouts and guides. Take
# them, ignore them, or take them and delete two thirds.
python manage.py load_starter_reference

# Fetch local copies of everything linked, since links rot.
# Polite: a pause between requests.
python manage.py archive_documents

# Tell yourself when there's a newer version. Exits 1 when there is,
# so it composes with whatever you already use to get notified.
python manage.py check_updates --quiet
```

---

## If something's wrong

- **A page is blank or 500s** — check `docker compose logs sethsparts`, or the console
  if you're running `runserver`.
- **"DisallowedHost"** — `DJANGO_ALLOWED_HOSTS` doesn't include the name you used.
- **Timestamps are in the wrong timezone** — Settings → Name and place.
- **Labels print but the text is tiny** — the label sizes in
  `inventory/label_printing.py` don't match your stock. See Help → Lights and the label
  printer.
- **A datasheet didn't archive** — expected sometimes. The manage page says why: a
  login wall, a 404, too big. A link behind a login stays a link.

The in-app **Help** section covers how the app is organised and how to lay out a
workshop so it stays usable as it fills up. That last one is worth reading before you
put everything in one drawer.

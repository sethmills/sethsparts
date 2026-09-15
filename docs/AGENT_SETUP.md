# Give yourself an AI assistant to help set this up

For anyone who has cloned this project and would like a hand installing it, configuring it, and
filling in the data. It sets up [Hermes Agent](https://hermes-agent.nousresearch.com/) — the same
kind of tool as Claude Code or Codex — running on **DeepSeek**, and then hands it the job.

You do the four steps once. After that the assistant does the work: it can read this project,
run its commands, look things up on the web, and fill in the parts data with you.

The DeepSeek configuration below is exactly what this project's maintainer runs on,
which is why it's written down.

## Step 1 — Install the Hermes desktop app

1. Go to **https://hermes-agent.nousresearch.com/** and download the app for your computer
   (Windows and macOS installers are on that page).
2. Run the installer, then open the app.
3. First launch:
   - **macOS** — if it says the app can't be opened because it's from an unidentified developer,
     go to System Settings → Privacy & Security and click **Open Anyway**.
   - **Windows** — if SmartScreen warns, click **More info** → **Run anyway**.
4. It will ask you to choose a model/provider. Pick anything for now — **step 3 is what moves it
   to DeepSeek.** If it offers a "Nous Portal" sign-in, that's the one-click option, and it also
   supplies the web-search tool mentioned at the end of this file.

## Step 2 — Get a DeepSeek API key

1. Go to **https://platform.deepseek.com/api_keys** and create an account.
2. Add a few dollars of credit. DeepSeek is **prepaid**: it spends from that balance and stops,
   so it can't run away with your card. A few dollars covers a lot of setup work.
3. Create an API key and copy it — it's shown once. Treat it like a password and keep it in a
   password manager.

## Step 3 — Point the assistant at DeepSeek

Easiest way: open a chat in the app and **paste the prompt in step 4.** It tells the assistant to
switch itself to DeepSeek and verify it, so you don't have to touch a config file.

If you'd rather do it by hand, the commands are:

```bash
hermes setup model             # pick DeepSeek, paste the key when it asks
```

Or, if you already have the key and only want to change the default model:

```bash
hermes config set model.provider deepseek
hermes config set model.default deepseek-v4-flash
```

and put the key in the file whose location this prints:

```bash
hermes config env-path         # e.g. ~/.hermes/.env
```

```
DEEPSEEK_API_KEY=your-key-goes-here
```

Then check it took — the first two lines should read `deepseek` and `deepseek-v4-flash`:

```bash
hermes config get model.provider
hermes config get model.default
hermes doctor
```

One rule worth knowing, because the assistant will follow it too: **settings go in
`config.yaml`, secrets go in `.env`.** Never put an API key in `config.yaml`, and never
hand-edit `config.yaml` — use `hermes config set` so a stray indent can't corrupt it.

## Step 4 — Paste this to the assistant

Copy everything in the box below into the chat, replacing the square brackets with your details.
The assistant can do the rest on its own.

```text
I need help setting up a workshop inventory application on this computer. I'm not a
programmer, so please explain what you're doing in plain language as you go, and ask me
before anything destructive.

Do these in order:

1. Make sure you are running on DeepSeek, and tell me which model you're using.
   Check with:  hermes config get model.provider  and  hermes config get model.default
   If they don't read "deepseek" and "deepseek-v4-flash", set them:
       hermes config set model.provider deepseek
       hermes config set model.default deepseek-v4-flash
   My DeepSeek API key needs to be in the .env file — run `hermes config env-path` to find
   it — as a line reading DEEPSEEK_API_KEY=... Ask me to paste the key; don't put it in
   config.yaml and don't print it back to me.
   Then run `hermes doctor` and confirm the DeepSeek model actually answers before we start.

2. Read the project's own instructions before touching anything. Clone it:
       git clone https://github.com/sethmills/sethsparts.git
   Then read README.md, then docs/RUNNING.md (the from-scratch guide). Those two files answer
   most questions — use them instead of guessing, and tell me if anything in them contradicts
   what you find.

3. Install it and get it running. Docker is the easiest route ("docker compose up -d"), and
   the README has the copy-paste version, including what to do on a Raspberry Pi or without
   Docker at all. Then open http://localhost:3200 and walk me through the setup wizard:
   my account, what to call my workshop, and the timezone.

4. Set up the hardware I actually have, and skip the rest — ask me what I've got:
   - LED strips in the cabinets: the wizard's Lights step takes the controller's address, and
     the "Flash the LED controller" step next to it walks through putting the firmware on the
     board (it's a script you run on the Raspberry Pi the board is plugged into).
   - A label printer: the Labels step. Only Zebra/ZPL has been tested on real hardware; the
     others are written from the manufacturers' manuals and the app says so.

5. Help me get my inventory in, then help me enrich it:
   - Import first (the README covers the import command, or use the app's own intake pages for
     a small amount of stuff).
   - Then set the AI keys under Settings → "Research & AI" — a DeepSeek key (descriptive
     enrichment) and a Tavily key (web research that finds product pages/datasheets/pricing).
     The enrichment queue at /enrichment/ then does it all in-app: "AI scan for candidates"
     flags the parts worth looking up, and "Enrich with DeepSeek" fills them in — no exporting
     and re-importing files back and forth. Ask me to paste each key; don't print them back to me.

6. When we're done, write down what you did and anything you had to work out the hard way, so
   the next conversation doesn't start from scratch. If you learned something specific to this
   project, save it as a skill.
```

## What this costs

DeepSeek charges by the token, and it's one of the cheapest frontier models: an afternoon of
setup help costs **cents**, and a large parts-research pass costs a few dollars. Current numbers:
<https://api-docs.deepseek.com/quick_start/pricing/> — and since it's prepaid, your balance is
the hard limit.

## If the assistant needs to search the web

DeepSeek supplies the thinking, not the searching. The app's own parts research now happens
in-app (it has its own Tavily key, set under Settings → "Research & AI"), but the assistant
still wants web search for general setup work — reading docs, checking hardware, troubleshooting.
Two things give it that:

- **Sign in with Nous Portal** — run `hermes setup --portal` (or take the sign-in offer during
  first launch). One sign-in covers a model *and* the tool gateway, web search included. This is
  the simplest option; you can still keep DeepSeek as the default model for everything it does.
- **A search API key** — Tavily, Exa and Brave all have free tiers. Ask the assistant to add one
  for you the first time it needs to look something up online.

Without either, the assistant can still open pages in a real browser on your machine and read
them — it's just slower than having a search tool.

## Doing it without the desktop app (optional)

The command-line version, if you'd rather:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash     # macOS, Linux, WSL2
iex (irm https://hermes-agent.nousresearch.com/install.ps1)            # Windows (PowerShell)
```

Then `hermes setup` once, and step 4 above works the same way. Docs:
<https://hermes-agent.nousresearch.com/docs/>

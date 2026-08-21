# flat-alert

Watches three Tirol rental sites 24/7 and sends a **Telegram message the moment a
new flat appears** that matches the criteria in `config.json`:

| Site | What is monitored |
|---|---|
| [ÖH Wohnungsbörse](https://wohnen.oehweb.at/) | Newest listings (RSS feed) |
| [immo.tt.com](https://immo.tt.com/) | Rental flats, Innsbruck Stadt + Land |
| [ImmoScout24.at](https://www.immobilienscout24.at/) | Rental flats, Innsbruck Stadt + Land |

Runs for free on GitHub Actions every ~10 minutes. No dependencies — plain Python 3.

## One-time setup

### 1. Create the Telegram bot (2 minutes)

1. In Telegram, open **@BotFather** → send `/newbot` → pick a name and username.
   BotFather replies with a **bot token** (looks like `1234567:AA...`).
2. Open a chat with your new bot and send it any message (e.g. "hi").
3. Get your **chat id**: open
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   in a browser and copy the number at `"chat":{"id": ... }`.
   *Tip: for alerts to several people, create a Telegram group, add the bot,
   send a message in the group, and use the group's (negative) id instead.*

### 2. Add the secrets on GitHub

In the repo: **Settings → Secrets and variables → Actions → New repository secret**

- `TELEGRAM_BOT_TOKEN` — the token from BotFather
- `TELEGRAM_CHAT_ID` — the chat id

### 3. Done

The workflow (`.github/workflows/monitor.yml`) runs automatically every ~10 min.
The very first run only memorises the current listings (no alert flood);
alerts start from the second run. You can trigger a run manually under
**Actions → Flat monitor → Run workflow**.

## Changing the search criteria

Edit `config.json`:

- `max_price` — maximum monthly rent in € (listings without a price are always alerted)
- `exclude_keywords` — listings whose title contains one of these are skipped
- `sources.*.pages` — swap the URLs to monitor a different district
  (e.g. `.../tirol/landeck` instead of `.../tirol/innsbruck-stadt`)

## Local test

```bash
python3 monitor.py
```

Without the Telegram env vars it prints alerts instead of sending them.
State (already-seen listings) lives in `state/seen.json` and is committed
back by the workflow after each run.

## Notes

- GitHub's cron is not exact — checks land every 10–20 minutes in practice.
- If a site changes its layout, the run prints a `WARNING` for that source in the
  Actions log while the other sources keep working.
- Be fair: the monitor makes ~12 lightweight requests per run, comparable to one
  person refreshing the sites — keep it that way.

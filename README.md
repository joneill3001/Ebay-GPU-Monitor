# eBay GPU Deal Scanner

Polls eBay UK for newly listed GPUs at your target prices and posts deal alerts to Discord channels.

## Features

- **eBay Browse API** — newest listings first, ships to UK, GBP pricing
- **Strict title matching** — filters wrong models, Ti/Super variants, parts, and accessories
- **Landed cost** — item price plus cheapest shipping to your postcode
- **Auto-scan** — all NVIDIA 10/20/30/40/50 series (xx60–xx90, Ti & Super; no xx50)
- **Easy pricing** — one file `config/prices.yaml` for all target prices
- **Discord embeds** — title, link, price, % below target, image, time listed
- **Per-series Discord channels** — 10 / 20 / 30 / 40 / 50 series
- **Batched eBay searches** — one API call per GPU model (e.g. `RTX 3060` covers base + Ti)

## Quick start

### 1. Prerequisites

- Python 3.11+
- [eBay Developer](https://developer.ebay.com/) account with **Buy API / Browse API** enabled
- A Discord bot invited to your server

### 2. Install

```powershell
cd C:\Users\desktop\Projects\ebay-gpu-deals
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

### 3. eBay API setup

1. Go to [developer.ebay.com](https://developer.ebay.com/) → **My Account** → **Application Keys**.
2. Create an app (Production keys for real listings).
3. Ensure **Buy API** access is granted for your application.
4. Copy **Client ID** and **Client Secret** into `.env`:

```
EBAY_CLIENT_ID=YourProdAppId
EBAY_CLIENT_SECRET=YourProdCertId
EBAY_DELIVERY_POSTCODE=SW1A1AA
```

Use your real UK postcode (no spaces is fine) for accurate shipping estimates.

### 4. Discord bot setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. **New Application** → **Bot** → **Reset Token** → copy the token into `.env`:
  ```
   DISCORD_BOT_TOKEN=your_bot_token_here
  ```
3. **OAuth2** → **URL Generator**:
  - Scopes: `bot`
  - Bot permissions: `Send Messages`, `Embed Links`, `View Channels`
4. Open the generated invite URL and add the bot to your server.
5. In Discord: **User Settings** → **Advanced** → enable **Developer Mode**.
6. Right-click the alert channel → **Copy Channel ID**.

### 5. Configure prices and channels

Edit **[config/prices.yaml](config/prices.yaml)** — change target prices in one place:

```yaml
channels:
  "10": "YOUR_CHANNEL_ID   # GTX 1060–1080 Ti
  "20": "YOUR_CHANNEL_ID   # RTX 2060–2080 Super
  "30": "YOUR_CHANNEL_ID   # RTX 3060–3090 Ti
  "40": "YOUR_CHANNEL_ID   # RTX 4060–4090
  "50": "YOUR_CHANNEL_ID   # RTX 5060–5090

prices:
  "3080": 250
  "3080-ti": 300
  "4090": 900
  "5090": 1200
  # ... every key is listed in the file
```

| To change… | Edit… |
|------------|--------|
| RTX 3080 target to £280 | `"3080": 280` under `prices:` |
| Which Discord channel gets 30-series alerts | `channels."30"` |
| Poll speed (many GPUs = slower cycle) | `config/settings.yaml` → `poll_interval_seconds` (default 120) |

**Scanned GPUs:** 1060–1080 Ti, RTX 2060–2080 Super, 3060–3090 Ti, 4060–4090, 5060–5090 (Ti/Super where applicable). **Not scanned:** 1050, 1650, 3050, 4050, 5050, etc.

Optional: **[config/settings.yaml](config/settings.yaml)** for `poll_interval_seconds`, `max_listing_age_minutes`, `search_delay_seconds`.

### 6. Run

```powershell
python -m src
```

The scanner logs each cycle and posts embeds when a listing passes matching and is at or below your target (including shipping).

## How matching works

1. eBay API filters by price, UK delivery, GBP, BIN + auctions, and excludes “For parts or not working”.
2. Title matcher enforces required terms (e.g. `rtx`, `3080`), blocks junk keywords, and uses variant rules:
  - `base` — 3080 only, not Ti / Super / mobile
  - `ti` — must include “3080 Ti”
  - `super` — must include “3080 Super”
3. Accessories (“fan for RTX 3080”, “compatible with”) are rejected.

## Discord alert fields

Each deal embed includes:

- **Title** (clickable link to eBay)
- **Price** (landed cost; auctions show current bid)
- **Target** and **% below target**
- **Listed** (e.g. “4 minutes ago”)
- **Thumbnail** image when available

## Project layout

```
config/prices.yaml     # all target prices + Discord channels
config/settings.yaml   # poll interval, listing age, delays
data/scanner.db        # seen items (auto-created, gitignored)
src/
  ebay_client.py       # OAuth + Browse API
  matcher.py           # strict GPU title rules
  scanner.py           # 60s poll loop
  discord_notifier.py  # embed alerts
```

## eBay API usage (batched searches)

Variants sharing the same chip (e.g. **RTX 3060** + **3060 Ti**) use **one** eBay search; the matcher picks the right target locally.

| | Before | After batching |
|--|--------|----------------|
| API calls per cycle | 33 | **18** |
| 17h @ 2 min poll (~510 cycles) | ~16,800/day | **~9,180/day** |

eBay’s default cap is **5,000 calls/day**. Batching cuts usage roughly in half but may still exceed the free tier if you run 7am–midnight at 2 min poll. Options: [Application Growth Check](https://developer.ebay.com/develop/apis/api-call-limits) for a higher limit, or slightly longer `poll_interval_seconds`.

On startup the log shows: `18 eBay calls/cycle (33 GPU targets)`.

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Troubleshooting


| Issue                        | Fix                                                                       |
| ---------------------------- | ------------------------------------------------------------------------- |
| `No enabled searches found`  | Set `enabled: true` and real `discord_channel_id` values                  |
| `EBAY_CLIENT_ID` error       | Fill in `.env` from eBay developer portal                                 |
| Discord channel warning     | Re-invite bot; confirm channel ID; check bot can view the channel         |
| No alerts but listings exist | Title may fail matcher; check logs; loosen `require_terms` if appropriate |
| eBay `500` errors            | Fixed in latest code (filter retry). Confirm Production Browse API is enabled. |
| Rate limits                  | Reduce number of searches or increase `POLL_INTERVAL_SECONDS`             |

**Auction note:** eBay blocks `buyingOptions` with `sort=newlyListed`; results are mostly Buy It Now.

## Run 24/7 (optional)

Use **Task Scheduler** or [NSSM](https://nssm.cc/) to run `python -m src` from the project folder with the venv activated on Windows startup.

## License

Private use — eBay API usage must comply with [eBay API License Agreement](https://developer.ebay.com/join/api-license-agreement).
# bankfetch

`bankfetch` is a Python CLI for fetching account balances and transactions from Enable Banking and writing file-based state, raw archives, and normalized JSONL output that can run safely from cron.

## Requirements

- Python 3.11+
- `uv`
- An Enable Banking application ID and private RSA key

## Setup

```bash
uv venv
uv sync --extra dev
```

## Local development

The app defaults are Linux-first:

- config: `/etc/bankfetch/config.yaml`
- state: `/var/lib/bankfetch/state`
- output: `/var/lib/bankfetch/out`

For local development, pass an explicit config path with local state/output directories:

```bash
uv run bankfetch --config ./dev-config.yaml session status
```

Start from [examples/config.yaml](examples/config.yaml) and replace:

- `api.app_id`
- `api.private_key_file`
- `bank.aspsp`
- `bank.redirect_url`

## Commands

```text
bankfetch auth init
bankfetch auth complete --code <authorization_code>
bankfetch session status
bankfetch accounts list
bankfetch balances fetch --all-accounts
bankfetch transactions fetch --all-accounts --from 2026-04-01 --to 2026-04-18
bankfetch sync run --all-accounts
```

## Output layout

```text
/var/lib/bankfetch/
  state/
    active_session.json
    auth_init.json
    checkpoints.json
    lock/sync.lock
  out/
    raw/
      balances/YYYY/MM/DD/<account_key>/<timestamp>.json
      transactions/YYYY/MM/DD/<account_key>/<timestamp>_page_<n>.json
    normalized/
      balances/<account_key>.jsonl
      transactions/<account_key>.jsonl
      transactions/<account_key>_latest.jsonl
```

## Security notes

- Keep the config directory and private key readable only by the account running `bankfetch`.
- Logs never include the private key, JWT, or full authorization header.
- Masked account identifiers are persisted in session state and CLI output.
- Use filesystem permissions suitable for secrets on `/etc/bankfetch` and `/var/lib/bankfetch`.

## Cron example

```cron
17 */6 * * * /usr/local/bin/bankfetch sync run --all-accounts >> /var/log/bankfetch.log 2>&1
```

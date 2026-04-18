# bankfetch — Specification for v1 CLI

## 1. Purpose

`bankfetch` is a command-line application for fetching account balances and transactions from Enable Banking and storing the results locally in a cron-friendly format.

Version 1 is intentionally limited in scope:

- Enable Banking as the only provider
- multiple named bank session profiles
- read-only account information access
- balance fetch
- transaction fetch
- file-based local state
- no database required
- no categorization logic
- no write/payment functionality

The design supports multiple active sessions in version 1 and must make it easy to extend later to support:

- multiple providers
- multiple accounts across banks
- additional account data types

---

## 2. Product goals

The application must:

- authenticate against Enable Banking using the required JWT-based mechanism
- support a one-time interactive authorization flow
- support non-interactive recurring sync from cron after authorization is completed
- fetch accounts, balances, and transactions from one or more configured Enable Banking sessions
- store raw and normalized output on disk
- support incremental transaction sync
- be deterministic, observable, and safe to run unattended

The application should:

- use structured logs
- avoid leaking secrets in logs or output
- be robust against duplicate fetches and partial failures
- be easy to wrap from shell scripts or an external agent/orchestrator

---

## 3. Non-goals for v1

The following are explicitly out of scope for version 1:

- automatic browser-based completion of bank authorization
- built-in web server for OAuth callback handling
- payment initiation
- background daemon mode
- database storage
- reconciliation across providers
- transaction categorization
- data export to accounting systems
- secret management beyond file-based configuration

---

## 4. High-level architecture

The application is a local CLI with file-based persistence.

### 4.1 Components

Suggested internal modules:

- `cli` — command-line interface
- `config` — config loading and validation
- `auth` — JWT creation and signing
- `enable_client` — HTTP client for Enable Banking
- `session_store` — local storage for active session and sync state
- `balances` — balance fetch and normalization
- `transactions` — transaction fetch, pagination, normalization, deduplication
- `sync` — orchestration for cron-safe sync runs
- `logging` — structured logging helpers

### 4.2 Runtime model

There are two phases per configured session profile:

1. **Interactive setup phase**

   - operator starts an authorization flow for a named session profile
   - operator opens the returned bank authorization URL
   - operator completes bank login and consent
   - operator extracts the returned authorization code
   - operator completes session creation via CLI

2. **Recurring sync phase**

   - cron invokes `bankfetch sync run`
   - CLI generates a fresh JWT
   - CLI checks selected session validity
   - CLI fetches balances
   - CLI fetches transactions incrementally
   - CLI writes raw + normalized outputs
   - CLI updates checkpoints only after successful completion

---

## 5. Technology requirements

Implementation language: Python 3.11+

Recommended libraries:

- `httpx` for HTTP
- `typer` or `click` for CLI
- `pydantic` for config and model validation
- `pyjwt` or equivalent for JWT signing
- standard library `pathlib`, `json`, `logging`, `hashlib`, `datetime`

Implementation must not require a database.

Integrate with Enable Banking API: [API reference | Enable Banking Docs](https://enablebanking.com/docs/api/reference/)

---

## 6. CLI commands

## 6.1 Command overview

The CLI must support the following commands:

```bash
bankfetch auth init --session <profile>
bankfetch auth complete --session <profile> --code <authorization_code>
bankfetch session status --session <profile>
bankfetch accounts list --session <profile>
bankfetch balances fetch --session <profile>
bankfetch transactions fetch --session <profile>
bankfetch sync run [--session <profile> ...]
```

Optional helper commands may be added if useful, but the commands above are required.

---

## 6.2 `bankfetch auth init`

### Purpose

Start an interactive authorization flow.

### Behavior

The command must:

- load config
- resolve the target session profile
- generate a short-lived JWT for API authentication
- query Enable Banking for candidate banks if needed
- select the configured bank / ASPSP
- initiate the authorization flow
- print a bank authorization URL
- persist temporary authorization state needed for completion

### Inputs

Required or configurable inputs:

- session profile name
- bank / ASPSP identifier or bank selection config
- redirect URL
- consent validity window
- PSU type if needed
- optional state value (otherwise generated automatically)

### Output

Human-readable output by default, JSON output optional.

Minimum output must include:

- selected session profile
- generated authorization URL
- locally generated state value
- timestamp

### Exit behavior

- `0` on success
- non-zero on config, signing, API, or validation failure

---

## 6.3 `bankfetch auth complete --code <authorization_code>`

### Purpose

Complete session creation after the user has authorized with the bank.

### Behavior

The command must:

- load saved authorization-init state
- submit the authorization code to Enable Banking
- create a session
- fetch or store session metadata
- persist the session as the active session for the selected profile
- initialize state for future syncs

### Required arguments

- `--session <profile>`
- `--code <authorization_code>`

### Output

Must return or print at least:

- session identifier
- session status
- session validity window if available
- number of accounts discovered

### State changes

Must write/update:

- active session metadata for the selected profile
- account list for the session
- sync checkpoint container for the selected profile

---

## 6.4 `bankfetch session status`

### Purpose

Show whether the currently stored session for a selected profile is usable.

### Behavior

The command must:

- load active session from local state
- query remote session status
- report status in a concise form

### Output

Must include:

- selected session profile
- provider name (`enable_banking`)
- bank identifier / ASPSP metadata if available
- session ID
- remote status
- local active/inactive marker
- valid-until timestamp if available

### Exit code semantics

- `0` if session is usable for sync
- `20` if re-authorization is required
- other non-zero codes for technical failures

---

## 6.5 `bankfetch accounts list`

### Purpose

List accounts known for the selected active session profile.

### Behavior

The command must:

- read local session state
- optionally refresh account metadata if needed
- print account list

### Output fields

For each account, include if available:

- local account key
- provider account UID
- display name
- account type
- currency
- masked identification fields (never print full sensitive values unless explicitly allowed)

---

## 6.6 `bankfetch balances fetch`

### Purpose

Fetch balances for one or more accounts.

### Behavior

The command must:

- validate active session
- iterate through selected accounts
- fetch balances for each account
- store raw response payloads
- write normalized balance records
- support `--all-accounts` and `--account <id>`

### Required options

At least one of:

- `--all-accounts`
- `--account <local_account_key>` (repeatable)

### Output

Must log number of balances fetched per account.

---

## 6.7 `bankfetch transactions fetch`

### Purpose

Fetch transactions for one or more accounts, optionally for a specific date range.

### Behavior

The command must:

- validate active session
- determine date range from CLI args or checkpoint state
- fetch transactions page by page
- follow provider pagination / continuation mechanism until exhausted
- write raw payloads
- normalize transaction records
- deduplicate locally
- update per-account checkpoint only on success

### Arguments/options

Must support:

- `--all-accounts`
- `--account <local_account_key>` (repeatable)
- `--from YYYY-MM-DD`
- `--to YYYY-MM-DD`
- `--status booked|pending|both` (optional)
- `--no-checkpoint-update` (optional helper)

If `--from/--to` are omitted, the command must derive the fetch window from stored checkpoints using the configured overlap window.

---

## 6.8 `bankfetch sync run`

### Purpose

Primary cron-safe command.

### Behavior

This command orchestrates a full sync.

Required steps:

1. load config
2. acquire a process lock to avoid concurrent runs
3. generate fresh JWT
4. validate each selected active session
5. fetch balances for all active accounts in each selected session
6. fetch transactions incrementally for all active accounts in each selected session
7. write raw outputs
8. write normalized outputs
9. atomically update checkpoints only after success
10. emit summary log and exit

### Options

Must support at least:

- `--session <profile>` (repeatable, optional; defaults to all configured profiles)
- `--all-accounts`
- `--fail-fast / --no-fail-fast`
- `--dry-run` (optional helper)

### Exit behavior

Must distinguish between:

- full success
- partial success
- technical failure
- reauthorization required

---

## 7. Configuration

## 7.1 Config file location

Default config path:

```text
/etc/bankfetch/config.yaml
```

The CLI should also support:

```bash
bankfetch --config /custom/path/config.yaml ...
```

## 7.2 Required config fields

Example:

```yaml
app_name: bankfetch
provider: enable_banking

api:
  base_url: https://api.enablebanking.com
  app_id: YOUR_ENABLE_BANKING_APPLICATION_ID
  private_key_file: /etc/bankfetch/private.key
  timeout_seconds: 30

sessions:
  nordea:
    bank:
      aspsp:
        id: null
        name: Nordea
        country: DK
      psu_type: personal
      redirect_url: http://127.0.0.1:8787/callback
      consent_days: 90
  lunar:
    bank:
      aspsp:
        id: null
        name: Lunar
        country: DK
      psu_type: personal
      redirect_url: http://127.0.0.1:8787/callback
      consent_days: 90

sync:
  overlap_days: 3
  output_dir: /var/lib/bankfetch/out
  state_dir: /var/lib/bankfetch/state
  raw_archive: true
  normalized_format: jsonl

logging:
  format: json
  level: info

headers:
  psu_ip_address: null
  psu_user_agent: bankfetch/0.1
```

## 7.3 Config validation rules

The application must validate on startup:

- config file exists and is parseable
- private key file exists and is readable
- output/state directories exist or can be created
- `provider == enable_banking` in v1
- at least one session profile is configured
- consent days is positive
- overlap days is non-negative

---

## 8. Local filesystem layout

Default state layout:

```text
/var/lib/bankfetch/
  state/
    active_session_<profile>.json
    auth_init_<profile>.json
    checkpoints_<profile>.json
    lock/
  out/
    raw/
      balances/
      transactions/
    normalized/
      balances/
      transactions/
  logs/
```

The implementation may choose a slightly different layout, but it must preserve a clear distinction between:

- local state
- raw provider payloads
- normalized records

---

## 9. Data model requirements

Version 1 supports multiple named session profiles at runtime, and the stored data model must remain shaped for multi-bank support.

This means normalized records must include stable top-level fields that identify:

- provider
- bank / ASPSP
- session
- account
- fetch run

Do **not** design a file format that assumes only one bank globally.

---

## 10. Normalized identifiers

## 10.1 Provider key

For v1, always:

```json
"provider": "enable_banking"
```

## 10.2 Bank key

Must be represented explicitly, even in v1.

Example:

```json
"bank": {
  "aspsp_id": "nordea-dk",
  "display_name": "Nordea",
  "country_code": "DK"
}
```

If the provider returns a different canonical bank ID, prefer that over a locally guessed value.

## 10.3 Local account key

Each account must have a stable local key for file-based state.

Suggested format:

```text
enable_banking:<aspsp_id>:<provider_account_uid>
```

Example:

```text
enable_banking:nordea-dk:497f6eca-6276-4993-bfeb-53cbbbba6f08
```

This avoids redesign later when multiple banks and sessions are active in the same installation.

---

## 11. Required stored files and schemas

## 11.1 `active_session_<profile>.json`

Purpose: store the currently active session for one configured profile.

Example shape:

```json
{
  "provider": "enable_banking",
  "bank": {
    "aspsp_id": "nordea-dk",
    "display_name": "Nordea",
    "country_code": "DK"
  },
  "session": {
    "session_id": "SESSION_ID",
    "status": "AUTHORIZED",
    "valid_until": "2026-07-15T12:00:00Z",
    "created_at": "2026-04-17T06:00:00Z"
  },
  "accounts": [
    {
      "account_key": "enable_banking:nordea-dk:497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "provider_account_uid": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
      "display_name": "Lønkonto",
      "currency": "DKK",
      "account_type": "payment",
      "identifiers": {
        "iban_masked": "DK12************34"
      }
    }
  ]
}
```

## 11.2 `checkpoints_<profile>.json`

Purpose: store per-account sync progress for one configured profile.

Example shape:

```json
{
  "version": 1,
  "accounts": {
    "enable_banking:nordea-dk:497f6eca-6276-4993-bfeb-53cbbbba6f08": {
      "last_successful_sync_at": "2026-04-17T06:00:00Z",
      "last_booked_date": "2026-04-16",
      "last_pending_date": "2026-04-17",
      "last_fetch_from": "2026-04-13",
      "last_fetch_to": "2026-04-17"
    }
  }
}
```

## 11.3 Raw balance files

One file per fetch run per account is acceptable.

Recommended file naming pattern:

```text
raw/balances/YYYY/MM/DD/<account_key>/<fetch_timestamp>.json
```

## 11.4 Raw transaction files

Recommended file naming pattern:

```text
raw/transactions/YYYY/MM/DD/<account_key>/<fetch_timestamp>_page_<n>.json
```

## 11.5 Normalized balances

Must be append-friendly and easy to consume downstream.

Preferred format: JSON Lines.

Example record:

```json
{
  "record_type": "balance",
  "provider": "enable_banking",
  "bank": {
    "aspsp_id": "nordea-dk",
    "display_name": "Nordea",
    "country_code": "DK"
  },
  "session_id": "SESSION_ID",
  "account_key": "enable_banking:nordea-dk:497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "provider_account_uid": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "fetched_at": "2026-04-17T06:00:00Z",
  "balance_type": "CLAV",
  "balance_name": "Booked balance",
  "amount": "12345.67",
  "currency": "DKK",
  "credit_debit_indicator": "CRDT",
  "reference_date": "2026-04-17",
  "provider_payload_version": 1
}
```

## 11.6 Normalized transactions

Preferred format: JSON Lines.

Example record:

```json
{
  "record_type": "transaction",
  "provider": "enable_banking",
  "bank": {
    "aspsp_id": "nordea-dk",
    "display_name": "Nordea",
    "country_code": "DK"
  },
  "session_id": "SESSION_ID",
  "account_key": "enable_banking:nordea-dk:497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "provider_account_uid": "497f6eca-6276-4993-bfeb-53cbbbba6f08",
  "fetched_at": "2026-04-17T06:00:00Z",
  "transaction_id": "abc123",
  "entry_reference": "5561990681",
  "transaction_status": "BOOK",
  "booking_date": "2026-04-16",
  "value_date": "2026-04-16",
  "amount": "-249.95",
  "currency": "DKK",
  "credit_debit_indicator": "DBIT",
  "counterparty_name": "NETS*FOETEX",
  "remittance_information": "KORTKØB",
  "proprietary_bank_transaction_code": null,
  "provider_payload_version": 1,
  "dedupe_key": "sha256:..."
}
```

---

## 12. Deduplication rules

Transactions may be fetched more than once due to overlap windows and reruns.

The implementation must deduplicate normalized transaction records before appending or publishing them as the latest normalized view.

### 12.1 Preferred dedupe strategy

Use provider-native transaction identifier if available.

Suggested priority order:

1. `transaction_id`
2. provider-specific unique reference if stable
3. fallback content hash over stable fields

### 12.2 Fallback dedupe key

If no stable provider ID exists, compute a SHA-256 hash over a canonical concatenation of fields such as:

- provider
- bank ASPSP ID
- provider account UID
- booking date
- value date
- amount
- currency
- credit/debit indicator
- counterparty name
- remittance information
- entry reference

The same dedupe key algorithm must be used consistently across runs.

---

## 13. Incremental sync rules

The sync logic must support incremental transaction fetching.

### 13.1 Initial sync

If an account has no checkpoint yet:

- require explicit `--from` for the first transaction fetch, or
- allow a configured default lookback window if implemented

For v1, the simplest acceptable behavior is:

- `transactions fetch` without checkpoint and without `--from` fails with a clear error
- `sync run` without checkpoints may use a configured `initial_lookback_days` if the implementer adds it

### 13.2 Recurring sync

For recurring syncs:

- derive `from_date = last_booked_date - overlap_days`
- derive `to_date = today`
- fetch entire range
- deduplicate locally
- update checkpoint only after full success for that account

### 13.3 Pending transactions

If the provider exposes pending transactions, the implementation should track them separately where practical.

At minimum, checkpoint format must allow both:

- `last_booked_date`
- `last_pending_date`

---

## 14. Concurrency and locking

The application must guard against concurrent sync runs.

### Requirements

- `sync run` must acquire a lock before starting
- if a lock already exists and appears active, the command must fail cleanly
- stale lock handling may be added if useful

Acceptable approaches:

- lock file
- file lock
- PID-based lock metadata

Exit with a dedicated non-zero code on lock contention.

---

## 15. Logging and observability

All commands must emit structured logs.

### Log format

Preferred format: one JSON object per line.

Example:

```json
{"level":"info","event":"sync_started","ts":"2026-04-17T06:00:00Z"}
{"level":"info","event":"balances_fetched","account_key":"enable_banking:nordea-dk:...","count":2}
{"level":"info","event":"transactions_fetched","account_key":"enable_banking:nordea-dk:...","count":84,"pages":3}
{"level":"info","event":"sync_completed","duration_ms":8421}
```

### Logging requirements

Must never log:

- private key contents
- raw JWT token
- full Authorization header
- full unmasked account identifiers unless debug mode explicitly allows it
- secrets from config

---

## 16. Security requirements

### 16.1 Secrets

Secrets include:

- provider application ID where relevant
- private signing key
- session identifiers if treated as sensitive
- any persisted auth-init temporary state

### 16.2 File permissions

The coding agent should implement or document expected file permissions for:

- config directory
- private key file
- state directory
- output directory

### 16.3 Error handling

API errors must be surfaced without leaking secrets.

Error messages should include enough context to troubleshoot:

- command
- account or session involved
- HTTP status code
- provider error code/message where available

---

## 17. Exit codes

The CLI must use stable exit codes.

Recommended set:

```text
0   Success
10  Configuration error
11  JWT/signing error
12  API authentication/authorization error
13  Session invalid or unusable
14  Remote API/network/timeout error
15  Data validation or normalization error
16  Partial sync failure
17  Lock contention / concurrent run
20  Reauthorization required
```

---

## 18. Error-handling requirements

### 18.1 Fail-fast vs partial mode

`sync run` should support two modes:

- fail-fast: abort on first account failure
- continue mode: continue other accounts and return partial-failure exit code if any fail

Default behavior for v1:

- continue mode preferred
- exit `16` if at least one account failed but at least one succeeded

### 18.2 Atomic checkpoint update

Checkpoint updates must be atomic per account or per completed sync run.

A failed run must not advance the checkpoint past data that was not safely written.

---

## 19. Cron usage requirements

The tool is explicitly intended for cron.

### Requirements

- non-interactive commands must never wait for user input
- all commands must produce deterministic exit codes
- sync command must be safe to run repeatedly
- logs must go to stdout/stderr cleanly

### Example cron entry

```cron
17 */6 * * * /usr/local/bin/bankfetch sync run --all-accounts >> /var/log/bankfetch.log 2>&1
```

---

## 20. Acceptance criteria

The implementation is acceptable for v1 when all of the following are true.

### 20.1 Authorization flow

- operator can run `bankfetch auth init --session <profile>`
- CLI outputs a bank authorization URL
- operator can complete bank authorization manually
- operator can run `bankfetch auth complete --session <profile> --code ...`
- active session is stored locally per profile

### 20.2 Session status

- `bankfetch session status --session <profile>` reports usable vs unusable session correctly
- command returns exit code `20` when reauthorization is required

### 20.3 Account listing

- `bankfetch accounts list --session <profile>` prints accounts from the active session
- each account has a stable future-proof `account_key`

### 20.4 Balance fetch

- `bankfetch balances fetch --session <profile> --all-accounts` fetches balances for all accounts
- raw files are stored
- normalized balance records are written with provider and bank identifiers included

### 20.5 Transaction fetch

- `bankfetch transactions fetch --session <profile> --all-accounts --from YYYY-MM-DD --to YYYY-MM-DD` fetches all pages of transactions
- raw payloads are archived
- normalized transaction records are written
- rerunning with overlapping dates does not produce duplicates in the latest normalized view

### 20.6 Sync run

- `bankfetch sync run --all-accounts` can run unattended from cron across all configured profiles
- concurrent execution is prevented by locking
- checkpoints are updated only after successful writes
- logs are structured
- exit codes are stable and meaningful

---

## 21. Suggested implementation order

1. config loading and validation
2. JWT signing helper
3. thin Enable Banking client
4. `auth init`
5. `auth complete`
6. `session status`
7. `accounts list`
8. `balances fetch`
9. `transactions fetch` with pagination
10. normalization + dedupe
11. `sync run`
12. locking + structured logging + exit code polishing

---

## 22. Nice-to-have helpers

These are optional but useful:

- `--format json` for machine-readable command output
- `--verbose`
- `--dry-run`
- `bankfetch doctor` to validate local config/state
- `bankfetch export latest` to materialize a deduplicated latest-view file per account

---

## 23. Deliverables expected from the coding agent

The coding agent should produce:

1. Python project source code
2. CLI implementation
3. sample config file
4. README with setup and cron examples
5. implementation notes about security assumptions
6. tests for:
   - config validation
   - dedupe logic
   - checkpoint behavior
   - lock handling
   - normalization shape

---

## 24. Implementation note to the coding agent

Even though v1 is limited to Enable Banking, **all normalized records and internal account identifiers must already include provider and bank identity** so that a future v2 can support multiple banks without breaking stored file formats.

That requirement is mandatory and should take precedence over simplistic v1-only shortcuts.

# Route 53 DNS Inventory

DNS asset visibility tooling for AWS Route 53. Runs as a scheduled Lambda — queries every hosted zone, filters to scope, and produces dated PDF and CSV reports stored in S3.

Supports compliance asset inventories, attack surface reviews, and firewall baseline documentation.

---

## Scripts

### `dns_inventory.py`
Full record-type inventory (A, CNAME, MX, TXT, ALIAS, etc.) across all hosted zones. Filters to `.gov` scope, deduplicates, and outputs:

- Per-domain PDF and CSV
- Summary index — all domains and record counts in one view
- Combined full report — every domain in a single file

### `external_ips.py`
Resolves `.gov` A records live via DNS lookup. Classifies each resolved IP as **public** (internet-routable) or private, and computes a covering CIDR block per hostname.

Use this to enumerate internet-exposed endpoints and build firewall or attack surface baselines.

---

## How It Works

```
EventBridge (scheduled trigger)
        │
        ▼
  AWS Lambda
        │
        ├── Query Route 53 API  (paginated, all hosted zones)
        ├── Filter and deduplicate records
        ├── Generate PDF + CSV reports
        └── Upload to S3  (organized by domain, date-stamped)
```

---

## Setup

**Requirements:** Python 3.11 · AWS credentials · S3 bucket for report storage

### 1. Package dependencies

```powershell
python -m pip install reportlab `
  --target .\package `
  --platform manylinux2014_x86_64 `
  --only-binary=:all: `
  --python-version 3.11 `
  --implementation cp `
  --abi cp311
```

### 2. Build the deployment zip

```bash
zip -r route53-report.zip dns_inventory.py external_ips.py package/
```

### 3. Configure Lambda

| Setting | Value |
|---|---|
| Runtime | Python 3.11 |
| Handler — `dns_inventory.py` | `dns_inventory.lambda_handler` |
| Handler — `external_ips.py` | `external_ips.lambda_handler` |

**Environment variables**

| Variable | Required | Default | Description |
|---|---|---|---|
| `S3_BUCKET` | Yes | — | Destination bucket for reports |
| `S3_PREFIX` | No | `reports` | S3 path prefix |

### 4. IAM permissions

Attach [`policy.json`](policy.json) to the Lambda execution role.

The policy is least-privilege: read-only on Route 53, write-only to the designated reports prefix in S3.

---

## S3 Output Structure

```
reports/
├── _index/      ← Summary index (all domains + record counts)
├── _full/       ← Combined report (all domains in one file)
├── _gov-ips/    ← Public IP reports  (external_ips.py)
└── <domain>/    ← Per-domain PDF + CSV  (dns_inventory.py)
```

Each run produces files date-stamped with the current date.

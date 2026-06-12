# Route 53 DNS Inventory

Automated tooling for auditing DNS records in AWS Route 53. Runs as a scheduled AWS Lambda function — pulls every hosted zone record, filters to `.gov` scope, and produces dated PDF and CSV reports stored in S3.

---

## Tools

### `dns_inventory.py` — Full DNS Record Inventory
Queries all record types (A, CNAME, MX, TXT, ALIAS, etc.) across every hosted zone. Filters to `.gov` scope, deduplicates, and generates:

- A per-domain PDF and CSV
- A summary index listing every domain and its record count
- A combined full report across all domains

### `external_ips.py` — Public IP Resolver
Pulls `.gov` A records from Route 53 and performs live DNS resolution on each hostname. Classifies IPs as **public** (internet-routable) or private, and computes the covering CIDR block per record.

Useful for identifying exposed endpoints and supporting firewall or attack-surface reviews.

---

## Architecture

```
EventBridge (cron schedule)
        │
        ▼
  AWS Lambda
        │
        ├─ Query Route 53 (all hosted zones + record sets)
        ├─ Filter to .gov scope
        ├─ Generate PDF + CSV reports
        └─ Upload to S3
```

---

## Deployment

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

### 2. Create the deployment zip

```bash
zip -r route53-report.zip dns_inventory.py external_ips.py package/
```

### 3. Configure Lambda

| Setting | Value |
|---|---|
| Runtime | Python 3.11 |
| Handler (`dns_inventory.py`) | `dns_inventory.lambda_handler` |
| Handler (`external_ips.py`) | `external_ips.lambda_handler` |

**Environment variables:**

| Variable | Required | Default | Description |
|---|---|---|---|
| `S3_BUCKET` | Yes | — | Bucket where reports are written |
| `S3_PREFIX` | No | `reports` | S3 path prefix for all output |

### 4. Attach the IAM policy

Attach [`policy.json`](policy.json) to the Lambda execution role.

The policy is **least-privilege**: read-only on Route 53, write-only to the designated reports prefix in S3.

---

## S3 Output Structure

```
reports/
├── _index/        ← Summary index (all domains + counts)
├── _full/         ← Combined report (all domains in one file)
├── _gov-ips/      ← Public IP reports (external_ips.py)
└── <domain>/      ← Per-domain reports (dns_inventory.py)
```

Each run produces files stamped with the current date (e.g., `route53_records_<domain>_2025-01-15.pdf`).

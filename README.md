# Route 53 DNS Inventory

[![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python&logoColor=white)](https://www.python.org/)
[![AWS Lambda](https://img.shields.io/badge/AWS-Lambda-FF9900?logo=awslambda&logoColor=white)](https://aws.amazon.com/lambda/)
[![AWS Route 53](https://img.shields.io/badge/AWS-Route%2053-8C4FFF?logo=amazonroute53&logoColor=white)](https://aws.amazon.com/route53/)

Automated DNS asset inventory for AWS Route 53. A scheduled Lambda function that queries every hosted zone, filters records to scope, and delivers dated PDF and CSV reports to S3.

> Supports DNS visibility programs, compliance asset inventories, and attack surface documentation.

---

## Tools

| Script | Purpose |
|---|---|
| [`dns_inventory.py`](#dns_inventorypy) | Full DNS record inventory across all record types, with per-domain and combined reports |
| [`external_ips.py`](#external_ipspy) | Live A record resolution — maps hostnames to their public IPs and CIDR blocks |

---

### `dns_inventory.py`

Inventories all record types (A, CNAME, MX, TXT, ALIAS, etc.) across every hosted zone. Filters to scope, deduplicates, and generates:

- **Per-domain PDF and CSV** — one report set per root domain
- **Summary index** — all domains and record counts in a single view
- **Combined full report** — every domain in one document

---

### `external_ips.py`

Pulls A records from Route 53 then performs live DNS resolution on each hostname. For every record that resolves to a public IP:

- Classifies the address as **public** (internet-routable) vs. private
- Computes the tightest CIDR block spanning all resolved IPs for that record
- Outputs a dated PDF and CSV: hostname → IP(s) → CIDR

Useful for attack surface enumeration, firewall baselining, and identifying internet-exposed endpoints.

---

## How It Works

```
EventBridge  (cron schedule)
      │
      ▼
AWS Lambda
      │
      ├─ 1. Fetch    →  list all hosted zones + record sets via Route 53 API (paginated)
      ├─ 2. Filter   →  scope to target domains, drop noise
      ├─ 3. Process  →  deduplicate values, group by root domain
      ├─ 4. Report   →  generate PDF + CSV (per-domain, index, and full)
      └─ 5. Deliver  →  upload to S3, organized by domain and date
```

---

## Deployment

### Prerequisites

- Python 3.11
- AWS account with Route 53 hosted zones
- S3 bucket for report storage
- Lambda execution role with [`policy.json`](policy.json) attached

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

### 3. Configure the Lambda function

| Setting | Value |
|---|---|
| Runtime | Python 3.11 |
| Handler — `dns_inventory.py` | `dns_inventory.lambda_handler` |
| Handler — `external_ips.py` | `external_ips.lambda_handler` |

**Environment variables**

| Variable | Required | Default | Description |
|---|---|---|---|
| `S3_BUCKET` | Yes | — | S3 bucket for report output |
| `S3_PREFIX` | No | `reports` | Folder prefix within the bucket |

### 4. IAM permissions

Attach [`policy.json`](policy.json) to the Lambda execution role.

Scoped to the minimum required:
- `route53:ListHostedZones` + `route53:ListResourceRecordSets` — read-only
- `s3:PutObject` — write access restricted to the reports prefix only

---

## S3 Output Structure

```
reports/
├── _index/      ←  Summary index: all domains and record counts
├── _full/       ←  Combined report: every domain in one document
├── _gov-ips/    ←  Public IP inventory  (external_ips.py)
└── <domain>/    ←  Per-domain PDF + CSV  (dns_inventory.py)
```

All files are date-stamped on each run.

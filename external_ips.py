#!/usr/bin/env python3
"""
Route 53 .gov A-Record IPv4 Inventory
=====================================
Pulls every .gov A record from Route 53, performs a live nslookup on each
record name, and reports the resolved IPv4 addresses. Each IP is tagged
external (public / internet-routable) or internal (private), which is the
key distinction for attack-surface review.

Runs locally (python3 external_ips.py) or as Lambda
(handler = external_ips.lambda_handler).
"""

import csv
import ipaddress
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import boto3
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer


# ---------------------------------------------------------------- Config

DOMAIN_SUFFIX = ".gov"            # .gov only
PUBLIC_ONLY = True                # keep only internet-routable (public) IPs
socket.setdefaulttimeout(3)       # per-lookup DNS timeout

CSV_FIELDS = ["record_name", "ipv4", "cidr"]


# ---------------------------------------------------------------- Route 53

def fetch_a_record_names():
    """Return a de-duplicated list of .gov A-record names."""
    r53 = boto3.client("route53")

    seen = set()
    names = []

    zone_pages = r53.get_paginator("list_hosted_zones").paginate()
    for zone_page in zone_pages:
        for zone in zone_page["HostedZones"]:
            zone_id = zone["Id"].split("/")[-1]

            rec_pages = r53.get_paginator(
                "list_resource_record_sets"
            ).paginate(HostedZoneId=zone_id)

            for rec_page in rec_pages:
                for rec in rec_page["ResourceRecordSets"]:
                    if rec["Type"] != "A":
                        continue

                    name = rec["Name"].rstrip(".").replace("\\052", "*")

                    if not name.lower().endswith(DOMAIN_SUFFIX):
                        continue
                    if "*" in name:          # wildcards can't be resolved
                        continue

                    if name not in seen:
                        seen.add(name)
                        names.append(name)

    return names


# ---------------------------------------------------------------- nslookup + classify

def resolve_ipv4(name):
    """Forward DNS lookup -> sorted unique IPv4 list (or [] on failure)."""
    try:
        _, _, ips = socket.gethostbyname_ex(name)
        return sorted(set(ips))
    except (socket.gaierror, socket.timeout, OSError):
        return []


def is_public(ip):
    """True if the IP is globally routable (not private/reserved)."""
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def smallest_cidr(ips):
    """Smallest single CIDR block that covers all of a record's IPs."""
    ints = [int(ipaddress.ip_address(ip)) for ip in ips]
    if len(ints) == 1:
        return f"{ips[0]}/32"
    lo, hi = min(ints), max(ints)
    prefix = 32 - (lo ^ hi).bit_length()
    return str(ipaddress.ip_network((lo, prefix), strict=False))


def build_rows(names):
    rows = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        results = pool.map(lambda n: (n, resolve_ipv4(n)), names)

    for name, ips in results:
        # Keep only the public IPs for this record.
        keep = [ip for ip in ips if not (PUBLIC_ONLY and not is_public(ip))]
        if not keep:
            continue

        # Sort low -> high so the cell reads first..last.
        keep = sorted(keep, key=lambda ip: int(ipaddress.ip_address(ip)))

        rows.append({
            "record_name": name,
            "ipv4": " | ".join(keep),     # all IPs in one cell
            "cidr": smallest_cidr(keep),  # block spanning first..last
        })

    return sorted(rows, key=lambda r: r["record_name"])


# ---------------------------------------------------------------- CSV

def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[+] CSV written: {path} ({len(rows)} IPs)")


# ---------------------------------------------------------------- PDF

def build_pdf(rows, out_path):
    doc = SimpleDocTemplate(
        out_path, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        title="Route 53 .gov A-Record IPv4 Inventory",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], textColor=colors.black)
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"], alignment=1,
        fontSize=11, textColor=colors.black)
    cell = ParagraphStyle(
        "cell", parent=styles["Normal"], fontSize=9, leading=12,
        textColor=colors.black)

    table_style = TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10.5),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])

    story = []
    story.append(Paragraph(date.today().strftime("%B %d, %Y"), title_style))
    story.append(Paragraph(
        "Public Facing IPs (.gov)", subtitle_style))
    story.append(Spacer(1, 16))

    data = [["Record", "IPv4", "CIDR"]]
    for r in rows:
        stacked = r["ipv4"].replace(" | ", "<br/>")
        data.append([
            Paragraph(r["record_name"], cell),
            Paragraph(stacked, cell),
            r["cidr"],
        ])

    table = Table(
        data,
        colWidths=[3.4 * inch, 1.8 * inch, 1.8 * inch],
        repeatRows=1, hAlign="CENTER",
    )
    table.setStyle(table_style)

    story.append(table)
    doc.build(story)
    print(f"[+] PDF written: {out_path}")


# ---------------------------------------------------------------- S3

def upload_to_s3(file_path, bucket, key):
    s3 = boto3.client("s3")
    s3.upload_file(file_path, bucket, key)
    print(f"[+] Uploaded to s3://{bucket}/{key}")


# ---------------------------------------------------------------- Workflow

def run(output_dir, s3_bucket=None, prefix="reports", upload=True, stamp=None):
    print("[*] Starting Route 53 .gov A-record IPv4 lookup")

    if stamp is None:
        stamp = date.today().strftime("%Y-%m-%d")

    os.makedirs(output_dir, exist_ok=True)

    names = fetch_a_record_names()
    if not names:
        print("[!] No .gov A records found")
        return {"status": "no_a_records_found"}

    rows = build_rows(names)

    base = f"route53_gov_ips_{stamp}"
    pdf_path = os.path.join(output_dir, f"{base}.pdf")
    csv_path = os.path.join(output_dir, f"{base}.csv")

    build_pdf(rows, pdf_path)
    write_csv(rows, csv_path)

    pdf_key = f"{prefix}/_gov-ips/{base}.pdf"
    csv_key = f"{prefix}/_gov-ips/{base}.csv"

    if upload and s3_bucket:
        upload_to_s3(file_path=pdf_path, bucket=s3_bucket, key=pdf_key)
        upload_to_s3(file_path=csv_path, bucket=s3_bucket, key=csv_key)

    total_ips = sum(len(r["ipv4"].split(" | ")) for r in rows)
    print(f"[*] {len(names)} names -> {len(rows)} records, {total_ips} IPs")
    print("[+] Completed successfully")

    return {
        "status": "success",
        "a_records": len(names),
        "records_with_ips": len(rows),
        "ips": total_ips,
        "s3_bucket": s3_bucket,
        "pdf": pdf_path,
        "csv": csv_path,
    }


# ---------------------------------------------------------------- Lambda

def lambda_handler(event, context):
    s3_bucket = os.environ["S3_BUCKET"]
    prefix = os.environ.get("S3_PREFIX", "reports")
    return run(output_dir="/tmp", s3_bucket=s3_bucket,
               prefix=prefix, upload=True)


# ---------------------------------------------------------------- Local

if __name__ == "__main__":
    bucket = os.environ.get("S3_BUCKET", "REPLACE_WITH_YOUR_BUCKET_NAME")
    prefix = os.environ.get("S3_PREFIX", "reports")

    result = run(
        output_dir="aws-route53-gov-ips",
        s3_bucket=bucket,
        prefix=prefix,
        upload=bool(bucket),
    )
    print(result)

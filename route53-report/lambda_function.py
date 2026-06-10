#!/usr/bin/env python3

import csv
import os
from collections import defaultdict
from datetime import date

import boto3
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer


CSV_FIELDS = ["record_name", "record_type", "value"]


# ---------------------------------------------------------------- AWS Route 53 Fetch

def fetch_from_aws():
    r53 = boto3.client("route53")

    rows = []

    zone_pages = r53.get_paginator("list_hosted_zones").paginate()

    for zone_page in zone_pages:
        for zone in zone_page["HostedZones"]:
            zone_id = zone["Id"].split("/")[-1]

            rec_pages = r53.get_paginator(
                "list_resource_record_sets"
            ).paginate(HostedZoneId=zone_id)

            for rec_page in rec_pages:
                for rec in rec_page["ResourceRecordSets"]:
                    name = rec["Name"].rstrip(".").replace("\\052", "*")
                    rtype = rec["Type"]

                    if "AliasTarget" in rec:
                        target = rec["AliasTarget"]["DNSName"].rstrip(".")
                        rows.append({
                            "record_name": name,
                            "record_type": rtype,
                            "value": f"ALIAS -> {target}"
                        })
                    else:
                        for rr in rec.get("ResourceRecords", []):
                            rows.append({
                                "record_name": name,
                                "record_type": rtype,
                                "value": str(rr["Value"])
                            })

    return rows


# ---------------------------------------------------------------- CSV

def write_csv(rows, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[+] CSV written: {path} ({len(rows)} rows)")


# ---------------------------------------------------------------- Filtering

def base_domain(record_name):
    parts = record_name.rstrip(".").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else record_name


def group_gov(rows):
    merged = defaultdict(list)

    for row in rows:
        name = row["record_name"].strip().rstrip(".")

        if not name.lower().endswith(".gov"):
            continue

        key = (
            base_domain(name),
            name,
            row["record_type"].strip()
        )

        for v in row["value"].split(" | "):
            v = v.strip()

            if v and v not in merged[key]:
                merged[key].append(v)

    grouped = defaultdict(list)

    for (domain, name, rtype), values in merged.items():
        grouped[domain].append((name, rtype, values))

    return grouped


# ---------------------------------------------------------------- PDF

def build_pdf(grouped, out_path):
    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="AWS Automated Route 53 Inventory Records",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "title",
        parent=styles["Title"],
        textColor=colors.black
    )

    subtitle_style = ParagraphStyle(
        "subtitle",
        parent=styles["Normal"],
        alignment=1,
        fontSize=11,
        textColor=colors.black
    )

    cell = ParagraphStyle(
        "cell",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=colors.black
    )

    table_style = TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10.5),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),

        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("LINEBELOW", (0, 1), (-1, 1), 1.2, colors.black),

        ("FONTNAME", (0, 2), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),

        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ])

    story = []

    story.append(Paragraph(date.today().strftime("%B %d, %Y"), title_style))
    story.append(Paragraph("AWS Automated Route 53 Inventory Records", subtitle_style))
    story.append(Spacer(1, 16))

    for domain in sorted(grouped):
        records = sorted(grouped[domain], key=lambda r: (r[1], r[0]))

        data = [
            [domain, "", ""],
            ["Record", "Type", "Value"]
        ]

        for name, rtype, values in records:
            stacked = "<br/>".join(values)

            data.append([
                Paragraph(name, cell),
                rtype,
                Paragraph(stacked, cell)
            ])

        table = Table(
            data,
            colWidths=[2.4 * inch, 0.7 * inch, 3.9 * inch],
            repeatRows=2,
            hAlign="CENTER"
        )

        table.setStyle(table_style)

        story.append(table)
        story.append(Spacer(1, 18))

    doc.build(story)

    print(f"[+] PDF written: {out_path}")


# ---------------------------------------------------------------- S3 Upload

def upload_to_s3(file_path, bucket, key):
    s3 = boto3.client("s3")

    s3.upload_file(file_path, bucket, key)

    print(f"[+] Uploaded to s3://{bucket}/{key}")


# ---------------------------------------------------------------- Lambda Handler

def lambda_handler(event, context):
    print("[*] Starting Route 53 .gov DNS inventory report")

    output_pdf = "/tmp/gov_dns_report.pdf"
    output_csv = "/tmp/route53_records.csv"

    s3_bucket = os.environ["S3_BUCKET"]
    s3_key = os.environ.get("S3_KEY", "reports/gov_dns_report.pdf")

    rows = fetch_from_aws()

    if not rows:
        print("[!] No Route 53 records found")
        return {
            "status": "no_records_found"
        }

    write_csv(rows, output_csv)

    grouped = group_gov(rows)

    if not grouped:
        print("[!] No .gov records found")
        return {
            "status": "no_gov_records_found"
        }

    total_records = sum(len(v) for v in grouped.values())

    print(
        f"[*] Kept {total_records} .gov records "
        f"across {len(grouped)} domains"
    )

    build_pdf(grouped, output_pdf)

    upload_to_s3(
        file_path=output_pdf,
        bucket=s3_bucket,
        key=s3_key
    )

    print("[+] Lambda completed successfully")

    return {
        "status": "success",
        "gov_domains": len(grouped),
        "gov_records": total_records,
        "s3_bucket": s3_bucket,
        "s3_key": s3_key
    }
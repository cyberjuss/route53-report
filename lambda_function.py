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


def records_to_rows(records):
    """Flatten a single domain's grouped records back into flat CSV rows."""
    out = []
    for name, rtype, values in records:
        for v in values:
            out.append({
                "record_name": name,
                "record_type": rtype,
                "value": v,
            })
    return out


INDEX_FIELDS = ["domain", "gov_records", "pdf_file", "csv_file"]


def write_index_csv(produced, path):
    """Write a top-level summary CSV: one row per domain."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        for d in produced:
            writer.writerow({
                "domain": d["domain"],
                "gov_records": d["records"],
                "pdf_file": os.path.basename(d["pdf"]),
                "csv_file": os.path.basename(d["csv"]),
            })

    print(f"[+] Index CSV written: {path} ({len(produced)} domains)")


# ---------------------------------------------------------------- Filtering

def base_domain(record_name):
    parts = record_name.rstrip(".").lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else record_name


EXCLUDED_SUFFIXES = (".internal", ".com")


def drop_excluded(rows):
    kept = []
    for row in rows:
        name = row["record_name"].strip().rstrip(".").lower()
        if name.endswith(EXCLUDED_SUFFIXES):
            continue
        kept.append(row)
    return kept


def group_gov(rows):
    merged = defaultdict(list)

    for row in rows:
        name = row["record_name"].strip().rstrip(".")
        lower = name.lower()

        # Keep only .gov, and explicitly drop .internal / .com
        if not lower.endswith(".gov"):
            continue

        if lower.endswith(EXCLUDED_SUFFIXES):
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

def build_domain_pdf(domain, records, out_path):
    """Build a PDF containing the records for ONE domain."""
    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=f"Route 53 Inventory - {domain}",
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
    story.append(Paragraph(
        f"AWS Route 53 Inventory Records - {domain}", subtitle_style))
    story.append(Spacer(1, 16))

    records = sorted(records, key=lambda r: (r[1], r[0]))

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

    doc.build(story)

    print(f"[+] PDF written: {out_path}")


def build_index_pdf(produced, out_path):
    """Build a one-page summary PDF listing every domain and its count."""
    doc = SimpleDocTemplate(
        out_path,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="Route 53 Inventory - Summary Index",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "title", parent=styles["Title"], textColor=colors.black)
    subtitle_style = ParagraphStyle(
        "subtitle", parent=styles["Normal"], alignment=1,
        fontSize=11, textColor=colors.black)

    table_style = TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10.5),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.black),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])

    story = []
    story.append(Paragraph(date.today().strftime("%B %d, %Y"), title_style))
    story.append(Paragraph(
        "AWS Route 53 Inventory - Summary Index", subtitle_style))
    story.append(Spacer(1, 16))

    data = [["Domain", "Records"]]
    for d in produced:
        data.append([d["domain"], str(d["records"])])
    data.append(["TOTAL", str(sum(d["records"] for d in produced))])

    table = Table(data, colWidths=[5.0 * inch, 2.0 * inch], hAlign="CENTER")
    table.setStyle(table_style)
    # Bold the TOTAL row
    table.setStyle(TableStyle([
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1.0, colors.black),
    ]))

    story.append(table)

    doc.build(story)

    print(f"[+] Index PDF written: {out_path}")


# ---------------------------------------------------------------- S3 Upload

def upload_to_s3(file_path, bucket, key):
    s3 = boto3.client("s3")

    s3.upload_file(file_path, bucket, key)

    print(f"[+] Uploaded to s3://{bucket}/{key}")


# ---------------------------------------------------------------- Core Workflow

def run_report(output_dir, s3_bucket=None, prefix="reports",
               upload=True, stamp=None):
    print("[*] Starting Route 53 .gov DNS inventory report")

    if stamp is None:
        stamp = date.today().strftime("%Y-%m-%d")

    os.makedirs(output_dir, exist_ok=True)

    rows = fetch_from_aws()

    if not rows:
        print("[!] No Route 53 records found")
        return {"status": "no_records_found"}

    rows = drop_excluded(rows)

    grouped = group_gov(rows)

    if not grouped:
        print("[!] No .gov records found")
        return {"status": "no_gov_records_found"}

    produced = []

    # One PDF + one CSV per domain.
    for domain in sorted(grouped):
        records = grouped[domain]

        base_name = f"route53_records_{domain}_{stamp}"

        pdf_path = os.path.join(output_dir, f"{base_name}.pdf")
        csv_path = os.path.join(output_dir, f"{base_name}.csv")

        build_domain_pdf(domain, records, pdf_path)
        write_csv(records_to_rows(records), csv_path)

        pdf_key = f"{prefix}/{domain}/{base_name}.pdf"
        csv_key = f"{prefix}/{domain}/{base_name}.csv"

        if upload and s3_bucket:
            upload_to_s3(file_path=pdf_path, bucket=s3_bucket, key=pdf_key)
            upload_to_s3(file_path=csv_path, bucket=s3_bucket, key=csv_key)

        produced.append({
            "domain": domain,
            "records": sum(len(v) for _, _, v in records),
            "pdf": pdf_path,
            "csv": csv_path,
            "s3_pdf_key": pdf_key if (upload and s3_bucket) else None,
            "s3_csv_key": csv_key if (upload and s3_bucket) else None,
        })

    total_records = sum(d["records"] for d in produced)

    # Top-level summary index (PDF + CSV) listing every domain.
    index_base = f"route53_index_{stamp}"
    index_pdf_path = os.path.join(output_dir, f"{index_base}.pdf")
    index_csv_path = os.path.join(output_dir, f"{index_base}.csv")

    build_index_pdf(produced, index_pdf_path)
    write_index_csv(produced, index_csv_path)

    index_pdf_key = f"{prefix}/{index_base}.pdf"
    index_csv_key = f"{prefix}/{index_base}.csv"

    if upload and s3_bucket:
        upload_to_s3(file_path=index_pdf_path, bucket=s3_bucket, key=index_pdf_key)
        upload_to_s3(file_path=index_csv_path, bucket=s3_bucket, key=index_csv_key)

    print(
        f"[*] Wrote {len(produced)} domain reports "
        f"({total_records} .gov records total)"
    )

    print("[+] Report completed successfully")

    return {
        "status": "success",
        "gov_domains": len(produced),
        "gov_records": total_records,
        "s3_bucket": s3_bucket,
        "index_pdf": index_pdf_path,
        "index_csv": index_csv_path,
        "files": produced,
    }


# ---------------------------------------------------------------- Lambda Handler

def lambda_handler(event, context):
    s3_bucket = os.environ["S3_BUCKET"]
    prefix = os.environ.get("S3_PREFIX", "reports")

    return run_report(
        output_dir="/tmp",
        s3_bucket=s3_bucket,
        prefix=prefix,
        upload=True,
    )


# ---------------------------------------------------------------- Local Entry Point

if __name__ == "__main__":
    # Replace the placeholder below with your real bucket name, or override
    # it at runtime with:  export S3_BUCKET=my-bucket-name
    bucket = os.environ.get("S3_BUCKET", "REPLACE_WITH_YOUR_BUCKET_NAME")
    prefix = os.environ.get("S3_PREFIX", "reports")

    result = run_report(
        output_dir="reports_out",
        s3_bucket=bucket,
        prefix=prefix,
        upload=bool(bucket),
    )

    print(result)

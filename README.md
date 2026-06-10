python -m pip install reportlab `
  --target .\package `
  --platform manylinux2014_x86_64 `
  --only-binary=:all: `
  --python-version 3.11 `
  --implementation cp `
  --abi cp311 `
  --no-user



{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Route53ReadAccess",
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:ListResourceRecordSets"
      ],
      "Resource": "*"
    },
    {
      "Sid": "UploadReportToS3",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/reports/*"
    }
  ]
}

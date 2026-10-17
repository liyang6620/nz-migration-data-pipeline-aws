"""AWS Glue 5.0 job for one immutable NZ migration release."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote_plus

LANDING_KEY_PATTERN = re.compile(
    r"^landing/dataset=migration/"
    r"snapshot_month=(?P<snapshot_month>\d{4}-(?:0[1-9]|1[0-2]))/"
    r"release_id=(?P<release_id>[A-Za-z0-9._-]{1,200})/source\.csv$"
)
SOURCE_COLUMNS = (
    "year_month",
    "month_of_release",
    "passenger_type",
    "direction",
    "citizenship",
    "visa",
    "country_of_residence",
    "estimate",
    "standard_error",
    "status",
)
DIMENSIONS = ("citizenship", "visa", "country_of_residence")
BUSINESS_KEY = (
    "snapshot_month",
    "year_month",
    "passenger_type",
    "direction",
    *DIMENSIONS,
)
REVISION_KEY = BUSINESS_KEY[1:]
COMPARE_COLUMNS = (
    "source_release_month",
    "metric_slice",
    "estimate",
    "standard_error",
    "status",
)
METRIC_SLICES = (
    "total",
    "citizenship",
    "visa",
    "country_of_residence",
    "citizenship_visa",
    "citizenship_country_of_residence",
    "visa_country_of_residence",
    "citizenship_visa_country_of_residence",
)
SCHEMA_VERSION = "1.0.0"
MAX_SOURCE_BYTES = 200 * 1024 * 1024


class DataContractError(ValueError):
    """Raised when an uploaded release is not safe to publish."""


def parse_landing_key(key: str) -> tuple[str, str]:
    """Return snapshot month and release ID from the contracted landing key."""

    decoded = unquote_plus(key)
    match = LANDING_KEY_PATTERN.fullmatch(decoded)
    if not match:
        raise DataContractError(
            "landing key must match "
            "landing/dataset=migration/snapshot_month=YYYY-MM/"
            "release_id=<safe-id>/source.csv"
        )
    return match.group("snapshot_month"), match.group("release_id")


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _json_record_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()


def _validate_source_header(source_path: Path) -> None:
    with source_path.open(newline="", encoding="utf-8-sig") as handle:
        header = next(csv.reader(handle), None)
    if tuple(header or ()) != SOURCE_COLUMNS:
        raise DataContractError(
            "source columns do not match the contracted names and order"
        )


def _list_keys(s3, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys.extend(item["Key"] for item in page.get("Contents", []))
    return keys


def _delete_prefix(s3, bucket: str, prefix: str) -> None:
    keys = _list_keys(s3, bucket, prefix)
    for start in range(0, len(keys), 1000):
        batch = keys[start : start + 1000]
        s3.delete_objects(
            Bucket=bucket,
            Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
        )


def _copy_parquet_prefix(
    s3, bucket: str, source_prefix: str, destination_prefix: str
) -> int:
    copied = 0
    for key in _list_keys(s3, bucket, source_prefix):
        if not key.endswith(".parquet"):
            continue
        relative = key.removeprefix(source_prefix).lstrip("/")
        s3.copy_object(
            Bucket=bucket,
            Key=f"{destination_prefix.rstrip('/')}/{relative}",
            CopySource={"Bucket": bucket, "Key": key},
            MetadataDirective="COPY",
        )
        copied += 1
    if copied == 0:
        raise DataContractError(f"no Parquet output found below {source_prefix}")
    return copied


def _read_source_object(
    s3, *, bucket: str, key: str, version_id: str, destination: Path
) -> tuple[str, int]:
    request = {"Bucket": bucket, "Key": key}
    if version_id:
        request["VersionId"] = version_id
    response = s3.get_object(**request)
    content_length = int(response.get("ContentLength", 0))
    if content_length <= 0 or content_length > MAX_SOURCE_BYTES:
        raise DataContractError(
            f"source size must be between 1 and {MAX_SOURCE_BYTES} bytes"
        )

    digest = hashlib.sha256()
    written = 0
    with destination.open("wb") as handle:
        while chunk := response["Body"].read(1024 * 1024):
            written += len(chunk)
            if written > MAX_SOURCE_BYTES:
                raise DataContractError("source exceeded the maximum size while reading")
            digest.update(chunk)
            handle.write(chunk)
    return digest.hexdigest(), written


def _preserve_raw(
    s3,
    *,
    bucket: str,
    local_source: Path,
    release_id: str,
    snapshot_month: str,
    source_sha256: str,
    byte_size: int,
    ingested_at: str,
    landing_key: str,
    landing_version_id: str,
) -> str:
    raw_prefix = f"raw/release_id={release_id}"
    raw_key = f"{raw_prefix}/source.csv"
    manifest_key = f"{raw_prefix}/manifest.json"
    try:
        existing = s3.head_object(Bucket=bucket, Key=raw_key)
    except Exception as error:
        error_code = getattr(error, "response", {}).get("Error", {}).get("Code")
        if error_code not in {"404", "NoSuchKey", "NotFound"}:
            raise
    else:
        existing_digest = existing.get("Metadata", {}).get("source-sha256")
        if existing_digest != source_sha256:
            raise DataContractError(
                f"release {release_id!r} already exists with different content"
            )
        return raw_key

    s3.upload_file(
        str(local_source),
        bucket,
        raw_key,
        ExtraArgs={
            "ContentType": "text/csv",
            "Metadata": {
                "source-sha256": source_sha256,
                "snapshot-month": snapshot_month,
            },
        },
    )
    manifest = {
        "byte_size": byte_size,
        "ingested_at": ingested_at,
        "landing_key": landing_key,
        "landing_version_id": landing_version_id,
        "release_id": release_id,
        "snapshot_month": snapshot_month,
        "source_sha256": source_sha256,
    }
    s3.put_object(
        Bucket=bucket,
        Key=manifest_key,
        Body=_json_bytes(manifest),
        ContentType="application/json",
    )
    return raw_key


def _previous_snapshot(s3, bucket: str, current: str) -> str | None:
    months: set[str] = set()
    prefix = "metadata/commits/snapshot_month="
    for key in _list_keys(s3, bucket, prefix):
        match = re.match(
            r"metadata/commits/snapshot_month=(\d{4}-\d{2})/success\.json$", key
        )
        if match and match.group(1) < current:
            months.add(match.group(1))
    return max(months, default=None)


def _single_value_count(frame, column: str, expected: str) -> None:
    invalid = frame.filter(frame[column] != expected).limit(1).count()
    if invalid:
        raise DataContractError(f"{column} must contain only {expected!r}")


def _transform(
    spark,
    raw_uri: str,
    *,
    snapshot_month: str,
    release_id: str,
    source_sha256: str,
    ingested_at: str,
):
    from pyspark.sql import functions as F
    from pyspark.sql.types import StringType, StructField, StructType

    schema = StructType([StructField(name, StringType(), True) for name in SOURCE_COLUMNS])
    source = (
        spark.read.option("header", True)
        .option("mode", "FAILFAST")
        .schema(schema)
        .csv(raw_uri)
    )
    if tuple(source.columns) != SOURCE_COLUMNS:
        raise DataContractError("source columns do not match the contracted order")
    if source.limit(1).count() == 0:
        raise DataContractError("source contains no data rows")

    empty = F.lit(False)
    for column in SOURCE_COLUMNS:
        empty = empty | F.col(column).isNull() | (F.trim(F.col(column)) == "")
    if source.filter(empty).limit(1).count():
        raise DataContractError("source contains null or empty values")

    month_pattern = r"^\d{4}-(0[1-9]|1[0-2])$"
    invalid_month = (
        ~F.col("year_month").rlike(month_pattern)
        | ~F.col("month_of_release").rlike(month_pattern)
        | (F.col("year_month") > F.lit(snapshot_month))
        | (F.col("month_of_release") > F.lit(snapshot_month))
    )
    if source.filter(invalid_month).limit(1).count():
        raise DataContractError("source contains invalid or future month values")
    _single_value_count(source, "passenger_type", "Long-term migrant")
    _single_value_count(source, "direction", "Arrivals")
    if source.filter(~F.col("status").isin("Final", "Provisional")).limit(1).count():
        raise DataContractError("source contains an unsupported status")

    estimate = F.col("estimate").cast("long")
    standard_error = F.col("standard_error").cast("double")
    invalid_numeric = (
        ~F.col("estimate").rlike(r"^[0-9]+$")
        | estimate.isNull()
        | (estimate < 0)
        | standard_error.isNull()
        | F.isnan(standard_error)
        | (F.abs(standard_error) == F.lit(float("inf")))
        | (standard_error < 0)
    )
    if source.filter(invalid_numeric).limit(1).count():
        raise DataContractError("source contains invalid numeric values")

    c_active = F.col("citizenship") != "TOTAL"
    v_active = F.col("visa") != "TOTAL"
    r_active = F.col("country_of_residence") != "TOTAL"
    metric_slice = (
        F.when(~c_active & ~v_active & ~r_active, "total")
        .when(c_active & ~v_active & ~r_active, "citizenship")
        .when(~c_active & v_active & ~r_active, "visa")
        .when(~c_active & ~v_active & r_active, "country_of_residence")
        .when(c_active & v_active & ~r_active, "citizenship_visa")
        .when(c_active & ~v_active & r_active, "citizenship_country_of_residence")
        .when(~c_active & v_active & r_active, "visa_country_of_residence")
        .otherwise("citizenship_visa_country_of_residence")
    )

    canonical = (
        source.withColumnRenamed("month_of_release", "source_release_month")
        .withColumn("release_id", F.lit(release_id))
        .withColumn("snapshot_month", F.lit(snapshot_month))
        .withColumn("metric_slice", metric_slice)
        .withColumn("estimate", estimate)
        .withColumn("standard_error", standard_error)
        .withColumn("source_sha256", F.lit(source_sha256))
        .withColumn("ingested_at", F.lit(ingested_at))
        .withColumn("schema_version", F.lit(SCHEMA_VERSION))
    )
    duplicate = canonical.groupBy(*BUSINESS_KEY).count().filter("count > 1").limit(1)
    if duplicate.count():
        raise DataContractError("source contains duplicate canonical business keys")
    total_months = canonical.filter(F.col("metric_slice") == "total").select(
        "year_month"
    )
    if total_months.count() != canonical.select("year_month").distinct().count():
        raise DataContractError("headline total slice is not unique for every month")
    return canonical


def _revision_frame(spark, previous_uri: str, current):
    from pyspark.sql import functions as F

    previous = spark.read.parquet(previous_uri)
    left = previous.select(
        *REVISION_KEY,
        *[F.col(column).alias(f"previous_{column}") for column in COMPARE_COLUMNS],
    )
    right = current.select(
        *REVISION_KEY,
        *[F.col(column).alias(f"current_{column}") for column in COMPARE_COLUMNS],
    )
    joined = left.join(right, list(REVISION_KEY), "full_outer")
    changed = F.lit(False)
    for column in COMPARE_COLUMNS:
        changed = changed | ~F.col(f"previous_{column}").eqNullSafe(
            F.col(f"current_{column}")
        )
    return (
        joined.withColumn(
            "estimate_delta", F.col("current_estimate") - F.col("previous_estimate")
        )
        .withColumn(
            "standard_error_delta",
            F.col("current_standard_error") - F.col("previous_standard_error"),
        )
        .withColumn(
            "change_type",
            F.when(F.col("previous_estimate").isNull(), "added")
            .when(F.col("current_estimate").isNull(), "removed")
            .when(changed, "revised")
            .otherwise("unchanged"),
        )
    )


def main() -> None:
    import boto3
    from awsglue.context import GlueContext
    from awsglue.dynamicframe import DynamicFrame
    from awsglue.job import Job
    from awsglue.utils import getResolvedOptions
    from awsgluedq.transforms import EvaluateDataQuality
    from pyspark.context import SparkContext
    from pyspark.sql import functions as F

    required = [
        "JOB_NAME",
        "SOURCE_BUCKET",
        "SOURCE_KEY",
        "SOURCE_VERSION_ID",
        "RUN_ID",
        "DATA_BUCKET",
        "DQ_RULESET_S3_URI",
    ]
    args = getResolvedOptions(sys.argv, required)
    snapshot_month, release_id = parse_landing_key(args["SOURCE_KEY"])
    ingested_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    s3 = boto3.client("s3")

    context = GlueContext(SparkContext.getOrCreate())
    spark = context.spark_session
    job = Job(context)
    job.init(args["JOB_NAME"], args)

    local_source = Path("/tmp/source.csv")
    source_sha256, byte_size = _read_source_object(
        s3,
        bucket=args["SOURCE_BUCKET"],
        key=args["SOURCE_KEY"],
        version_id=args["SOURCE_VERSION_ID"],
        destination=local_source,
    )
    _validate_source_header(local_source)
    raw_key = _preserve_raw(
        s3,
        bucket=args["DATA_BUCKET"],
        local_source=local_source,
        release_id=release_id,
        snapshot_month=snapshot_month,
        source_sha256=source_sha256,
        byte_size=byte_size,
        ingested_at=ingested_at,
        landing_key=args["SOURCE_KEY"],
        landing_version_id=args["SOURCE_VERSION_ID"],
    )
    raw_uri = f"s3://{args['DATA_BUCKET']}/{raw_key}"
    canonical = _transform(
        spark,
        raw_uri,
        snapshot_month=snapshot_month,
        release_id=release_id,
        source_sha256=source_sha256,
        ingested_at=ingested_at,
    )

    ruleset_bucket, ruleset_key = args["DQ_RULESET_S3_URI"].removeprefix(
        "s3://"
    ).split("/", 1)
    ruleset = s3.get_object(Bucket=ruleset_bucket, Key=ruleset_key)["Body"].read().decode()
    dq_result = EvaluateDataQuality.apply(
        frame=DynamicFrame.fromDF(canonical, context, "canonical"),
        ruleset=ruleset,
        publishing_options={
            "dataQualityEvaluationContext": "nz_migration_arrivals",
            "enableDataQualityCloudWatchMetrics": True,
            "enableDataQualityResultsPublishing": True,
            "resultsS3Prefix": f"s3://{args['DATA_BUCKET']}/quality/glue-dq/",
        },
        additional_options={"performanceTuning.caching": "CACHE_NOTHING"},
    )
    dq_rows = [row.asDict(recursive=True) for row in dq_result.toDF().collect()]
    if any(str(row.get("Outcome")) != "Passed" for row in dq_rows):
        raise DataContractError("one or more Glue Data Quality rules failed")

    run_prefix = f"staging/run_id={args['RUN_ID']}"
    canonical_stage = f"{run_prefix}/curated"
    canonical.repartition(16, "year_month").write.mode("overwrite").partitionBy(
        "year_month"
    ).option("compression", "zstd").parquet(
        f"s3://{args['DATA_BUCKET']}/{canonical_stage}"
    )

    previous_month = _previous_snapshot(s3, args["DATA_BUCKET"], snapshot_month)
    revision_counts = {name: 0 for name in ("added", "removed", "revised", "unchanged")}
    revision_rows = 0
    if previous_month:
        previous_uri = (
            f"s3://{args['DATA_BUCKET']}/curated/migration_arrivals/"
            f"snapshot_month={previous_month}/"
        )
        revisions = _revision_frame(spark, previous_uri, canonical).cache()
        revision_rows = revisions.count()
        for row in revisions.groupBy("change_type").count().collect():
            revision_counts[row["change_type"]] = int(row["count"])
        revisions.coalesce(4).write.mode("overwrite").option(
            "compression", "zstd"
        ).parquet(f"s3://{args['DATA_BUCKET']}/{run_prefix}/revisions")

    final_prefix = f"curated/migration_arrivals/snapshot_month={snapshot_month}"
    commit_key = f"metadata/commits/snapshot_month={snapshot_month}/success.json"
    try:
        s3.head_object(Bucket=args["DATA_BUCKET"], Key=commit_key)
    except Exception as error:
        error_code = getattr(error, "response", {}).get("Error", {}).get("Code")
        if error_code not in {"404", "NoSuchKey", "NotFound"}:
            raise
    else:
        raise DataContractError(f"snapshot {snapshot_month} is already committed")

    # Curated files are invisible to Gold until the commit marker exists. A retry
    # can therefore replace files left by an interrupted, uncommitted run.
    if _list_keys(s3, args["DATA_BUCKET"], f"{final_prefix}/"):
        _delete_prefix(s3, args["DATA_BUCKET"], f"{final_prefix}/")
    partition_files = _copy_parquet_prefix(
        s3, args["DATA_BUCKET"], canonical_stage, final_prefix
    )
    if previous_month:
        _copy_parquet_prefix(
            s3,
            args["DATA_BUCKET"],
            f"{run_prefix}/revisions",
            f"revisions/current_snapshot={snapshot_month}/previous_snapshot={previous_month}",
        )

    row_count = canonical.count()
    activity = canonical.agg(
        F.min("year_month").alias("min"), F.max("year_month").alias("max")
    ).first()
    slice_counts = {
        row["metric_slice"]: int(row["count"])
        for row in canonical.groupBy("metric_slice").count().collect()
    }
    status_counts = {
        row["status"]: int(row["count"])
        for row in canonical.groupBy("status").count().collect()
    }
    quality = {
        "activity_month_max": activity["max"],
        "activity_month_min": activity["min"],
        "checks": {
            "canonical_key_unique": True,
            "glue_data_quality_rules": "passed",
            "headline_month_unique": True,
            "required_values_complete": True,
        },
        "metric_slice_counts": slice_counts,
        "quality_status": "passed",
        "release_id": release_id,
        "row_count": row_count,
        "schema_version": SCHEMA_VERSION,
        "snapshot_month": snapshot_month,
        "status_counts": status_counts,
    }
    quality_key = f"quality/snapshot_month={snapshot_month}/results.json"
    s3.put_object(
        Bucket=args["DATA_BUCKET"],
        Key=quality_key,
        Body=_json_record_bytes(quality),
        ContentType="application/json",
    )
    manifest = {
        "ingested_at": ingested_at,
        "partition_file_count": partition_files,
        "previous_snapshot_month": previous_month,
        "quality_key": quality_key,
        "release_id": release_id,
        "revision_counts": revision_counts,
        "revision_row_count": revision_rows,
        "row_count": row_count,
        "run_id": args["RUN_ID"],
        "schema_version": SCHEMA_VERSION,
        "snapshot_month": snapshot_month,
        "source_sha256": source_sha256,
        "status": "CANDIDATE",
    }
    s3.put_object(
        Bucket=args["DATA_BUCKET"],
        Key=(
            f"metadata/releases/snapshot_month={snapshot_month}/"
            f"release_id={release_id}/manifest.json"
        ),
        Body=_json_bytes(manifest),
        ContentType="application/json",
    )
    _delete_prefix(s3, args["DATA_BUCKET"], run_prefix)
    job.commit()


if __name__ == "__main__":
    main()

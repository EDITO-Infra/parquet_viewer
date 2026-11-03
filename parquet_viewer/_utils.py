"""Shared utility functions for parquet dataset handling."""

import os
from urllib.parse import urlparse
from urllib.request import url2pathname
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as fs


def _normalize_parquet_source(parquet_source: str | os.PathLike[str]) -> str:
    """Normalize parquet input to a usable path/URL string."""
    normalized_source = os.fspath(parquet_source)
    parsed_url = urlparse(normalized_source)

    if parsed_url.scheme == "file":
        local_path = url2pathname(parsed_url.path)
        if parsed_url.netloc:
            local_path = f"{parsed_url.netloc}{local_path}"
        return local_path

    return normalized_source


def _get_dataset(dataset_url: str | os.PathLike[str]) -> ds.Dataset:
    """
    Build a PyArrow dataset from a direct URL or local path.

    Parameters
    ----------
    dataset_url : str
        A direct parquet URL, a data-explorer wrapper URL, or a local path.

    Returns
    -------
    pyarrow.dataset.Dataset
        The dataset object used for reading.
    """
    normalized_source = _normalize_parquet_source(dataset_url)
    parsed_url = urlparse(normalized_source)

    if parsed_url.scheme in {"http", "https"} and parsed_url.hostname:
        path_parts = parsed_url.path.strip("/").split("/", 1)
        if len(path_parts) != 2:
            raise ValueError(
                "Expected S3 URL with bucket and key, got: "
                f"{normalized_source}"
            )

        bucket_name, key = path_parts
        s3 = fs.S3FileSystem(endpoint_override=parsed_url.hostname, anonymous=True)
        dataset_path = f"{bucket_name}/{key}"
        return ds.dataset(dataset_path, filesystem=s3, format="parquet")

    return ds.dataset(normalized_source, format="parquet")


def _resolve_dataset(dataset_input: ds.Dataset | str | os.PathLike[str]) -> ds.Dataset:
    """Resolve dataset input to a Dataset object."""
    if isinstance(dataset_input, ds.Dataset):
        return dataset_input
    if isinstance(dataset_input, (str, os.PathLike)):
        return _get_dataset(dataset_input)
    raise TypeError(
        "dataset_input must be a pyarrow.dataset.Dataset or a parquet URL/path string"
    )


def _resolve_columns(dataset: ds.Dataset, columns: list[str] | None) -> list[str]:
    """Resolve and validate requested columns."""
    if not columns:
        return [field.name for field in dataset.schema]

    missing_columns = [name for name in columns if name not in dataset.schema.names]
    if missing_columns:
        raise ValueError(f"Unknown columns: {missing_columns}")

    return columns


def _filter_items(filters: Mapping[str, Any] | list[tuple[str, Any]] | None) -> list[tuple[str, Any]]:
    """Convert filter input to list of tuples."""
    if filters is None:
        return []
    if isinstance(filters, Mapping):
        return list(filters.items())
    if isinstance(filters, list):
        return filters
    raise TypeError("filters must be a mapping, a list of (column, value), or None")


def _build_filter_expression(
    dataset: ds.Dataset,
    filters: Mapping[str, Any] | list[tuple[str, Any]] | None,
) -> ds.Expression | None:
    """Build PyArrow filter expression from filter input."""
    expression = None
    for column_name, filter_value in _filter_items(filters):
        if column_name not in dataset.schema.names:
            raise ValueError(f"Unknown filter column: {column_name}")

        field_type = dataset.schema.field(column_name).type
        is_string_type = pa.types.is_string(field_type) or pa.types.is_large_string(field_type)

        if isinstance(filter_value, Mapping) and ("min" in filter_value or "max" in filter_value):
            conditions = []
            minimum = filter_value.get("min")
            maximum = filter_value.get("max")
            if minimum is not None:
                conditions.append(pc.field(column_name) >= minimum)
            if maximum is not None:
                conditions.append(pc.field(column_name) <= maximum)
            if not conditions:
                continue
            condition = conditions[0]
            for bound_condition in conditions[1:]:
                condition = condition & bound_condition
        elif isinstance(filter_value, (list, tuple, set, frozenset)):
            values = list(filter_value)
            if not values:
                raise ValueError(
                    f"Filter column '{column_name}' received an empty value list"
                )
            condition = pc.field(column_name).isin(values)
        elif filter_value is None:
            condition = pc.field(column_name).is_null()
        elif is_string_type and isinstance(filter_value, str) and filter_value.strip():
            condition = pc.match_substring(pc.field(column_name), filter_value)
        else:
            condition = pc.field(column_name) == filter_value

        expression = condition if expression is None else expression & condition

    return expression

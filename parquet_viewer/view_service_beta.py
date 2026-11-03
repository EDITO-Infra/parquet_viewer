"""
DuckDB-based ParquetViewService optimized for efficiency.

Advantages over PyArrow:
- Better native support for complex SQL predicates (faster string filters).
- Built-in query optimization and pushdown.
- Excellent columnar projection efficiency.
- Lower memory footprint for wide schemas.
"""

from __future__ import annotations

import os
from typing import Any, Mapping
import pyarrow as pa

from ._utils import _normalize_parquet_source

try:
    import duckdb
except ImportError:
    raise ImportError("duckdb must be installed to use DuckDBViewService. pip install duckdb")

DatasetInput = str | os.PathLike[str]
FilterInput = Mapping[str, Any] | list[tuple[str, Any]] | None

__all__ = [
    "DatasetInput",
    "FilterInput",
    "DuckDBViewService",
    "get_view",
    "get_schema",
]


def _build_where_clause(filters: FilterInput) -> tuple[str, tuple]:
    """Build WHERE clause from filter dict/list for DuckDB SQL.
    
    Returns
    -------
    tuple[str, tuple]
        (WHERE_SQL_STRING, params_tuple)
    """
    if not filters:
        return "", ()

    conditions = []
    if isinstance(filters, dict):
        filter_items = list(filters.items())
    else:
        filter_items = filters

    for col_name, value in filter_items:
        col_safe = f'"{col_name}"'

        if isinstance(value, Mapping) and ("min" in value or "max" in value):
            predicates = []
            params = []
            for operator, sql_operator in (("min", ">="), ("max", "<=")):
                operand = value.get(operator)
                if operand is not None:
                    predicates.append(f"{col_safe} {sql_operator} ?")
                    params.append(operand)
            if not predicates:
                continue
            conditions.append((" AND ".join(predicates), params))
        elif isinstance(value, (list, tuple, set, frozenset)):
            values = list(value)
            if not values:
                raise ValueError(f"Filter column '{col_name}' received an empty value list")
            placeholders = ", ".join("?" * len(values))
            conditions.append((f"{col_safe} IN ({placeholders})", values))
        elif value is None:
            conditions.append((f"{col_safe} IS NULL", []))
        elif isinstance(value, str):
            conditions.append((f"{col_safe} ILIKE ?", [f"%{value}%"]))
        else:
            conditions.append((f"{col_safe} = ?", [value]))

    where_parts = [cond[0] for cond in conditions]
    all_params = []
    for _, params in conditions:
        all_params.extend(params)

    where_str = " AND ".join(where_parts)
    return where_str, tuple(all_params) if all_params else ()


class DuckDBViewService:
    """
    DuckDB-backed parquet viewer for efficient querying.
    Optimized for wide schemas and complex predicates.
    """

    def __init__(self, parquet: DatasetInput, con: duckdb.DuckDBPyConnection | None = None):
        """
        Initialize service.

        Parameters
        ----------
        parquet : str
            Path or URL to parquet file.
        con : duckdb.DuckDBPyConnection, optional
            Reuse existing DuckDB connection; if None, creates :memory: connection.
        """
        self._parquet_source = _normalize_parquet_source(parquet)
        self._con = con or duckdb.connect(":memory:")
        self._table_alias = "data"
        self._schema_cache: dict[str, str] | None = None

    def _get_columns(self) -> list[str]:
        """Fetch column names from parquet without full load."""
        try:
            query = "SELECT * FROM read_parquet(?) LIMIT 0"
            result = self._con.execute(query, [self._parquet_source]).fetch_arrow_table()
            return result.column_names
        except Exception as e:
            raise RuntimeError(f"Failed to read schema from {self._parquet_source}: {e}")

    def get_schema(self) -> dict[str, str]:
        """
        Get schema as column -> dtype mapping.

        Returns
        -------
        dict[str, str]
            Column names mapped to their DuckDB type strings.
        """
        if self._schema_cache is not None:
            return self._schema_cache

        query = "SELECT * FROM read_parquet(?) LIMIT 0"
        result = self._con.execute(query, [self._parquet_source]).fetch_arrow_table()
        schema = {col: str(result.schema.field(col).type) for col in result.column_names}
        self._schema_cache = schema
        return schema

    def get_view(
        self,
        columns: list[str] | None = None,
        filters: FilterInput = None,
        max_rows: int = 25,
        row_offset: int = 0,
    ) -> pa.Table:
        """
        Read parquet preview with column selection and filters.

        Parameters
        ----------
        columns : list[str], optional
            Columns to select; if None, select all.
        filters : dict | list, optional
            Filter predicates.
        max_rows : int
            Maximum rows to return.
        row_offset : int
            Number of matching rows to skip before returning data.

        Returns
        -------
        pa.Table
            Arrow table with selected rows and columns.
        """
        if max_rows < 0:
            raise ValueError("max_rows must be >= 0")
        if row_offset < 0:
            raise ValueError("row_offset must be >= 0")

        schema = self.get_schema()
        all_cols = list(schema.keys())
        selected_columns = columns if columns else all_cols

        missing = [c for c in selected_columns if c not in all_cols]
        if missing:
            raise ValueError(f"Unknown columns: {missing}")

        col_list = ", ".join(f'"{c}"' for c in selected_columns)

        where_clause, params = _build_where_clause(filters)
        where_sql = f"WHERE {where_clause}" if where_clause else ""

        limit_sql = f"LIMIT {max_rows}" if max_rows > 0 else ""
        offset_sql = f"OFFSET {row_offset}" if row_offset > 0 else ""

        query = f"""
            SELECT {col_list}
            FROM read_parquet(?)
            {where_sql}
            {limit_sql}
            {offset_sql}
        """

        query_params = [self._parquet_source, *params]
        result = self._con.execute(query, query_params).fetch_arrow_table()

        return result


def get_view(
    parquet: DatasetInput,
    columns: list[str] | None = None,
    filters: FilterInput = None,
    max_rows: int = 25,
    row_offset: int = 0,
) -> pa.Table:
    """Convenience entrypoint for DuckDB view service."""
    return DuckDBViewService(parquet).get_view(
        columns=columns,
        filters=filters,
        max_rows=max_rows,
        row_offset=row_offset,
    )


def get_schema(parquet: DatasetInput) -> dict[str, str]:
    """Convenience entrypoint for DuckDB schema retrieval."""
    return DuckDBViewService(parquet).get_schema()




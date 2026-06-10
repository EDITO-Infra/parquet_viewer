from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    # Normal package import when used as a module/package
    from .view_service import ParquetViewService
    from .view_service_beta import DuckDBViewService
except Exception:
    # Allow running the file directly (python api.py) where relative imports
    # would fail; fall back to importing the sibling modules by name.
    from view_service import ParquetViewService
    from view_service_beta import DuckDBViewService


class ViewRequest(BaseModel):
    parquet_url: str = Field(..., min_length=1)
    max_rows: int = Field(default=25, ge=1, le=200)
    row_offset: int = Field(default=0, ge=0)
    columns: list[str] | None = None
    filters: dict[str, str] | None = None


class SchemaRequest(BaseModel):
    parquet_url: str = Field(..., min_length=1)


class SchemaColumn(BaseModel):
    name: str
    dtype: str


class SchemaResponse(BaseModel):
    columns: list[SchemaColumn]


class ViewResponse(BaseModel):
    total_rows: int
    displayed_rows: int
    columns: list[str]
    data: dict[str, list[Any]]
    output_file: str | None = None


app = FastAPI(title="Parquet Viewer API")

FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend_dist"
FRONTEND_INDEX_FILE = FRONTEND_DIST_DIR / "index.html"

# Minimal local dev CORS for the React app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _to_json_safe(value: Any) -> Any:
    """Convert nested values to JSON-safe primitives for API responses."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, Mapping):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_json_safe(item) for item in value]
    return str(value)


def _schema_columns(schema: Any) -> list[dict[str, str]]:
    if isinstance(schema, Mapping):
        return [{"name": str(name), "dtype": str(dtype)} for name, dtype in schema.items()]

    return [{"name": field.name, "dtype": str(field.type)} for field in schema]


def _get_schema_columns(parquet_url: str) -> list[dict[str, str]]:
    try:
        schema = DuckDBViewService(parquet_url).get_schema()
    except Exception:
        schema = ParquetViewService(parquet_url).get_schema()

    return _schema_columns(schema)


def _get_view_table(
    parquet_url: str,
    columns: list[str] | None,
    filters: dict[str, str] | None,
    max_rows: int,
    row_offset: int,
):
    try:
        return DuckDBViewService(parquet_url).get_view(
            columns=columns,
            filters=filters,
            max_rows=max_rows,
            row_offset=row_offset,
        )
    except Exception:
        fallback = ParquetViewService(parquet_url).get_view(
            columns=columns,
            filters=filters,
            max_rows=max_rows + row_offset,
        )
        return fallback.slice(row_offset, max_rows)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/view", response_model=ViewResponse)
def get_view_endpoint(request: ViewRequest) -> dict[str, Any]:
    try:
        table = _get_view_table(
            request.parquet_url,
            request.columns,
            request.filters,
            request.max_rows,
            request.row_offset,
        )
        columnar_data = {
            column_name: table.column(column_name).to_pylist()
            for column_name in table.column_names
        }
        payload = {
            "total_rows": table.num_rows,
            "displayed_rows": table.num_rows,
            "columns": table.column_names,
            "data": columnar_data,
            "output_file": None,
        }
        return _to_json_safe(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/schema", response_model=SchemaResponse)
def get_schema_endpoint(request: SchemaRequest) -> dict[str, list[dict[str, str]]]:
    try:
        return {"columns": _get_schema_columns(request.parquet_url)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _frontend_file_for_path(full_path: str) -> Path | None:
    if not FRONTEND_DIST_DIR.exists():
        return None
    requested = (FRONTEND_DIST_DIR / full_path).resolve()
    # Keep file serving constrained to the built frontend directory.
    if FRONTEND_DIST_DIR.resolve() not in requested.parents and requested != FRONTEND_DIST_DIR.resolve():
        return None
    if requested.is_file():
        return requested
    return None


if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")


@app.get("/", include_in_schema=False)
def serve_frontend_root() -> FileResponse:
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)
    raise HTTPException(status_code=404, detail="Frontend build not found")


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend_files(full_path: str) -> FileResponse:
    file_path = _frontend_file_for_path(full_path)
    if file_path is not None:
        return FileResponse(file_path)
    if FRONTEND_INDEX_FILE.exists():
        return FileResponse(FRONTEND_INDEX_FILE)
    raise HTTPException(status_code=404, detail="Not found")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("parquet_viewer.api:app", host="127.0.0.1", port=8000, reload=True)


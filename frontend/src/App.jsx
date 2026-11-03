import React, { useEffect, useMemo, useRef, useState } from "react";

const API_BASE = "";
const DEFAULT_URL = "https://s3.waw3-1.cloudferro.com/emodnet/emodnet_biology/12639/marine_biodiversity_observations_occurrence_2026-09-30.parquet";
const COLUMN_PAGE_SIZE = 10;
const ROW_PAGE_OPTIONS = [50, 100, 200, 500];

function compareColumnNames(a, b) {
  return a.localeCompare(b, undefined, { sensitivity: "base" });
}

export default function App() {
  const [parquetUrl, setParquetUrl] = useState(DEFAULT_URL);
  const [schemaColumns, setSchemaColumns] = useState([]);
  const [draftSelectedColumns, setDraftSelectedColumns] = useState([]);
  const [draftFilterValues, setDraftFilterValues] = useState({});
  const [appliedFilterValues, setAppliedFilterValues] = useState({});
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [columnSearch, setColumnSearch] = useState("");
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [activeParquetUrl, setActiveParquetUrl] = useState("");
  const [activeColumns, setActiveColumns] = useState([]);
  const [activeFilters, setActiveFilters] = useState({});
  const [columnOffset, setColumnOffset] = useState(0);
  const [rowOffset, setRowOffset] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(50);
  const [columnWidths, setColumnWidths] = useState({});
  const resizeRef = useRef(null);

  const dropdownRef = useRef(null);
  const loadedSchemaUrlRef = useRef("");

  const sortedSchemaColumns = useMemo(
    () => [...schemaColumns].sort((left, right) => compareColumnNames(left.name, right.name)),
    [schemaColumns]
  );
  const filteredSchemaColumns = useMemo(() => {
    const search = columnSearch.trim().toLowerCase();
    if (!search) {
      return sortedSchemaColumns;
    }
    return sortedSchemaColumns.filter((column) => column.name.toLowerCase().includes(search));
  }, [columnSearch, sortedSchemaColumns]);
  const allColumnNames = useMemo(() => sortedSchemaColumns.map((item) => item.name), [sortedSchemaColumns]);
  const schemaByName = useMemo(
    () => Object.fromEntries(schemaColumns.map((item) => [item.name, item])),
    [schemaColumns]
  );
  const selectedColumnsSet = useMemo(() => new Set(draftSelectedColumns), [draftSelectedColumns]);
  const selectedCount = draftSelectedColumns.length;
  const totalCount = allColumnNames.length;
  const canGoPrevious = columnOffset > 0;
  const canGoNext = columnOffset + COLUMN_PAGE_SIZE < activeColumns.length;
  const canGoPreviousRows = rowOffset > 0;
  const canGoNextRows = Boolean(result) && result.rows.length === rowsPerPage;

  useEffect(() => {
    function onClickOutside(event) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setDropdownOpen(false);
      }
    }

    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    function handleMouseMove(event) {
      if (!resizeRef.current) {
        return;
      }

      const { column, startX, startWidth } = resizeRef.current;
      const width = Math.max(100, startWidth + event.clientX - startX);
      setColumnWidths((previous) => ({ ...previous, [column]: width }));
    }

    function handleMouseUp() {
      resizeRef.current = null;
      document.body.classList.remove("is-resizing-column");
    }

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  async function fetchSchema(url) {
    const response = await fetch(`${API_BASE}/schema`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parquet_url: url })
    });

    const body = await response.json();

    if (!response.ok) {
      throw new Error(body.detail || "Failed to load schema");
    }

    const columns = Array.isArray(body.columns) ? body.columns : [];
    const names = columns.map((item) => item.name);

    return { columns, names };
  }

  function isStringDtype(dtype) {
    const normalized = String(dtype || "").toLowerCase();
    return (
      normalized.includes("string") ||
      normalized.includes("utf8") ||
      normalized.includes("varchar") ||
      normalized.includes("text")
    );
  }

  function isNumericDtype(dtype) {
    const normalized = String(dtype || "").toLowerCase();
    return (
      normalized.includes("int") ||
      normalized.includes("float") ||
      normalized.includes("double") ||
      normalized.includes("decimal") ||
      normalized.includes("numeric")
    );
  }

  function buildFiltersForRequest(selectedColumns, filtersByColumn) {
    const selectedSet = new Set(selectedColumns);
    const filters = {};
    Object.keys(filtersByColumn).forEach((columnName) => {
      if (!selectedSet.has(columnName)) {
        return;
      }
      const columnMeta = schemaByName[columnName];
      const rawValue = filtersByColumn[columnName];
      if (columnMeta && isStringDtype(columnMeta.dtype) && typeof rawValue === "string") {
        const trimmed = rawValue.trim();
        if (trimmed) {
          filters[columnName] = trimmed;
        }
      } else if (columnMeta && isNumericDtype(columnMeta.dtype) && rawValue) {
        const numericFilters = {};
        ["min", "max"].forEach((operator) => {
          const value = rawValue[operator]?.trim();
          if (value) {
            const number = Number(value);
            if (Number.isFinite(number)) {
              numericFilters[operator] = number;
            }
          }
        });
        if (Object.keys(numericFilters).length > 0) {
          filters[columnName] = numericFilters;
        }
      }
    });
    return filters;
  }

  async function renderData(url, columnsToRender, filtersToApply, offsetRows) {
    const trimmedUrl = url.trim();
    if (!trimmedUrl || columnsToRender.length === 0) {
      return null;
    }

    const response = await fetch(`${API_BASE}/view`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parquet_url: trimmedUrl,
        max_rows: rowsPerPage,
        row_offset: offsetRows,
        columns: columnsToRender,
        filters: filtersToApply,
        format: "json_columns"
      })
    });

    const body = await response.json();
    if (!response.ok) {
      throw new Error(body.detail || "Failed to load view");
    }

    return body.data || {};
  }

  function getVisibleColumns(columnsToRender, offset) {
    return columnsToRender.slice(offset, offset + COLUMN_PAGE_SIZE);
  }

  async function renderPage(url, columnsToRender, filtersToApply, offsetColumns, offsetRows) {
    const visibleColumns = getVisibleColumns(columnsToRender, offsetColumns);
    const data = await renderData(url, visibleColumns, filtersToApply, offsetRows);
    if (!data) {
      setResult(null);
      return 0;
    }

    const rows = toRows(data, visibleColumns);
    if (rows.length === 0 && offsetRows > 0) {
      return 0;
    }

    setResult({
      columns: visibleColumns,
      rows,
      totalColumns: columnsToRender.length,
      startIndex: offsetColumns,
      endIndex: offsetColumns + visibleColumns.length,
      rowStart: rows.length > 0 ? offsetRows + 1 : 0,
      rowEnd: offsetRows + rows.length,
    });
    return rows.length;
  }

  function toRows(columnarData, columns) {
    const firstColumn = columns[0];
    const rowCount = firstColumn ? (columnarData[firstColumn] || []).length : 0;
    const rows = [];

    for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
      const row = {};
      columns.forEach((column) => {
        const values = columnarData[column] || [];
        row[column] = values[rowIndex];
      });
      rows.push(row);
    }

    return rows;
  }

  function toggleColumn(name) {
    setDraftSelectedColumns((previous) => {
      if (!previous.includes(name)) {
        return [...previous, name];
      }

      setDraftFilterValues((prevFilters) => {
        const next = { ...prevFilters };
        delete next[name];
        return next;
      });
      setAppliedFilterValues((prevFilters) => {
        const next = { ...prevFilters };
        delete next[name];
        return next;
      });
      setActiveFilters((prevFilters) => {
        const next = { ...prevFilters };
        delete next[name];
        return next;
      });

      return previous.filter((item) => item !== name);
    });
  }

  function handleSelectAll() {
    setDraftSelectedColumns(allColumnNames);
  }

  function handleSelectNone() {
    setDraftSelectedColumns([]);
    setDraftFilterValues({});
    setAppliedFilterValues({});
    setActiveFilters({});
  }

  function handleClearAllFilters() {
    setDraftFilterValues({});
  }

  function updateDraftFilter(name, value, operator = null) {
    if (operator === null) {
      setDraftFilterValues((previous) => ({
        ...previous,
        [name]: value,
      }));
      return;
    }

    setDraftFilterValues((previous) => {
      const current = previous[name] || { min: "", max: "" };
      return { ...previous, [name]: { ...current, [operator]: value } };
    });
  }

  function validateNumericFilter(name, operator) {
    setDraftFilterValues((previous) => {
      const current = previous[name];
      if (!current || !current.min.trim() || !current.max.trim()) {
        return previous;
      }

      const minimum = Number(current.min);
      const maximum = Number(current.max);
      if (
        Number.isFinite(minimum) &&
        Number.isFinite(maximum) &&
        minimum > maximum
      ) {
        return {
          ...previous,
          [name]: { ...current, [operator]: "" },
        };
      }

      return previous;
    });
  }

  function startColumnResize(event, column) {
    event.preventDefault();
    resizeRef.current = {
      column,
      startX: event.clientX,
      startWidth: columnWidths[column] || 160,
    };
    document.body.classList.add("is-resizing-column");
  }

  async function handleRenderClick(closeDropdown = true) {
    const trimmedUrl = parquetUrl.trim();
    if (!trimmedUrl) {
      setError("Paste a parquet URL first.");
      return;
    }

    setRendering(true);
    setError("");

    try {
      let columnsToRender = draftSelectedColumns;
      if (loadedSchemaUrlRef.current !== trimmedUrl || schemaColumns.length === 0) {
        const schemaPayload = await fetchSchema(trimmedUrl);
        setSchemaColumns(schemaPayload.columns);
        const sortedNames = [...schemaPayload.names].sort(compareColumnNames);
        setDraftSelectedColumns(sortedNames);
        setDraftFilterValues({});
        setAppliedFilterValues({});
        columnsToRender = sortedNames;
        loadedSchemaUrlRef.current = trimmedUrl;
      }

      columnsToRender = [...columnsToRender].sort(compareColumnNames);

      if (columnsToRender.length === 0) {
        setError("Select at least one column.");
        setResult(null);
        return;
      }

      setActiveParquetUrl(trimmedUrl);
      setActiveColumns(columnsToRender);
      const filtersToApply = buildFiltersForRequest(columnsToRender, draftFilterValues);
      setAppliedFilterValues({ ...draftFilterValues });
      setActiveFilters(filtersToApply);
      setColumnOffset(0);
      setRowOffset(0);
      await renderPage(trimmedUrl, columnsToRender, filtersToApply, 0, 0);
      if (closeDropdown) {
        setDropdownOpen(false);
      }
    } catch (err) {
      setError(err.message || "Failed to render");
    } finally {
      setRendering(false);
    }
  }

  async function handleApplyClick() {
    if (rendering) {
      return;
    }
    await handleRenderClick(false);
  }

  async function handleNextColumns() {
    if (!canGoNext || rendering) {
      return;
    }

    const nextOffset = Math.min(
      columnOffset + COLUMN_PAGE_SIZE,
      Math.max(0, activeColumns.length - COLUMN_PAGE_SIZE)
    );
    setRendering(true);
    setError("");
    try {
      setColumnOffset(nextOffset);
      await renderPage(activeParquetUrl, activeColumns, activeFilters, nextOffset, rowOffset);
    } catch (err) {
      setError(err.message || "Failed to render");
    } finally {
      setRendering(false);
    }
  }

  async function handlePreviousColumns() {
    if (!canGoPrevious || rendering) {
      return;
    }

    const nextOffset = Math.max(0, columnOffset - COLUMN_PAGE_SIZE);
    setRendering(true);
    setError("");
    try {
      setColumnOffset(nextOffset);
      await renderPage(activeParquetUrl, activeColumns, activeFilters, nextOffset, rowOffset);
    } catch (err) {
      setError(err.message || "Failed to render");
    } finally {
      setRendering(false);
    }
  }

  async function handleNextRows() {
    if (!canGoNextRows || rendering) {
      return;
    }

    const nextRowOffset = rowOffset + rowsPerPage;
    setRendering(true);
    setError("");
    try {
      const rowCount = await renderPage(activeParquetUrl, activeColumns, activeFilters, columnOffset, nextRowOffset);
      if (rowCount === 0) {
        setError("No more rows.");
        return;
      }
      setRowOffset(nextRowOffset);
    } catch (err) {
      setError(err.message || "Failed to render");
    } finally {
      setRendering(false);
    }
  }

  async function handlePreviousRows() {
    if (!canGoPreviousRows || rendering) {
      return;
    }

    const nextRowOffset = Math.max(0, rowOffset - ROW_PAGE_SIZE);
    setRendering(true);
    setError("");
    try {
      await renderPage(activeParquetUrl, activeColumns, activeFilters, columnOffset, nextRowOffset);
      setRowOffset(nextRowOffset);
    } catch (err) {
      setError(err.message || "Failed to render");
    } finally {
      setRendering(false);
    }
  }

  const renderDisabled = rendering || !parquetUrl.trim() || (totalCount > 0 && selectedCount === 0);

  return (
    <div className="app-shell">
      <header className="site-header">
        <h1>DTO-Bioflow parquet viewer</h1>
        <a
          href="https://dto-bioflow.eu/"
          target="_blank"
          rel="noreferrer"
          aria-label="Visit DTO-Bioflow"
        >
          <img
            src="https://dto-bioflow-data.lab.dive.edito.eu/Logo_BIO-Flow2023_Final_Negative.png"
            alt="DTO-Bioflow"
          />
        </a>
      </header>
      <header className="top-panel">
        <div className="form-row">
          <input
            type="text"
            placeholder="Paste parquet URL"
            value={parquetUrl}
            onChange={(e) => {
              setParquetUrl(e.target.value);
              setSchemaColumns([]);
              setDraftSelectedColumns([]);
              setDraftFilterValues({});
              setAppliedFilterValues({});
              setResult(null);
              setError("");
              setActiveParquetUrl("");
              setActiveColumns([]);
              setActiveFilters({});
              setColumnOffset(0);
              setRowOffset(0);
              loadedSchemaUrlRef.current = "";
            }}
          />
          <div className="render-actions">
            <button type="button" className="render-button" onClick={handleRenderClick} disabled={renderDisabled}>
              Render
            </button>
            <label className="rows-control">
              <span>Show rows</span>
              <select
                value={rowsPerPage}
                onChange={(event) => {
                  setRowsPerPage(Number(event.target.value));
                  setRowOffset(0);
                }}
                disabled={rendering}
              >
                {ROW_PAGE_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </label>
          </div>
          {rendering && (
            <span className="loading-indicator">Rendering...</span>
          )}
        </div>

        <div className="columns-row" ref={dropdownRef}>
          <button
            type="button"
            className="columns-trigger"
            onClick={() => setDropdownOpen((open) => !open)}
            disabled={totalCount === 0 || rendering}
          >
            Columns ({selectedCount}/{totalCount})
          </button>

          {dropdownOpen && (
            <div className="columns-dropdown">
              <div className="columns-search">
                <input
                  type="search"
                  value={columnSearch}
                  onChange={(event) => setColumnSearch(event.target.value)}
                  placeholder="Search columns"
                  aria-label="Search columns"
                />
              </div>
              <div className="columns-actions">
                <button type="button" onClick={handleSelectAll} disabled={rendering || totalCount === 0}>
                  Select all
                </button>
                <button type="button" onClick={handleSelectNone} disabled={rendering || totalCount === 0}>
                  Select none
                </button>
                <button type="button" onClick={handleClearAllFilters} disabled={rendering || totalCount === 0}>
                  Clear all filters
                </button>
                <button type="button" className="apply-button" onClick={handleApplyClick} disabled={renderDisabled}>
                  Apply
                </button>
              </div>
              <div className="columns-list">
                <div className="columns-table-header">
                  <span>Select</span>
                  <span>Column</span>
                  <span>Filter</span>
                </div>
                {filteredSchemaColumns.map((column) => {
                  const selected = selectedColumnsSet.has(column.name);
                  const stringColumn = isStringDtype(column.dtype);
                  const numericColumn = isNumericDtype(column.dtype);
                  const draftFilter = draftFilterValues[column.name] || (numericColumn ? { min: "", max: "" } : "");
                  const appliedFilter = appliedFilterValues[column.name] || (numericColumn ? { min: "", max: "" } : "");
                  const pendingFilter = JSON.stringify(draftFilter) !== JSON.stringify(appliedFilter);

                  return (
                    <div key={column.name} className={`columns-item${selected ? " is-selected" : ""}`}>
                      <input
                        className="columns-checkbox"
                        type="checkbox"
                        checked={selected}
                        onChange={() => toggleColumn(column.name)}
                        aria-label={`Select column ${column.name}`}
                      />
                      <div className="columns-main">
                        <span className="columns-name">{column.name}</span>
                      </div>
                      {stringColumn ? (
                        <input
                          type="text"
                          className={`column-filter-input${pendingFilter ? " is-pending" : ""}`}
                          value={draftFilter}
                          onChange={(event) => updateDraftFilter(column.name, event.target.value)}
                          placeholder="Contains text"
                          disabled={!selected || rendering}
                        />
                      ) : numericColumn ? (
                        <div className="numeric-filter-inputs">
                          {["min", "max"].map((operator) => (
                            <input
                              key={operator}
                              type="number"
                              className={`column-filter-input${pendingFilter ? " is-pending" : ""}`}
                              value={draftFilter[operator]}
                              onChange={(event) => updateDraftFilter(column.name, event.target.value, operator)}
                              onBlur={() => validateNumericFilter(column.name, operator)}
                              placeholder={operator}
                              aria-label={`${column.name} ${operator}`}
                              disabled={!selected || rendering}
                            />
                          ))}
                        </div>
                      ) : (
                        <span className="filter-not-available">Not available</span>
                      )}
                    </div>
                  );
                })}
                {filteredSchemaColumns.length === 0 && (
                  <div className="columns-no-results">No matching columns.</div>
                )}
              </div>
            </div>
          )}
        </div>

        {error && <div className="error">{error}</div>}
        {result && (
          <div className="meta-row">
            <div className="meta">
              Showing rows {result.rowStart}-{result.rowEnd}, columns {result.startIndex + 1}-{result.endIndex} of {result.totalColumns}
            </div>
            <div className="viewer-pagers">
              <div className="row-pager">
                <button type="button" onClick={handlePreviousRows} disabled={!canGoPreviousRows || rendering}>
                  Up
                </button>
                <button type="button" onClick={handleNextRows} disabled={!canGoNextRows || rendering}>
                  Down
                </button>
              </div>
              <div className="column-pager">
              <button type="button" onClick={handlePreviousColumns} disabled={!canGoPrevious || rendering}>
                &lt; Previous
              </button>
              <button type="button" onClick={handleNextColumns} disabled={!canGoNext || rendering}>
                Next &gt;
              </button>
              </div>
            </div>
          </div>
        )}
      </header>

      <section className="table-panel">
        {result ? (
          <div className="table-wrap">
            <table>
              <colgroup>
                {result.columns.map((col) => (
                  <col key={col} style={{ width: `${columnWidths[col] || 160}px` }} />
                ))}
              </colgroup>
              <thead>
                <tr>
                  {result.columns.map((col) => (
                    <th key={col} className="column-header-cell">
                      <span className="column-header-label">{col}</span>
                      <span
                        className="column-resize-handle"
                        onMouseDown={(event) => startColumnResize(event, col)}
                        role="separator"
                        aria-label={`Resize ${col} column`}
                      />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, idx) => (
                  <tr key={idx}>
                    {result.columns.map((col) => (
                      <td key={`${idx}-${col}`}>{String(row[col] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-state">
            {parquetUrl.trim()
              ? totalCount > 0
                ? "Choose columns, then click Render."
                : "Click Render to load schema and view data."
              : "Paste a parquet URL to view the data."}
          </div>
        )}
      </section>
      <footer className="site-footer">
        Developed by Willem Boone - VLIZ Flanders Marine Institute 2026.
      </footer>
    </div>
  );
}

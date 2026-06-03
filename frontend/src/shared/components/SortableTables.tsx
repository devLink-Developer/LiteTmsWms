import { useEffect } from "react";

type SortDirection = "asc" | "desc";

const originalRowOrder = new WeakMap<HTMLTableRowElement, number>();
const collator = new Intl.Collator("es", { numeric: true, sensitivity: "base" });

function headerText(header: HTMLTableCellElement) {
  return (header.textContent ?? "").replace(/\s+/g, " ").trim();
}

function isSortableHeader(header: HTMLTableCellElement) {
  if (header.dataset.sortable === "false") return false;
  if (!header.closest("thead")) return false;
  if (!header.closest("table")) return false;
  return headerText(header).length > 0;
}

function decorateSortableHeaders(root: ParentNode = document) {
  root.querySelectorAll<HTMLTableCellElement>("table thead th").forEach((header) => {
    if (!isSortableHeader(header)) return;
    header.dataset.sortableTableHeader = "true";
    header.tabIndex = header.tabIndex >= 0 ? header.tabIndex : 0;
    header.title = header.title || "Ordenar";
  });
}

function controlInsideHeader(target: Element, header: HTMLTableCellElement) {
  const control = target.closest("button, a, input, select, textarea, label");
  return Boolean(control && header.contains(control));
}

function sortableHeaderFromTarget(target: EventTarget | null) {
  if (!(target instanceof Element)) return null;
  const header = target.closest<HTMLTableCellElement>("th");
  if (!header || !isSortableHeader(header)) return null;
  if (controlInsideHeader(target, header)) return null;
  return header;
}

function cellValue(row: HTMLTableRowElement, index: number) {
  const cell = row.cells.item(index);
  if (!cell) return "";
  const controls = Array.from(cell.querySelectorAll<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>("input, select, textarea"));
  if (controls.length) {
    return controls
      .map((control) => {
        if (control instanceof HTMLSelectElement) {
          return control.selectedOptions[0]?.textContent || control.value;
        }
        return control.value;
      })
      .join(" ");
  }
  return (cell.textContent ?? "").replace(/\s+/g, " ").trim();
}

function parsedDate(value: string) {
  const text = value.trim();
  const appDate = /^(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2}))?$/.exec(text);
  if (appDate) {
    return new Date(
      Number(appDate[3]),
      Number(appDate[2]) - 1,
      Number(appDate[1]),
      Number(appDate[4] ?? 0),
      Number(appDate[5] ?? 0),
    ).getTime();
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) {
    const timestamp = Date.parse(text);
    return Number.isNaN(timestamp) ? null : timestamp;
  }
  return null;
}

function parsedNumber(value: string) {
  const text = value.trim();
  const match = /^([+-]?\s*\d+(?:[.,]\d+)*)(?:\s+[\p{L}\d%/²³.]+)?$/u.exec(text);
  if (!match) return null;
  const numberText = match[1].replace(/\s+/g, "");
  const normalized = normalizeNumberText(numberText);
  if (normalized === null) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function thousandsGrouped(value: string, separator: "." | ",") {
  const unsignedValue = value.replace(/^[+-]/, "");
  const groups = unsignedValue.split(separator);
  return groups.length > 1 && groups[0].length >= 1 && groups[0].length <= 3 && groups.slice(1).every((group) => group.length === 3);
}

function normalizeNumberText(value: string) {
  const hasDot = value.includes(".");
  const hasComma = value.includes(",");
  if (hasDot && hasComma) {
    const decimalSeparator = value.lastIndexOf(",") > value.lastIndexOf(".") ? "," : ".";
    return decimalSeparator === "," ? value.replace(/\./g, "").replace(",", ".") : value.replace(/,/g, "");
  }
  if (hasDot) {
    return thousandsGrouped(value, ".") ? value.replace(/\./g, "") : value;
  }
  if (hasComma) {
    return thousandsGrouped(value, ",") ? value.replace(/,/g, "") : value.replace(",", ".");
  }
  return value;
}

function compareCellValues(left: string, right: string) {
  const leftDate = parsedDate(left);
  const rightDate = parsedDate(right);
  if (leftDate !== null && rightDate !== null) return leftDate - rightDate;

  const leftNumber = parsedNumber(left);
  const rightNumber = parsedNumber(right);
  if (leftNumber !== null && rightNumber !== null) return leftNumber - rightNumber;

  return collator.compare(left, right);
}

function headerColumnIndex(header: HTMLTableCellElement) {
  return Array.from(header.parentElement?.children ?? []).indexOf(header);
}

function updateSortState(table: HTMLTableElement, activeHeader: HTMLTableCellElement, direction: SortDirection) {
  table.querySelectorAll<HTMLTableCellElement>("thead th[data-sortable-table-header='true']").forEach((header) => {
    if (header === activeHeader) {
      header.dataset.sortDirection = direction;
      header.setAttribute("aria-sort", direction === "asc" ? "ascending" : "descending");
    } else {
      delete header.dataset.sortDirection;
      header.removeAttribute("aria-sort");
    }
  });
}

function sortTableByHeader(header: HTMLTableCellElement) {
  const table = header.closest("table");
  const tbody = table?.tBodies.item(0);
  const columnIndex = headerColumnIndex(header);
  if (!table || !tbody || columnIndex < 0) return;

  const direction: SortDirection = header.dataset.sortDirection === "asc" ? "desc" : "asc";
  const rows = Array.from(tbody.rows);
  rows.forEach((row, index) => {
    if (!originalRowOrder.has(row)) originalRowOrder.set(row, index);
  });

  rows
    .sort((left, right) => {
      const comparison = compareCellValues(cellValue(left, columnIndex), cellValue(right, columnIndex));
      if (comparison !== 0) return direction === "asc" ? comparison : -comparison;
      return (originalRowOrder.get(left) ?? 0) - (originalRowOrder.get(right) ?? 0);
    })
    .forEach((row) => tbody.appendChild(row));

  updateSortState(table, header, direction);
}

export function useGlobalTableSorting() {
  useEffect(() => {
    decorateSortableHeaders();

    const observer = new MutationObserver(() => decorateSortableHeaders());
    observer.observe(document.body, { childList: true, subtree: true });

    function handleClick(event: MouseEvent) {
      const header = sortableHeaderFromTarget(event.target);
      if (header) sortTableByHeader(header);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Enter" && event.key !== " ") return;
      const header = sortableHeaderFromTarget(event.target);
      if (!header) return;
      event.preventDefault();
      sortTableByHeader(header);
    }

    document.addEventListener("click", handleClick);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      observer.disconnect();
      document.removeEventListener("click", handleClick);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, []);
}

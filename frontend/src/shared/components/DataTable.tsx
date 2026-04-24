import type { OperationRow } from "../../types/operations";
import { StatusBadge } from "./StatusBadge";

type DataTableProps = {
  rows: OperationRow[];
  selectedIds: string[];
  onSelect: (id: string) => void;
  onOpen: (id: string) => void;
  columns: string[];
};

export function DataTable({ rows, selectedIds, onSelect, onOpen, columns }: DataTableProps) {
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-full border-collapse text-left text-[12px]">
        <thead className="sticky top-0 z-10 bg-deep text-white">
          <tr>
            <th className="w-9 px-2 py-2">
              <span className="sr-only">Seleccion</span>
            </th>
            {columns.map((column) => (
              <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold">
                {column}
              </th>
            ))}
            <th className="w-24 px-3 py-2 font-semibold">Acciones</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b border-borderSoft bg-white hover:bg-softStart">
              <td className="px-2 py-2">
                <input
                  aria-label={`Seleccionar ${row.ref}`}
                  type="checkbox"
                  checked={selectedIds.includes(row.id)}
                  onChange={() => onSelect(row.id)}
                  className="h-4 w-4 rounded border-borderSoft text-primary focus:ring-primary"
                />
              </td>
              <td className="whitespace-nowrap px-3 py-2 font-mono font-semibold text-night">{row.ref}</td>
              <td className="px-3 py-2"><StatusBadge label={row.status} tone={row.statusTone} /></td>
              <td className="whitespace-nowrap px-3 py-2 text-night">{row.warehouse}</td>
              <td className="whitespace-nowrap px-3 py-2 text-secondaryText">{row.owner}</td>
              <td className="whitespace-nowrap px-3 py-2 text-night">{row.priority}</td>
              <td className="whitespace-nowrap px-3 py-2 font-mono text-night">{row.quantity}</td>
              <td className="whitespace-nowrap px-3 py-2 font-mono text-primaryHover">{row.sla}</td>
              <td className="px-3 py-2">
                <button
                  type="button"
                  className="h-8 rounded border border-borderSoft px-2 text-[12px] font-semibold text-primaryHover transition hover:border-primary hover:bg-softMid focus:outline-none focus:ring-2 focus:ring-primary/20"
                  onClick={() => onOpen(row.id)}
                >
                  Abrir
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

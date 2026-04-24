type FilterBarProps = {
  filters: Record<string, string>;
  onFilter: (key: string, value: string) => void;
  onReset: () => void;
};

export function FilterBar({ filters, onFilter, onReset }: FilterBarProps) {
  return (
    <section className="flex flex-wrap items-end gap-2 border-y border-borderSoft bg-softMid px-3 py-2" aria-label="Filtros">
      <label className="flex min-w-44 flex-col gap-1 text-[11px] font-semibold text-secondaryText">
        Busqueda
        <input
          className="h-8 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
          value={filters.busqueda}
          onChange={(event) => onFilter("busqueda", event.target.value)}
          placeholder="Pedido, item, cliente"
        />
      </label>
      <label className="flex min-w-36 flex-col gap-1 text-[11px] font-semibold text-secondaryText">
        Estado
        <select
          className="h-8 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
          value={filters.estado}
          onChange={(event) => onFilter("estado", event.target.value)}
        >
          <option value="">Todos</option>
          <option value="en proceso">En proceso</option>
          <option value="parcial">Parcial</option>
          <option value="validado">Validado</option>
        </select>
      </label>
      <label className="flex min-w-36 flex-col gap-1 text-[11px] font-semibold text-secondaryText">
        Warehouse
        <input
          className="h-8 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
          value={filters.warehouse}
          onChange={(event) => onFilter("warehouse", event.target.value)}
          placeholder="Warehouse"
        />
      </label>
      <label className="flex min-w-36 flex-col gap-1 text-[11px] font-semibold text-secondaryText">
        Fecha
        <input
          type="date"
          className="h-8 rounded border border-borderSoft bg-white px-2 text-[12px] text-night outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
          value={filters.fecha}
          onChange={(event) => onFilter("fecha", event.target.value)}
        />
      </label>
      <button
        type="button"
        className="h-8 rounded border border-borderSoft bg-white px-3 text-[12px] font-semibold text-night transition hover:border-primary hover:text-primaryHover focus:outline-none focus:ring-2 focus:ring-primary/20"
        onClick={onReset}
      >
        Limpiar
      </button>
    </section>
  );
}

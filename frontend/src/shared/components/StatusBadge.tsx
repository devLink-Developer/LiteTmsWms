import type { StatusTone } from "../../types/operations";

const toneClasses: Record<StatusTone, string> = {
  neutral: "border-borderSoft bg-surface text-secondaryText",
  info: "border-primary/25 bg-primary/10 text-primaryHover",
  warning: "border-amber-300 bg-amber-50 text-amber-800",
  success: "border-emerald-300 bg-emerald-50 text-emerald-800",
  danger: "border-red-300 bg-red-50 text-red-800",
};

type StatusBadgeProps = {
  label: string;
  tone?: StatusTone;
};

export function StatusBadge({ label, tone = "neutral" }: StatusBadgeProps) {
  return (
    <span className={`inline-flex min-h-6 items-center rounded border px-2 text-[11px] font-semibold uppercase ${toneClasses[tone]}`}>
      {label}
    </span>
  );
}

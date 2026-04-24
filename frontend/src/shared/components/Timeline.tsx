import type { TimelineEvent } from "../../types/operations";

type TimelineProps = {
  events: TimelineEvent[];
};

export function Timeline({ events }: TimelineProps) {
  return (
    <ol className="space-y-3" aria-label="Timeline de estados">
      {events.map((event) => (
        <li key={event.id} className="border-l-2 border-primary/30 pl-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-semibold text-night">{event.label}</span>
            <span className="font-mono text-[11px] text-secondaryText">{event.at}</span>
          </div>
          <div className="text-[11px] text-secondaryText">{event.actor}</div>
          <p className="mt-1 text-[12px] leading-5 text-night">{event.details}</p>
        </li>
      ))}
    </ol>
  );
}

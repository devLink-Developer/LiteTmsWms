const DATE_ONLY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const FULFILLMENT_PREFIX_PATTERN = /^FUL-/i;

function twoDigits(value: number) {
  return String(value).padStart(2, "0");
}

export function formatAppDate(value: string | null | undefined, fallback = "sin fecha") {
  if (!value) {
    return fallback;
  }
  const text = String(value).trim();
  const dateOnly = DATE_ONLY_PATTERN.exec(text);
  if (dateOnly) {
    return `${dateOnly[2]}/${dateOnly[3]}/${dateOnly[1]}`;
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return fallback;
  }
  return `${twoDigits(parsed.getMonth() + 1)}/${twoDigits(parsed.getDate())}/${parsed.getFullYear()}`;
}

export function formatAppDateTime(value: string | null | undefined, fallback = "sin fecha") {
  if (!value) {
    return fallback;
  }
  const text = String(value).trim();
  if (DATE_ONLY_PATTERN.test(text)) {
    return formatAppDate(text, fallback);
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return fallback;
  }
  return `${formatAppDate(text, fallback)} ${twoDigits(parsed.getHours())}:${twoDigits(parsed.getMinutes())}`;
}

export function formatMaybeDateValue(key: string, value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value !== "string") {
    return String(value);
  }
  if (FULFILLMENT_PREFIX_PATTERN.test(value)) {
    return value.replace(FULFILLMENT_PREFIX_PATTERN, "");
  }
  if (/(^|_)(date|at)$/.test(key) || DATE_ONLY_PATTERN.test(value) || /^\d{4}-\d{2}-\d{2}T/.test(value)) {
    return formatAppDateTime(value, value);
  }
  return value;
}

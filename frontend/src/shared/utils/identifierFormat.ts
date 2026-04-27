export function stripFulfillmentPrefix(value: unknown) {
  if (value === null || value === undefined) {
    return value;
  }
  return String(value).replace(/^FUL-/i, "");
}

export function formatIdentifier(value: unknown, fallback = "-") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return stripFulfillmentPrefix(value) || fallback;
}

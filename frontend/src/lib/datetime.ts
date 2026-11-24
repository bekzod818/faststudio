const OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/u;

/**
 * Parse a datetime wire value the way the API contract defines it: values of
 * timezone-aware columns without an offset (SQLite drops it) are UTC; naive
 * columns are wall-clock time and parse as local time.
 */
export function parseWireDateTime(value: string, timezoneAware: boolean): Date {
  return new Date(timezoneAware && !OFFSET.test(value) ? `${value}Z` : value);
}

import type { HeightRead, WeightRead } from "../api/types";

/**
 * For plain YYYY-MM-DD canonical dates (date_of_birth, missing_date) -- deliberately
 * never runs through a timezone conversion. These fields have no time component; naively
 * parsing "2020-01-01" as a UTC-midnight Date and then formatting it in a negative-UTC-
 * offset local timezone would silently display the wrong day (e.g. "Dec 31, 2019").
 * Parsing the Y/M/D directly and formatting with timeZone: "UTC" avoids that entirely.
 */
export function formatDateOnly(value: string | null | undefined): string | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return value;
  const [, year, month, day] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/**
 * For full ISO-8601 timestamps (created_at, updated_at, first_seen_at, last_seen_at,
 * source_modified_at). Correctly converts from UTC to the viewer's local time zone --
 * this is an accurate conversion, not "reinterpreting UTC as local": `Date` parses the
 * "Z" correctly, and `timeZoneName: "short"` labels whichever zone is actually shown so
 * it's never ambiguous.
 */
export function formatDateTime(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

export function formatLocation(...parts: Array<string | null | undefined>): string | null {
  const present = parts.filter((part): part is string => Boolean(part));
  return present.length > 0 ? present.join(", ") : null;
}

export function formatHeight(height: HeightRead): string | null {
  if (height.raw) return height.raw;
  if (height.min_cm == null && height.max_cm == null) return null;
  if (height.min_cm != null && height.max_cm != null && height.min_cm !== height.max_cm) {
    return `${height.min_cm}–${height.max_cm} cm`;
  }
  const value = height.min_cm ?? height.max_cm;
  return value != null ? `${value} cm` : null;
}

export function formatWeight(weight: WeightRead): string | null {
  if (weight.raw) return weight.raw;
  if (weight.min_kg == null && weight.max_kg == null) return null;
  if (weight.min_kg != null && weight.max_kg != null && weight.min_kg !== weight.max_kg) {
    return `${weight.min_kg}–${weight.max_kg} kg`;
  }
  const value = weight.min_kg ?? weight.max_kg;
  return value != null ? `${value} kg` : null;
}

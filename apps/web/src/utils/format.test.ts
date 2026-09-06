import { describe, expect, it } from "vitest";
import { formatDateOnly, formatDateTime, formatHeight, formatLocation, formatWeight } from "./format";

describe("formatDateOnly", () => {
  it("formats a plain date without shifting the day regardless of local time zone", () => {
    // A naive `new Date("2020-01-01")` + local-zone formatting could show "Dec 31, 2019"
    // in a negative-UTC-offset zone. This must never happen for a date-only field.
    expect(formatDateOnly("2020-01-01")).toBe("January 1, 2020");
  });

  it("returns null for a missing value", () => {
    expect(formatDateOnly(null)).toBeNull();
    expect(formatDateOnly(undefined)).toBeNull();
  });
});

describe("formatDateTime", () => {
  it("formats a full timestamp with a labeled time zone", () => {
    const result = formatDateTime("2026-08-25T05:28:54.771787Z");
    expect(result).not.toBeNull();
    // No longer the raw ISO shape (e.g. "2026-08-25T05:28:54.771787Z") -- note "UTC"
    // legitimately contains the letter "T", so this checks the ISO pattern, not "T".
    expect(result).not.toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("returns null for a missing value", () => {
    expect(formatDateTime(null)).toBeNull();
  });
});

describe("formatLocation", () => {
  it("joins only the present parts", () => {
    expect(formatLocation("Sampleton", null, "CO", "United States")).toBe("Sampleton, CO, United States");
  });

  it("returns null when nothing is present", () => {
    expect(formatLocation(null, undefined, null)).toBeNull();
  });
});

describe("formatHeight", () => {
  it("prefers raw text when present", () => {
    expect(formatHeight({ min_cm: 170, max_cm: 170, raw: "5'7\"", temporal_context: null })).toBe("5'7\"");
  });

  it("formats a point value", () => {
    expect(formatHeight({ min_cm: 170, max_cm: 170, raw: null, temporal_context: null })).toBe("170 cm");
  });

  it("formats a range", () => {
    expect(formatHeight({ min_cm: 162.6, max_cm: 165.1, raw: null, temporal_context: null })).toBe("162.6–165.1 cm");
  });

  it("returns null when nothing is known", () => {
    expect(formatHeight({ min_cm: null, max_cm: null, raw: null, temporal_context: null })).toBeNull();
  });
});

describe("formatWeight", () => {
  it("prefers raw text when present", () => {
    expect(formatWeight({ min_kg: 59, max_kg: 63.5, raw: "130 to 140 pounds", temporal_context: null })).toBe(
      "130 to 140 pounds",
    );
  });

  it("returns null when nothing is known", () => {
    expect(formatWeight({ min_kg: null, max_kg: null, raw: null, temporal_context: null })).toBeNull();
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, getCase, searchCases } from "./client";

describe("api client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("builds a query string from provided params and omits empty/undefined ones", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ total: 0, limit: 25, offset: 0, items: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await searchCases({ q: "sample", sex: undefined, limit: 25, offset: 0 });

    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toContain("/cases?");
    expect(calledUrl).toContain("q=sample");
    expect(calledUrl).not.toContain("sex=");
  });

  it("throws a 404 ApiError for a missing case", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }),
    );

    await expect(getCase("missing-id")).rejects.toMatchObject({ status: 404 });
  });

  it("wraps a network failure in an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    await expect(searchCases({})).rejects.toBeInstanceOf(ApiError);
  });
});

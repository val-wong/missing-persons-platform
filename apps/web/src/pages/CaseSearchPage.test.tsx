import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CaseSearchPage } from "./CaseSearchPage";
import * as client from "../api/client";
import type { CaseListResponse } from "../api/types";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, searchCases: vi.fn() };
});

const mockSearchCases = vi.mocked(client.searchCases);

function renderPage(initialEntry = "/") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <CaseSearchPage />
    </MemoryRouter>,
  );
}

const sampleResponse: CaseListResponse = {
  total: 2,
  limit: 25,
  offset: 0,
  items: [
    {
      case_id: "11111111-1111-1111-1111-111111111111",
      person_id: "p1",
      display_name: "ALEX SAMPLE",
      sex: "Female",
      missing_date: "2020-01-01",
      missing_city: "Sampleton",
      missing_state: "CO",
      missing_country: "United States",
      primary_photo_url: "https://example.org/photo.jpg",
      investigating_agency: "Federal Bureau of Investigation",
      source_codes: ["fbi"],
      source_names: ["Federal Bureau of Investigation"],
      updated_at: "2026-01-01T00:00:00Z",
    },
    {
      case_id: "22222222-2222-2222-2222-222222222222",
      person_id: "p2",
      display_name: "JORDAN OTHER",
      sex: null,
      missing_date: null,
      missing_city: null,
      missing_state: null,
      missing_country: null,
      primary_photo_url: null,
      investigating_agency: null,
      source_codes: ["fbi"],
      source_names: ["Federal Bureau of Investigation"],
      updated_at: "2026-01-02T00:00:00Z",
    },
  ],
};

describe("CaseSearchPage", () => {
  beforeEach(() => {
    mockSearchCases.mockReset();
  });

  it("renders returned cases", async () => {
    mockSearchCases.mockResolvedValue(sampleResponse);
    renderPage();

    expect(await screen.findByText("ALEX SAMPLE")).toBeInTheDocument();
    expect(screen.getByText("JORDAN OTHER")).toBeInTheDocument();
  });

  it("handles empty results without crashing", async () => {
    mockSearchCases.mockResolvedValue({ total: 0, limit: 25, offset: 0, items: [] });
    renderPage();

    expect(await screen.findByText(/no cases match/i)).toBeInTheDocument();
  });

  it("does not crash when a result has every optional field null", async () => {
    mockSearchCases.mockResolvedValue(sampleResponse);
    renderPage();

    expect(await screen.findByText("JORDAN OTHER")).toBeInTheDocument();
  });

  it("sends the free-text search parameter", async () => {
    mockSearchCases.mockResolvedValue({ total: 0, limit: 25, offset: 0, items: [] });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(mockSearchCases).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/search by name/i), "sample");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() => {
      const lastCall = mockSearchCases.mock.calls.at(-1)?.[0];
      expect(lastCall).toMatchObject({ q: "sample" });
    });
  });

  it("sends a filter parameter", async () => {
    mockSearchCases.mockResolvedValue({ total: 0, limit: 25, offset: 0, items: [] });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(mockSearchCases).toHaveBeenCalled());

    await user.type(screen.getByLabelText(/missing from state/i), "CO");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() => {
      const lastCall = mockSearchCases.mock.calls.at(-1)?.[0];
      expect(lastCall).toMatchObject({ missing_state: "CO" });
    });
  });

  it("sends sorting parameters", async () => {
    mockSearchCases.mockResolvedValue({ total: 0, limit: 25, offset: 0, items: [] });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => expect(mockSearchCases).toHaveBeenCalled());

    await user.selectOptions(screen.getByLabelText(/sort by/i), "name");
    await user.selectOptions(screen.getByLabelText(/sort direction/i), "asc");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() => {
      const lastCall = mockSearchCases.mock.calls.at(-1)?.[0];
      expect(lastCall).toMatchObject({ sort_by: "name", sort_order: "asc" });
    });
  });

  it("supports next/previous pagination and disables controls at the boundaries", async () => {
    mockSearchCases.mockResolvedValue({ total: 30, limit: 25, offset: 0, items: sampleResponse.items });
    const user = userEvent.setup();
    renderPage();

    const previousButton = await screen.findByRole("button", { name: /previous/i });
    expect(previousButton).toBeDisabled();

    const nextButton = screen.getByRole("button", { name: /^next$/i });
    expect(nextButton).toBeEnabled();

    mockSearchCases.mockResolvedValue({ total: 30, limit: 25, offset: 25, items: [] });
    await user.click(nextButton);

    await waitFor(() => {
      const lastCall = mockSearchCases.mock.calls.at(-1)?.[0];
      expect(lastCall).toMatchObject({ offset: 25 });
    });
  });

  it("restores search/filter state from the URL", async () => {
    mockSearchCases.mockResolvedValue({ total: 0, limit: 25, offset: 0, items: [] });
    renderPage("/?missing_state=CO&sort_by=name&sort_order=asc");

    await waitFor(() => expect(mockSearchCases).toHaveBeenCalled());
    expect(screen.getByLabelText(/missing from state/i)).toHaveValue("CO");
    expect(screen.getByLabelText(/sort by/i)).toHaveValue("name");
    expect(screen.getByLabelText(/sort direction/i)).toHaveValue("asc");

    const firstCall = mockSearchCases.mock.calls[0]?.[0];
    expect(firstCall).toMatchObject({ missing_state: "CO", sort_by: "name", sort_order: "asc" });
  });

  it("shows an error message when the API call fails", async () => {
    mockSearchCases.mockRejectedValue(new client.ApiError(500, "The API returned an unexpected error (500)."));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(/unexpected error/i);
  });
});

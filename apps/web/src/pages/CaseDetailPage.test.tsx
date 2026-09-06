import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CaseDetailPage } from "./CaseDetailPage";
import * as client from "../api/client";
import { ApiError } from "../api/client";
import type { CaseDetailRead } from "../api/types";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, getCase: vi.fn() };
});

const mockGetCase = vi.mocked(client.getCase);

function renderDetail(caseId: string) {
  return render(
    <MemoryRouter initialEntries={[`/cases/${caseId}`]}>
      <Routes>
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const sampleCase: CaseDetailRead = {
  id: "case-1",
  person_id: "person-1",
  case_status: null,
  missing_date: "2020-01-01",
  missing_city: "Sampleton",
  missing_county: null,
  missing_state: "CO",
  missing_country: "United States",
  age_at_missing: null,
  circumstances: "Sample circumstances narrative.",
  investigating_agency: "Federal Bureau of Investigation",
  agency_case_number: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  person: {
    id: "person-1",
    given_name: null,
    middle_name: null,
    family_name: null,
    suffix: null,
    display_name: "SAMPLE PERSON",
    aliases: null,
    date_of_birth: null,
    age: null,
    sex: "Female",
    height: { min_cm: null, max_cm: null, raw: null, temporal_context: null },
    weight: { min_kg: 59, max_kg: 63.5, raw: "130 to 140 pounds", temporal_context: null },
    hair_color: "Brown",
    eye_color: "Blue",
    distinguishing_characteristics: null,
    photos: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  sources: [
    {
      code: "fbi",
      name: "Federal Bureau of Investigation",
      external_id: "example-external-id",
      source_url: "https://www.fbi.gov/wanted/kidnap/sample-person",
      link_method: "fbi_deterministic_normalization_v1",
      first_seen_at: "2026-01-01T00:00:00Z",
      last_seen_at: "2026-01-02T00:00:00Z",
      source_modified_at: null,
      contributed_fields: { display_name: "SAMPLE PERSON" },
    },
  ],
};

describe("CaseDetailPage", () => {
  beforeEach(() => {
    mockGetCase.mockReset();
  });

  it("renders person and case fields", async () => {
    mockGetCase.mockResolvedValue(sampleCase);
    renderDetail("case-1");

    expect(await screen.findByRole("heading", { name: "SAMPLE PERSON" })).toBeInTheDocument();
    expect(screen.getByText("Sample circumstances narrative.")).toBeInTheDocument();
    // Appears twice: as the investigating agency fact and as the source card's name.
    expect(screen.getAllByText("Federal Bureau of Investigation").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("130 to 140 pounds")).toBeInTheDocument();
  });

  it("renders key person/case facts in the hero", async () => {
    mockGetCase.mockResolvedValue(sampleCase);
    renderDetail("case-1");

    await screen.findByRole("heading", { name: "SAMPLE PERSON" });
    expect(screen.getByText("Sex")).toBeInTheDocument();
    expect(screen.getByText("Female")).toBeInTheDocument();
    expect(screen.getByText("Weight")).toBeInTheDocument();
    expect(screen.getByText("Missing location")).toBeInTheDocument();
    expect(screen.getByText("Sampleton, CO, United States")).toBeInTheDocument();
  });

  it("shows the source name/badge, with technical details behind a labeled disclosure", async () => {
    mockGetCase.mockResolvedValue(sampleCase);
    renderDetail("case-1");

    await screen.findByRole("heading", { name: "SAMPLE PERSON" });
    // Renders twice: the hero badge and the source card's own badge.
    expect(screen.getAllByText("FBI").length).toBeGreaterThanOrEqual(1);
    // jsdom doesn't apply the native collapsed-<details> hiding a real browser does
    // (that's a jsdom fidelity limit, not testable here), so this checks the disclosure
    // exists and starts closed, rather than asserting the content is absent from the DOM.
    const details = screen.getByText(/technical provenance details/i).closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
  });

  it("reveals technical provenance details when expanded", async () => {
    mockGetCase.mockResolvedValue(sampleCase);
    const user = userEvent.setup();
    renderDetail("case-1");

    await screen.findByRole("heading", { name: "SAMPLE PERSON" });
    await user.click(screen.getByText(/technical provenance details/i));

    expect(await screen.findByText("example-external-id")).toBeInTheDocument();
  });

  it("shows the source link only when source_url is present", async () => {
    mockGetCase.mockResolvedValue(sampleCase);
    renderDetail("case-1");

    const link = await screen.findByRole("link", { name: /original source/i });
    expect(link).toHaveAttribute("href", sampleCase.sources[0].source_url);
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("does not render a source link when source_url is absent", async () => {
    mockGetCase.mockResolvedValue({
      ...sampleCase,
      sources: [{ ...sampleCase.sources[0], source_url: "" }],
    });
    renderDetail("case-1");

    await screen.findByRole("heading", { name: "SAMPLE PERSON" });
    expect(screen.queryByRole("link", { name: /original source/i })).not.toBeInTheDocument();
  });

  it("handles a case with no photos", async () => {
    mockGetCase.mockResolvedValue(sampleCase);
    renderDetail("case-1");

    expect(await screen.findByLabelText(/photo not available/i)).toBeInTheDocument();
  });

  it("renders without crashing when nearly every optional field is null", async () => {
    mockGetCase.mockResolvedValue({
      ...sampleCase,
      case_status: null,
      missing_date: null,
      missing_city: null,
      missing_county: null,
      missing_state: null,
      missing_country: null,
      age_at_missing: null,
      circumstances: null,
      investigating_agency: null,
      agency_case_number: null,
      person: {
        ...sampleCase.person,
        sex: null,
        hair_color: null,
        eye_color: null,
        aliases: null,
        distinguishing_characteristics: null,
        height: { min_cm: null, max_cm: null, raw: null, temporal_context: null },
        weight: { min_kg: null, max_kg: null, raw: null, temporal_context: null },
      },
    });
    renderDetail("case-1");

    expect(await screen.findByRole("heading", { name: "SAMPLE PERSON" })).toBeInTheDocument();
    expect(screen.queryByText("Circumstances")).not.toBeInTheDocument();
  });

  it("shows a not-found message for a 404", async () => {
    mockGetCase.mockRejectedValue(new ApiError(404, "Not found."));
    renderDetail("does-not-exist");

    expect(await screen.findByText(/case not found/i)).toBeInTheDocument();
  });

  it("shows a generic error message for a non-404 failure", async () => {
    mockGetCase.mockRejectedValue(new ApiError(500, "The API returned an unexpected error (500)."));
    renderDetail("case-1");

    expect(await screen.findByRole("alert")).toHaveTextContent(/unexpected error/i);
  });
});

/**
 * Types mirror the backend's Pydantic response models exactly (see
 * apps/api/app/schemas/case.py and apps/api/app/schemas/person.py). Keep them in sync
 * by hand -- there is no shared schema generation between the two apps yet.
 */

export interface HeightRead {
  min_cm: number | null;
  max_cm: number | null;
  raw: string | null;
  temporal_context: string | null;
}

export interface WeightRead {
  min_kg: number | null;
  max_kg: number | null;
  raw: string | null;
  temporal_context: string | null;
}

export interface PhotoRead {
  url: string | null;
  full_url: string | null;
  thumbnail_url: string | null;
  caption: string | null;
}

export interface PersonRead {
  id: string;
  given_name: string | null;
  middle_name: string | null;
  family_name: string | null;
  suffix: string | null;
  display_name: string;
  aliases: string[] | null;
  date_of_birth: string | null;
  age: number | null;
  sex: string | null;
  height: HeightRead;
  weight: WeightRead;
  hair_color: string | null;
  eye_color: string | null;
  distinguishing_characteristics: string | null;
  photos: PhotoRead[];
  created_at: string;
  updated_at: string;
}

export interface CaseSourceRead {
  code: string;
  name: string;
  external_id: string;
  source_url: string;
  link_method: string;
  first_seen_at: string;
  last_seen_at: string;
  source_modified_at: string | null;
  contributed_fields: Record<string, unknown> | null;
}

export interface CaseSummaryRead {
  case_id: string;
  person_id: string;
  display_name: string;
  sex: string | null;
  missing_date: string | null;
  missing_city: string | null;
  missing_state: string | null;
  missing_country: string | null;
  primary_photo_url: string | null;
  investigating_agency: string | null;
  source_codes: string[];
  source_names: string[];
  updated_at: string;
}

export interface CaseListResponse {
  total: number;
  limit: number;
  offset: number;
  items: CaseSummaryRead[];
}

export interface CaseDetailRead {
  id: string;
  person_id: string;
  case_status: string | null;
  missing_date: string | null;
  missing_city: string | null;
  missing_county: string | null;
  missing_state: string | null;
  missing_country: string | null;
  age_at_missing: number | null;
  circumstances: string | null;
  investigating_agency: string | null;
  agency_case_number: string | null;
  created_at: string;
  updated_at: string;
  person: PersonRead;
  sources: CaseSourceRead[];
}

export type SortField = "name" | "missing_date" | "created_at" | "updated_at";
export type SortOrder = "asc" | "desc";

export interface CaseSearchParams {
  q?: string;
  sex?: string;
  missing_state?: string;
  missing_city?: string;
  missing_country?: string;
  missing_date_from?: string;
  missing_date_to?: string;
  hair_color?: string;
  eye_color?: string;
  source?: string;
  sort_by?: SortField;
  sort_order?: SortOrder;
  limit?: number;
  offset?: number;
}

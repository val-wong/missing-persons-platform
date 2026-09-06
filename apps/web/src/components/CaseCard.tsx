import { Link } from "react-router-dom";
import type { CaseSummaryRead } from "../api/types";
import { PhotoThumbnail } from "./PhotoThumbnail";

function formatLocation(city: string | null, state: string | null, country: string | null): string | null {
  const parts = [city, state, country].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(", ") : null;
}

export function CaseCard({ item }: { item: CaseSummaryRead }) {
  const location = formatLocation(item.missing_city, item.missing_state, item.missing_country);

  return (
    <li className="case-card">
      <PhotoThumbnail src={item.primary_photo_url} alt={`Photo of ${item.display_name}`} className="case-card-photo" />
      <div className="case-card-body">
        <h3 className="case-card-name">
          <Link to={`/cases/${item.case_id}`}>{item.display_name}</Link>
        </h3>
        <dl className="case-card-facts">
          {item.sex && (
            <div>
              <dt>Sex</dt>
              <dd>{item.sex}</dd>
            </div>
          )}
          {item.missing_date && (
            <div>
              <dt>Missing since</dt>
              <dd>{item.missing_date}</dd>
            </div>
          )}
          {location && (
            <div>
              <dt>Last known location</dt>
              <dd>{location}</dd>
            </div>
          )}
          {item.investigating_agency && (
            <div>
              <dt>Investigating agency</dt>
              <dd>{item.investigating_agency}</dd>
            </div>
          )}
          {item.source_names.length > 0 && (
            <div>
              <dt>Source</dt>
              <dd>{item.source_names.join(", ")}</dd>
            </div>
          )}
        </dl>
        <p className="case-card-updated">Last updated {item.updated_at.slice(0, 10)}</p>
        <Link to={`/cases/${item.case_id}`} className="case-card-link">
          View case details
        </Link>
      </div>
    </li>
  );
}

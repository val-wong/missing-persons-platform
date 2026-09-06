import { Link } from "react-router-dom";
import type { CaseSummaryRead } from "../api/types";
import { PhotoThumbnail } from "./PhotoThumbnail";
import { SourceBadge } from "./SourceBadge";
import { formatDateOnly, formatLocation } from "../utils/format";

export function CaseCard({ item }: { item: CaseSummaryRead }) {
  const location = formatLocation(item.missing_city, item.missing_state, item.missing_country);
  const metaParts = [
    item.sex,
    item.missing_date ? `Missing since ${formatDateOnly(item.missing_date)}` : null,
    location,
  ].filter((part): part is string => Boolean(part));

  return (
    // The card's only link (the name) is CSS-"stretched" to cover the whole card via
    // .case-card-name a::after, so the entire card is clickable without a div standing
    // in for a real link -- there is exactly one real <a>, with its own accessible name.
    <li className="case-card">
      <PhotoThumbnail src={item.primary_photo_url} alt={`Photo of ${item.display_name}`} className="case-card-photo" />
      <div className="case-card-body">
        <div className="case-card-heading">
          <h3 className="case-card-name">
            <Link to={`/cases/${item.case_id}`}>{item.display_name}</Link>
          </h3>
          {item.source_codes.length > 0 && (
            <div className="source-badges">
              {item.source_codes.map((code) => (
                <SourceBadge key={code} code={code} />
              ))}
            </div>
          )}
        </div>

        {metaParts.length > 0 && <p className="case-card-meta">{metaParts.join(" · ")}</p>}
        {item.investigating_agency && <p className="case-card-agency">{item.investigating_agency}</p>}
      </div>
    </li>
  );
}

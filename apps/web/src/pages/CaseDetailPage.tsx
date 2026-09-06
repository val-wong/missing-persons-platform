import { Link, useParams } from "react-router-dom";
import { useCaseDetail } from "../hooks/useCaseDetail";
import { PhotoThumbnail } from "../components/PhotoThumbnail";
import type { CaseSourceRead, HeightRead, WeightRead } from "../api/types";

function formatHeight(height: HeightRead): string | null {
  if (height.raw) return height.raw;
  if (height.min_cm == null && height.max_cm == null) return null;
  if (height.min_cm != null && height.max_cm != null && height.min_cm !== height.max_cm) {
    return `${height.min_cm}–${height.max_cm} cm`;
  }
  const value = height.min_cm ?? height.max_cm;
  return value != null ? `${value} cm` : null;
}

function formatWeight(weight: WeightRead): string | null {
  if (weight.raw) return weight.raw;
  if (weight.min_kg == null && weight.max_kg == null) return null;
  if (weight.min_kg != null && weight.max_kg != null && weight.min_kg !== weight.max_kg) {
    return `${weight.min_kg}–${weight.max_kg} kg`;
  }
  const value = weight.min_kg ?? weight.max_kg;
  return value != null ? `${value} kg` : null;
}

/** Renders one labeled fact row, or nothing at all when the value is unknown -- this
 * platform distinguishes "unknown" from a fabricated placeholder, so a missing value is
 * simply omitted rather than shown as "N/A" everywhere. */
function Fact({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function SourceCard({ source }: { source: CaseSourceRead }) {
  const contributedEntries = source.contributed_fields ? Object.entries(source.contributed_fields) : [];

  return (
    <li className="source-card">
      <h4>{source.name}</h4>
      <dl>
        <Fact label="Source code" value={source.code} />
        <Fact label="Source record ID" value={source.external_id} />
        <Fact label="First seen" value={source.first_seen_at} />
        <Fact label="Last seen" value={source.last_seen_at} />
        <Fact label="Source last modified" value={source.source_modified_at} />
      </dl>
      {source.source_url && (
        <p>
          <a href={source.source_url} target="_blank" rel="noopener noreferrer">
            View original source listing
          </a>
        </p>
      )}
      {contributedEntries.length > 0 && (
        <details>
          <summary>Contributed fields</summary>
          <dl>
            {contributedEntries.map(([key, value]) => (
              <div className="fact" key={key}>
                <dt>{key}</dt>
                <dd>{value === null ? "Not available" : String(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
    </li>
  );
}

export function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>();
  const { data, loading, error, notFound } = useCaseDetail(caseId);

  if (loading) return <p role="status">Loading case…</p>;

  if (notFound) {
    return (
      <div>
        <h2>Case not found</h2>
        <p role="alert">This case may have been removed, or the link may be incorrect.</p>
        <Link to="/">Back to search</Link>
      </div>
    );
  }

  if (error) {
    return (
      <p role="alert" className="error-message">
        {error}
      </p>
    );
  }

  if (!data) return null;

  const { person } = data;
  const height = formatHeight(person.height);
  const weight = formatWeight(person.weight);
  const location = [data.missing_city, data.missing_county, data.missing_state, data.missing_country]
    .filter(Boolean)
    .join(", ");

  return (
    <article>
      <p>
        <Link to="/">&larr; Back to search</Link>
      </p>
      <h2>{person.display_name}</h2>

      <section aria-labelledby="photos-heading">
        <h3 id="photos-heading">Photos</h3>
        {person.photos.length === 0 ? (
          <p>No photos available.</p>
        ) : (
          <ul className="photo-gallery">
            {person.photos.map((photo, index) => (
              <li key={photo.url ?? index}>
                <PhotoThumbnail
                  src={photo.url}
                  alt={photo.caption ?? `Photo of ${person.display_name}`}
                  className="detail-photo"
                />
                {photo.caption && <p className="photo-caption">{photo.caption}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="person-heading">
        <h3 id="person-heading">Person</h3>
        <dl>
          <Fact label="Display name" value={person.display_name} />
          <Fact label="Aliases" value={person.aliases && person.aliases.length > 0 ? person.aliases.join(", ") : null} />
          <Fact label="Date of birth" value={person.date_of_birth} />
          <Fact label="Age" value={person.age} />
          <Fact label="Sex" value={person.sex} />
          <Fact label="Height" value={height} />
          <Fact label="Weight" value={weight} />
          <Fact label="Hair color" value={person.hair_color} />
          <Fact label="Eye color" value={person.eye_color} />
          <Fact label="Distinguishing characteristics" value={person.distinguishing_characteristics} />
        </dl>
      </section>

      <section aria-labelledby="case-heading">
        <h3 id="case-heading">Case</h3>
        <dl>
          <Fact label="Status" value={data.case_status} />
          <Fact label="Missing date" value={data.missing_date} />
          <Fact label="Missing location" value={location || null} />
          <Fact label="Age at time of disappearance" value={data.age_at_missing} />
          <Fact label="Investigating agency" value={data.investigating_agency} />
          <Fact label="Agency case number" value={data.agency_case_number} />
        </dl>
        {data.circumstances && (
          <>
            <h4>Circumstances</h4>
            <p>{data.circumstances}</p>
          </>
        )}
      </section>

      <section aria-labelledby="provenance-heading">
        <h3 id="provenance-heading">Sources</h3>
        <ul className="source-list">
          {data.sources.map((source) => (
            <SourceCard key={`${source.code}-${source.external_id}`} source={source} />
          ))}
        </ul>
      </section>
    </article>
  );
}

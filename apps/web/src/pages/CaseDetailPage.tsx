import { Link, useParams } from "react-router-dom";
import { useCaseDetail } from "../hooks/useCaseDetail";
import { PhotoThumbnail } from "../components/PhotoThumbnail";
import { SourceBadge } from "../components/SourceBadge";
import type { CaseSourceRead } from "../api/types";
import { formatDateOnly, formatDateTime, formatHeight, formatLocation, formatWeight } from "../utils/format";

/** Renders one labeled fact, or nothing at all when the value is unknown -- this
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

/** A compact hero-style fact -- label above, value below -- distinct from the denser
 * `.fact` row style used further down the page, so the hero doesn't read like a table. */
function HeroFact({ label, value }: { label: string; value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="hero-fact">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function SourceCard({ source }: { source: CaseSourceRead }) {
  const contributedEntries = source.contributed_fields ? Object.entries(source.contributed_fields) : [];

  return (
    <li className="source-card">
      <div className="source-card-heading">
        <SourceBadge code={source.code} />
        <h4>{source.name}</h4>
      </div>

      {source.source_url && (
        <p>
          <a href={source.source_url} target="_blank" rel="noopener noreferrer">
            Original source
          </a>
        </p>
      )}
      <dl>
        <Fact label="Source last modified" value={formatDateTime(source.source_modified_at)} />
      </dl>

      <details className="technical-provenance">
        <summary>Technical provenance details</summary>
        <dl>
          <Fact label="Source record ID" value={source.external_id} />
          <Fact label="Record first seen by this platform" value={formatDateTime(source.first_seen_at)} />
          <Fact label="Record last seen by this platform" value={formatDateTime(source.last_seen_at)} />
        </dl>
        {contributedEntries.length > 0 && (
          <>
            <p className="technical-provenance-label">Data reported by this source:</p>
            <dl>
              {contributedEntries.map(([key, value]) => (
                <div className="fact" key={key}>
                  <dt>{key}</dt>
                  <dd>{value === null ? "Not available" : String(value)}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
      </details>
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
  const [primaryPhoto, ...morePhotos] = person.photos;
  const location = formatLocation(data.missing_city, data.missing_county, data.missing_state, data.missing_country);
  const sourceCodes = [...new Set(data.sources.map((source) => source.code))];

  const hasPersonExtras = Boolean(
    (person.aliases && person.aliases.length > 0) || person.distinguishing_characteristics,
  );
  const hasCaseExtras = Boolean(
    data.case_status || data.age_at_missing != null || data.investigating_agency || data.agency_case_number,
  );

  return (
    <article>
      <p>
        <Link to="/">&larr; Back to search</Link>
      </p>

      <header className="case-hero">
        <div className="case-hero-photos">
          <PhotoThumbnail
            src={primaryPhoto?.url ?? null}
            alt={`Photo of ${person.display_name}`}
            className="hero-photo-primary"
          />
          {morePhotos.length > 0 && (
            <ul className="hero-photo-secondary-list">
              {morePhotos.map((photo, index) => (
                <li key={photo.url ?? index}>
                  <PhotoThumbnail
                    src={photo.url}
                    alt={photo.caption ?? `Additional photo of ${person.display_name}`}
                    className="hero-photo-secondary"
                  />
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="case-hero-summary">
          <h2>{person.display_name}</h2>
          {sourceCodes.length > 0 && (
            <div className="source-badges">
              {sourceCodes.map((code) => (
                <SourceBadge key={code} code={code} />
              ))}
            </div>
          )}
          <dl className="hero-facts">
            <HeroFact label="Date of birth" value={formatDateOnly(person.date_of_birth)} />
            <HeroFact label="Sex" value={person.sex} />
            <HeroFact label="Height" value={formatHeight(person.height)} />
            <HeroFact label="Weight" value={formatWeight(person.weight)} />
            <HeroFact label="Hair color" value={person.hair_color} />
            <HeroFact label="Eye color" value={person.eye_color} />
            <HeroFact label="Missing date" value={formatDateOnly(data.missing_date)} />
            <HeroFact label="Missing location" value={location} />
          </dl>
        </div>
      </header>

      {hasPersonExtras && (
        <section aria-labelledby="person-heading">
          <h3 id="person-heading">Additional person details</h3>
          <dl>
            <Fact
              label="Aliases"
              value={person.aliases && person.aliases.length > 0 ? person.aliases.join(", ") : null}
            />
            <Fact label="Distinguishing characteristics" value={person.distinguishing_characteristics} />
          </dl>
        </section>
      )}

      {hasCaseExtras && (
        <section aria-labelledby="case-heading">
          <h3 id="case-heading">Case details</h3>
          <dl>
            <Fact label="Status" value={data.case_status} />
            <Fact label="Age at time of disappearance" value={data.age_at_missing} />
            <Fact label="Investigating agency" value={data.investigating_agency} />
            <Fact label="Agency case number" value={data.agency_case_number} />
          </dl>
        </section>
      )}

      {data.circumstances && (
        <section aria-labelledby="circumstances-heading" className="circumstances">
          <h3 id="circumstances-heading">Circumstances</h3>
          <p>{data.circumstances}</p>
        </section>
      )}

      <section aria-labelledby="provenance-heading">
        <h3 id="provenance-heading">Source information</h3>
        <ul className="source-list">
          {data.sources.map((source) => (
            <SourceCard key={`${source.code}-${source.external_id}`} source={source} />
          ))}
        </ul>
      </section>
    </article>
  );
}

import { useState } from "react";

interface PhotoThumbnailProps {
  src: string | null;
  alt: string;
  className?: string;
}

/** Gracefully handles a missing or broken photo URL -- never analyzes, generates, or
 * modifies image content, per this platform's principles. */
export function PhotoThumbnail({ src, alt, className }: PhotoThumbnailProps) {
  const [failed, setFailed] = useState(false);

  if (!src || failed) {
    return (
      <div className={`photo-placeholder ${className ?? ""}`} role="img" aria-label={`${alt} (photo not available)`}>
        <span aria-hidden="true">No photo</span>
      </div>
    );
  }

  return <img src={src} alt={alt} className={className} onError={() => setFailed(true)} loading="lazy" />;
}

/** Still placeholders in the shape of what is loading. */
export function Bar({ w, h = 10, className = "" }: { w: number | string; h?: number; className?: string }) {
  return <span aria-hidden className={`skeleton block ${className}`} style={{ width: w, height: h }} />;
}

// Widths that vary like real names do, so the rows don't look like a barcode
const WIDTHS = ["62%", "48%", "71%", "55%", "40%", "66%", "52%", "58%", "45%", "69%"];

export function skeletonWidth(i: number): string {
  return WIDTHS[i % WIDTHS.length];
}

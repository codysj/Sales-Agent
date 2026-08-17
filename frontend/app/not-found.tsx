import Link from "next/link";

/**
 * The page for a URL that is not a page (T-217).
 *
 * Next serves one of its own otherwise, and it is the single screen in the application that the
 * stylesheet cannot reach usefully: it renders its own inline styles, black text and no
 * background, which on this design's desk is black on graphite. A reviewer who mistypes a
 * candidate id would meet it, and "the dashboard is broken" is the reasonable thing to conclude
 * from an unreadable screen.
 *
 * It says which address was wrong rather than only that something was, and it offers the way
 * back — a dead end with no exit is how a rehearsal run ends early.
 */
export default function NotFound() {
  return (
    <main>
      <h1>That page does not exist</h1>
      <p>
        The address you asked for is not part of this dashboard. If you followed a link to a
        candidate, the id in it may be wrong or the candidate may have been removed.
      </p>
      <p>
        <Link href="/">Back to the dashboard</Link>
      </p>
    </main>
  );
}

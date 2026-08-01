import Link from "next/link";

/**
 * The dashboard's entry page (T-159; §12.3, §19.6 Stage 2 exit gate).
 *
 * **It says what is here, and it is the way in.** `T-060a` wrote this as a scaffold that
 * truthfully reported an empty dashboard — "the review queue is not built yet", "this dashboard
 * does not read them yet" — and that stopped being true at `T-063a`. A reviewer arriving at
 * **G-10** would have been told the thing they came to do does not exist, and then given no link
 * to it: every page was reachable only by typing a URL.
 *
 * **Nothing is claimed that is not built.** The candidate queue *index* is a page nobody has
 * written (`T-160`); the backend serves the list, the dashboard does not render it yet. Saying so
 * plainly is the point of this page — a link to a route that 404s would be worse than the stale
 * copy it replaces, and "the queue is there somewhere" is exactly the impression that makes a
 * non-engineer give up.
 *
 * **Plain `next/link`, no navigation component.** Two destinations do not need an abstraction,
 * and ADR-021 defers styling until a screen needs it. When there is a queue index and an
 * operations panel (`T-069`) this becomes a nav; it is not one yet.
 */
export default function Home() {
  return (
    <main>
      <h1>Matrix Power — review dashboard</h1>
      <p>
        This is the authoritative interface for reviewing candidates and approving exact message
        revisions. Nothing is sent from here without an explicit human approval, and live sending
        is gated (G-07) behind a separate authorization.
      </p>

      <nav aria-label="Dashboard sections">
        <ul>
          <li>
            <Link href="/sign-in">Sign in</Link> — every page below needs a session.
          </li>
          <li>
            <Link href="/review">Review queue</Link> — candidates waiting on a decision and
            messages waiting on an approval, each row opening its card.
          </li>
          <li>
            <Link href="/attention">Approvals needing attention</Link> — approvals that were
            granted and no longer authorize a send, each with the record that made it stale, and a
            way to revoke one.
          </li>
          <li>
            <Link href="/operations">Operations</Link> — the safety posture, what is queued, dead
            jobs with their reasons, and the pause and shadow-mode switches. Administrators only.
          </li>
        </ul>
      </nav>

      <h2>Reviewing a candidate</h2>
      <p>
        A candidate&rsquo;s review card — evidence, product readiness, approved claims, suppression
        warnings, the exact draft, and the approve, edit, reject, defer, and request-more-research
        actions — opens from the queue, or directly at{" "}
        <code>/review/&lt;candidate id&gt;</code>.
      </p>
    </main>
  );
}

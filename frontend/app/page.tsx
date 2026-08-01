/**
 * The dashboard's entry page.
 *
 * Deliberately static. `T-060a` proves the toolchain — lint, types, build, tests — and nothing
 * else; the review queue is `T-062` and it needs the generated client `T-060b` has not written
 * yet. A placeholder that fetched something would make this task's "the scaffold fetches
 * nothing" criterion untestable, and would be the first data-fetching code in the repository
 * written before there was a typed contract to fetch against (§23).
 *
 * The text says what the dashboard is *for* rather than filling space, because the next person
 * to open this file should be able to tell whether the queue is missing or merely empty.
 */
export default function Home() {
  return (
    <main>
      <h1>Matrix Power — review dashboard</h1>
      <p>
        This is the authoritative interface for reviewing candidates and approving exact message
        revisions. Nothing is sent from here without an explicit approval.
      </p>
      <p>
        The review queue is not built yet. The backend pipeline runs in shadow mode and produces
        review-ready drafts; this dashboard does not read them yet.
      </p>
    </main>
  );
}

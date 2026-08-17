# ADR-031 — The review desk has a visual design, and it is one stylesheet of element selectors

- **Status:** ACCEPTED (2026-08-15)
- **Scope:** Local to this repository. Answers the styling question [ADR-021](ADR-021-frontend-toolchain-defaults.md) deferred, and corrects where that deferral was addressed.
- **Specification basis:** §12.3 (the dashboard is the authoritative review and approval interface), §19.6 Stage 2 exit gate (**G-10**: a non-engineer completes reviews unaided), §10.5 (an approval names exact text), §19.3 (entailment checking is not in scope).
- **Implemented by:** `T-217` (`frontend/app/globals.css`).

## The trigger, and why it is a trigger

ADR-021 deferred styling deliberately, and the deferral was right: *"None yet — deferred to the
first screen that needs it."* Nothing should be chosen against imagined requirements.

Two things then happened. The first is that the condition came true. `T-071b` sits a non-engineer
in front of this dashboard once, and their first impression is not repeatable — it *is* the
measurement. Every rehearsal reading so far has judged the words and never the screen, because
screenshots failed in all of them; one reader said so explicitly, that they could say nothing
about layout, hierarchy, or whether the warnings are actually prominent. The suppression warning
is a `role="alert"`, and whether it **looks** like one had never been assessed by anybody.

The second is that the deferral had been posted to an address that could not receive it. ADR-021
named `T-062` as the place the decision would be made. **`T-062` is server-side RBAC enforcement**;
it closed on 2026-07-31 without touching styling, because styling was never in its scope. For two
weeks after that, later tasks went on scoping styling out and citing a deferral whose destination
was already gone. That is the more useful half of this record: the deferral was sound and its
*pointer* was not, and a pointer nobody re-reads fails silently. ADR-021's "Revisit if" now names
a condition — the first screen that needs it — rather than a task.

## Decision

**One stylesheet, `frontend/app/globals.css`, imported once by the root layout, written entirely
in element and attribute selectors. No `className` anywhere in the application.**

Every page here was already written as semantic HTML: `section` with a labelled heading, `dl` for
record fields, `blockquote` for an evidence excerpt, `pre` for the exact message, `role="alert"`
for the two things a reviewer must not miss. Styling that markup directly means no component
changed to gain a look, and it means the style follows the meaning — the next `role="alert"`
anybody writes is styled as an alert without anybody remembering to add a class.

The direction, in four decisions:

**Two registers, because the content genuinely has two.** The message and the evidence excerpts
are prose a human wrote for another human, and they are set as correspondence: a serif, at the
largest size on the page, at a measure of about 64 characters. Everything else is *record* —
labels, states, identifiers, timestamps — set small and quiet in the interface face, with
identifiers in mono. The hierarchy is inverted against dashboard convention on purpose: on this
screen the message outranks the chrome, because reading the exact words *is* the job, and a
reviewer who skims the one thing they must read exactly is the failure this interface exists to
prevent.

**The signature is the citation pairing.** Above 68rem the review card becomes two columns, and
the exact message sits beside the evidence and approved claims it cites. That relationship is
§10.5's thesis, and having to scroll between the message and the evidence is the review's actual
friction. It is done with CSS grid areas, so DOM order — and therefore reading order and tab
order — is unchanged.

**Nothing may imply entailment.** The system checks that a citation *resolves*. It has never
checked that a sentence *follows* from its evidence; that is §19.3 and `T-082`, and it is not
built. So the pairing is adjacency and nothing else: no line, no arrow, no tick, no matched
highlight between one sentence and one source. Adjacency says *"this message cites these"*, which
is true. A connector would say *"this sentence is supported by that"*, which the system does not
know — and a design that implies verification the system does not perform would lie to the one
person the entire safety model depends on. `tests/stylesheet.test.ts` asserts the stylesheet
generates no content, which is the only way a stylesheet could say it.

**The palette is spent on one signal.** One accent, `#8c1d18`, and it means *do not*: suppression,
and a revision that cannot be approved. It never carries the signal alone — an alert has a solid
bar, a wash, and a heavier weight, so it survives a monochrome screen and a colour-blind reader.
Everything else is ink, one grey, and one hairline.

## What was rejected

**A CSS framework, a component kit, or a design-system dependency.** ADR-021's argument against
all three stands unchanged, and this ADR does not overturn it — it satisfies the condition ADR-021
itself set. The whole design is one file of about 300 lines against markup that already existed;
a framework would have been 100× the dependency for less control over the one thing that matters
here, which is what the alert states look like.

**Web fonts.** The correspondence face is a system serif stack (Charter, Iowan Old Style,
Palatino, Georgia). A hosted font would be an external request from a tool that is deliberately
same-origin (`T-195`) and offline, and self-hosting one would be a binary in the repository for a
dashboard with four readers.

**A persistent "shadow mode is on" banner.** Tempting, and the direction argued for it: nothing
can be sent, and that is worth knowing on every screen. Rejected because shadow mode is a
**runtime fact** read from `/api/operations`, and a banner in the layout would be static markup
asserting it. A page that says "nothing can be sent" because somebody typed those words, rather
than because it asked, is exactly the class of claim this repository refuses everywhere else. If
it is worth showing globally it is worth *fetching* globally, and that is a task with a data
dependency, not a stylesheet.

**Distinguishing the approve button from the refuse button by colour.** The card offers five
consequential controls. Colouring approve green and refuse red would spend the palette on
something a reviewer must read anyway, and would compete with the one signal that means *do not*.
Each action is separated as its own labelled block instead, which is what actually stops a
misclick.

**Dark mode.** No reader has asked, and the design's ground is a light sheet on a dark desk, which
already reads at night. A second palette is a second thing to keep correct.

## Cost, stated plainly

The two-column card is the one rule with a failure mode worth naming: it places five sections by
explicit grid row, so a **sixth section added to the top of the card will land wrong**, and it
will land wrong visually rather than loudly. The comment at that rule says so. It is 25 lines
inside one media query, and reverting to a single column is deleting them.

Styling on element selectors means a component that stops using `role="alert"` silently loses its
alert styling. That is the same trade in reverse, and it is the right way round: the markup is the
source of truth, and a component that stops announcing an alert to a screen reader *should* stop
looking like one.

## Revisit if

- A screen needs a treatment the semantic markup cannot express — that is the point at which
  `className` earns its way in, one component at a time, not application-wide.
- `T-071b` observes a reviewer missing something this design made quiet. The rehearsal is the
  measurement this was built for, and its findings outrank every choice above.
- Entailment checking is ever built (§19.3, `T-082`), at which point the ban on connectors between
  a sentence and its evidence becomes a design question rather than a correctness one.
- A second reader group appears — someone reading this on a phone in a warehouse, say — since the
  narrow layout here is a fallback that has been measured but never watched in use.

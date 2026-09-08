import Link from "next/link";

// The link between the two models.
//
// Both are estimated and published every week, from the same ABS and RBA data,
// by two separate pipelines. Keeping v2 reachable is not sentiment: v3 was
// chosen on a 14-quarter backtest of 40 model runs, which is a thin sample, and
// the only thing that will settle it is the two of them running side by side on
// quarters neither has seen. A link is what makes that checkable by a reader
// rather than an assertion in a commit message.
//
// Deliberately at the foot of the page and understated. Someone arriving for
// the number should get the number; someone who wants to know what else exists
// will scroll.

interface Props {
  here: "v2" | "v3";
}

export default function ModelSwitch({ here }: Props) {
  const other = here === "v3"
    ? {
        href: "/v2",
        name: "v2",
        what: "Monthly Activity Indicator with a U-MIDAS regression, following RBA RDP 2024-04",
        why: "the model this site published until September 2026",
      }
    : {
        href: "/",
        name: "v3",
        what: "the New York Fed Staff Nowcast 2.0, ported to Python and refitted to Australian data",
        why: "the model this site publishes now",
      };

  return (
    <section className="mb-10 border-t border-border pt-4">
      <p className="text-[10px] uppercase tracking-wider text-label">
        The other model
      </p>
      <p className="mt-2 max-w-2xl text-sm">
        <Link href={other.href} className="underline hover:text-teal">
          {other.name}
        </Link>{" "}
        is {other.what} — {other.why}. Both run every week on the same data, so
        the two estimates can be compared as quarters land.
      </p>
    </section>
  );
}

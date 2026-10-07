import { useId, useLayoutEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import Tooltip from '../overlay/Tooltip';
import { useIsTruncated } from '../overlay/Truncated';
import { crumbsFor, documentTitleFor, type Crumb, type SurfaceId } from './ia';
import { useSurfaceSlot, type ContextTone } from './surfaceSlot';

/**
 * The Context Bar (§5).
 *
 * One shared implementation, rendered into the shell's single band. It carries
 * three things and nothing else: where the operator is, what state this surface
 * is in, and what they can do to it.
 *
 * §27.1 promotion: every archetype begins with this bar (§4), the semantics are
 * identical on each — identity, state, primary actions — the interaction
 * contract is the same (links navigate, actions act), and the accessibility
 * contract is the same (a labelled breadcrumb and one heading, inside the
 * workspace's `main`). The
 * variation points are the three slots, which is what a structural primitive
 * should vary by.
 *
 * Deliberately absent: a page title block and a description sentence. §4 removes
 * those from the product; moving them into permanent chrome would be keeping
 * them under a new name.
 */

export type { Crumb } from './ia';

export default function ContextBar({
  surface,
  object,
  rootTo,
  status,
  actions,
  tone,
}: {
  /**
   * Which §5 surface this is. The root crumb, the sub-surface word and the
   * document title all come from the IA map (`ia.ts`); a page never spells
   * them, which is what keeps the rail, the crumb and the title one word.
   */
  surface: SurfaceId;
  /** The object this surface is about — a camera, a video — when it has one. */
  object?: Crumb;
  /** Where the root crumb returns to, when that is not the destination itself (Review → its Investigation). */
  rootTo?: string;
  /** Key state badges for this surface. */
  status?: ReactNode;
  /** Primary actions for this surface. */
  actions?: ReactNode;
  /**
   * A state the whole surface is in, rather than one badge's worth of it.
   * §27.1 generalises the Scene Editor's read-only treatment: mistaking a past
   * revision for the live one is the expensive error, and a chip alone was
   * judged too quiet for it.
   */
  tone?: ContextTone;
}) {
  const crumbs = crumbsFor(surface, { object, rootTo });
  const title = documentTitleFor(crumbs);
  const slot = useSurfaceSlot();
  const register = slot?.register;
  const unregister = slot?.unregister;
  const element = slot?.element ?? null;
  const id = useId();

  // Owning the band and publishing into it are the same fact, so they are
  // decided by the same condition — there is somewhere to publish, and this
  // surface is publishing there — and registered in one call.
  //
  // This is a layout effect, not a passive one, and that is the whole point.
  // React flushes state updates scheduled during the layout phase before the
  // browser paints, so the commit where the shell still believes it owns the
  // band is never a painted frame. A passive effect carries no such guarantee,
  // which is how the band came to show two crumb trails on the way in and none
  // on the way out. The tone rides along rather than living in a second effect
  // that could be a frame behind the ownership it describes.
  useLayoutEffect(() => {
    if (!register || !unregister || !element) return undefined;
    // The document title rides the same registration as ownership and tone:
    // it is a fact about the surface that owns the band, and a title set from
    // a separate effect could name the previous surface for a frame.
    register(id, { tone: tone ?? null, title });
    return () => unregister(id);
  }, [register, unregister, element, id, tone, title]);

  const content = (
    <>
      {/* §4 removes the large page title *block* from the product; it does not
          remove the document's heading, and a surface with no h1 is harder to
          orient in by keyboard, not simpler. So the trail is also stated once
          as the heading — where a screen-reader user jumps to ask "where am
          I?" — and takes no space on screen. */}
      <h1 className="visually-hidden">{crumbs.map((crumb) => crumb.label).join(' — ')}</h1>
      <Breadcrumbs crumbs={crumbs} />
      {status ? <div className="context-bar__status">{status}</div> : null}
      <div className="context-bar__spacer" />
      {actions ? <div className="context-bar__actions">{actions}</div> : null}
    </>
  );

  // Outside the shell there is no band to publish into, so the bar renders
  // itself. A surface must not lose its identity, state and actions merely
  // because of where it was mounted — which is also what keeps a page testable
  // on its own rather than only through the whole application.
  if (!slot) return <div className={barClass(tone)}>{content}</div>;

  // Inside the shell, the band is the shell's. Before it exists there is
  // nowhere to render; the shell shows its own fallback for that one frame.
  if (!slot.element) return null;
  return createPortal(content, slot.element);
}

/** The band's class, so the shell and the standalone case cannot diverge. */
export function barClass(tone: ContextTone | null | undefined): string {
  return tone ? `context-bar context-bar--${tone}` : 'context-bar';
}

export function Breadcrumbs({ crumbs }: { crumbs: readonly Crumb[] }) {
  return (
    <nav className="context-bar__crumbs" aria-label="Breadcrumb">
      <ol>
        {crumbs.map((crumb, index) => (
          <CrumbItem key={`${crumb.label}-${index}`} crumb={crumb} last={index === crumbs.length - 1} />
        ))}
      </ol>
    </nav>
  );
}

/**
 * One crumb. A crumb truncates with an ellipsis rather than pushing the bar's
 * state and actions off the end (§37.1, long names); while it is cut off its
 * full text is a tooltip on hover and on keyboard focus — the current crumb
 * becomes focusable for exactly that long — and it is always complete in the
 * document title and the bar's heading.
 */
function CrumbItem({ crumb, last }: { crumb: Crumb; last: boolean }) {
  const [attachLink, linkTruncated] = useIsTruncated<HTMLAnchorElement>(crumb.label);
  const [attachText, textTruncated] = useIsTruncated<HTMLSpanElement>(crumb.label);
  return (
    <li className={crumb.dynamic ? 'context-bar__crumb context-bar__crumb--object' : 'context-bar__crumb'}>
      {crumb.to && !last ? (
        <Tooltip content={crumb.label} enabled={linkTruncated}>
          <Link ref={attachLink} to={crumb.to}>{crumb.label}</Link>
        </Tooltip>
      ) : (
        <Tooltip content={crumb.label} enabled={textTruncated}>
          <span ref={attachText} aria-current={last ? 'page' : undefined} tabIndex={textTruncated ? 0 : undefined}>
            {crumb.label}
          </span>
        </Tooltip>
      )}
    </li>
  );
}

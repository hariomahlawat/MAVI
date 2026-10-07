import { useEffect, type RefObject } from 'react';

/**
 * After a submit that the form itself refused, bring the first invalid field
 * into view and give it focus (§12, invalid): "a rail or form that validates
 * off-screen is a defect".
 *
 * This is form orchestration, not a Field concern — a Field cannot know where
 * it sits in its form's reading order — so it lives with the form. It reads
 * the fields the form has marked `aria-invalid` and takes the first in
 * document order, which is the reading order of every form in the product.
 *
 * - It acts only when `attempt` changes, which the form bumps on a refused
 *   submit and on nothing else: a server failure that no field owns, a
 *   successful submit or a re-render never moves focus.
 * - The scroll is immediate (`behavior` left at its instant default) and
 *   minimal (`nearest`): the field appears where the operator can see it, and
 *   nothing animates (§13).
 * - The field's inline message stays the explanation; this only moves the
 *   operator to it.
 */
export function useFocusFirstInvalid(formRef: RefObject<HTMLElement | null>, attempt: number): void {
  useEffect(() => {
    if (attempt === 0) return;
    const first = formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]');
    if (!first) return;
    if (typeof first.scrollIntoView === 'function') first.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    first.focus({ preventScroll: true });
    // `attempt` is the only trigger; the ref is stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);
}

/** M0.4 validation rule 4 (and M0.9 "no number without a tooltip"): any text containing a digit
 * must sit inside a <Metric> ([data-metric]) or an identifier ([data-identifier]). A publisher's
 * own words shown verbatim (news headlines and summaries, [data-quoted]) are not our numbers. */
export function unexplainedNumbers(root: HTMLElement): string[] {
  const walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const offenders: string[] = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = node.textContent ?? "";
    if (/\d/.test(text) && !node.parentElement?.closest("[data-metric],[data-identifier],[data-quoted]")) {
      offenders.push(text.trim());
    }
  }
  return offenders;
}

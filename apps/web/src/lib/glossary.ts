import { GLOSSARY, type CompleteTermId } from "@/generated/glossary";

/** A term id from API data (e.g. a macro series' term_id), if it is a complete glossary term. */
export function completeTermId(id: string): CompleteTermId | null {
  return Object.hasOwn(GLOSSARY, id) ? (id as CompleteTermId) : null;
}

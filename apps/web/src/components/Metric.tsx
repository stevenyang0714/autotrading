"use client";

import { type ReactNode, useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { GLOSSARY, type CompleteTermId } from "@/generated/glossary";

interface MetricProps {
  /** Only complete glossary terms type-check: an unknown or unfinished term fails `tsc`. */
  termId: CompleteTermId;
  /** The displayed value or label; defaults to the term's display name. */
  children?: ReactNode;
  /** Show the "?" button (headings, column headers, badges). Off for dense values and nav. */
  icon?: boolean;
  placement?: "below" | "right";
  className?: string;
}

interface Position {
  top: number;
  left: number;
}

const GAP = 6;
const MARGIN = 8;

/**
 * The only way to render a metric, score, badge, status, risk measure, strategy or dashboard
 * label (02 §22, CLAUDE.md). Hover or keyboard focus shows a compact tooltip; the "?" button
 * (tap on mobile) opens the full glossary entry. Escape or an outside click closes it.
 *
 * The tooltip and panel render in a portal with fixed positioning, so table scroll areas and
 * nowrap cells cannot clip or squash them. They carry data-metric too: their text is the
 * explanation of this metric.
 */
export function Metric({ termId, children, icon = true, placement = "below", className }: MetricProps) {
  const term = GLOSSARY[termId];
  const [hovered, setHovered] = useState(false);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState<Position | null>(null);
  const root = useRef<HTMLSpanElement>(null);
  const panel = useRef<HTMLSpanElement>(null);
  const id = useId();
  const tooltipId = `${id}-tooltip`;
  const panelId = `${id}-panel`;
  const visible = open || hovered;

  const place = useCallback(() => {
    const anchor = root.current?.getBoundingClientRect();
    if (!anchor) return;
    const width = open ? 320 : 256;
    const maxLeft = window.innerWidth - width - MARGIN;
    const left =
      placement === "right" ? anchor.right + GAP : Math.min(Math.max(anchor.left, MARGIN), maxLeft);
    const top = placement === "right" ? anchor.top : anchor.bottom + GAP;
    setPosition({ top, left: Math.max(MARGIN, Math.min(left, maxLeft)) });
  }, [open, placement]);

  useLayoutEffect(() => {
    if (visible) place();
  }, [visible, place]);

  useEffect(() => {
    if (!visible) return;
    const onMove = () => (open ? place() : setHovered(false));
    window.addEventListener("scroll", onMove, true);
    window.addEventListener("resize", onMove);
    return () => {
      window.removeEventListener("scroll", onMove, true);
      window.removeEventListener("resize", onMove);
    };
  }, [visible, open, place]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!root.current?.contains(target) && !panel.current?.contains(target)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  const floating = "fixed z-50 block rounded border border-neutral-700 bg-neutral-900 text-left text-xs font-normal normal-case tracking-normal whitespace-normal text-neutral-100 shadow-xl";
  const style = position ? { top: position.top, left: position.left } : { visibility: "hidden" as const };

  return (
    <span
      ref={root}
      data-metric=""
      data-term-id={termId}
      className={`relative inline-flex items-center gap-1 ${className ?? ""}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setHovered(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") setHovered(false);
      }}
    >
      <span>{children ?? term.display_name}</span>
      {icon && (
        <button
          type="button"
          aria-label={`What is ${term.display_name}?`}
          aria-describedby={hovered && !open ? tooltipId : undefined}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((value) => !value)}
          className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-neutral-400 text-[10px] leading-none text-neutral-500 hover:border-neutral-200 hover:text-neutral-200"
        >
          ?
        </button>
      )}
      {hovered &&
        !open &&
        createPortal(
          <span
            role="tooltip"
            id={tooltipId}
            data-metric=""
            data-term-id={termId}
            style={style}
            className={`${floating} pointer-events-none w-64 p-2`}
          >
            <span className="block font-medium">{term.display_name}</span>
            <span className="mt-1 block">{term.short_definition}</span>
            <span className="mt-1 block text-neutral-400">{term.interpretation}</span>
          </span>,
          document.body,
        )}
      {open &&
        createPortal(
          <span
            ref={panel}
            role="dialog"
            aria-label={term.display_name}
            id={panelId}
            data-metric=""
            data-term-id={termId}
            style={style}
            className={`${floating} w-80 max-w-[calc(100vw-16px)] p-3`}
          >
            <span className="flex items-start justify-between gap-2">
              <span className="font-medium">{term.display_name}</span>
              <button
                type="button"
                aria-label="Close"
                onClick={() => setOpen(false)}
                className="text-neutral-400 hover:text-neutral-100"
              >
                ×
              </button>
            </span>
            <span className="mt-2 block">{term.full_definition}</span>
            <Field label="Formula">{term.formula}</Field>
            <Field label="Unit">{term.unit}</Field>
            <Field label="Direction">{term.direction}</Field>
            <Field label="Example">{term.example}</Field>
            <Field label="Why it matters">{term.why_it_matters}</Field>
            <Field label="Caveats">{term.caveats}</Field>
            <span className="mt-2 block text-neutral-400">
              Source:{" "}
              <a href={term.source_url} target="_blank" rel="noreferrer" className="underline">
                {term.source}
              </a>
            </span>
            <span className="mt-1 block text-neutral-500">
              Methodology {term.methodology_version} · as of {term.as_of}
            </span>
          </span>,
          document.body,
        )}
    </span>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="mt-2 block">
      <span className="text-neutral-400">{label}: </span>
      {children}
    </span>
  );
}

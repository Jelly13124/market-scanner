// Default canvas seed — five horizontal rows fanning out from the Input
// node, covering all 16 SOP sections plus a visual "Manager Check"
// terminator.
//
// Layout (left-to-right):
//
//   [Input] ─┬─→ Data Health ──→ Macro ───────→ Sector
//            ├─→ Company Fund. ─→ Financial St. ─→ Valuation
//            ├─→ Technical ────→ Risk Position ─→ Event Risk
//            ├─→ Evidence Ldg. ─→ Scenarios ────→ Conviction
//            └─→ Debate ──────→ Final Strategy ─→ Executive Summary ─→ [Manager Check]
//
// Manager Check is a visual-only terminator (orchestrator skips unknown
// section names, which is what we want here — the name "manager_check"
// is not in SECTION_ORDER so the runner ignores it).

import type { Edge, Node } from '@xyflow/react';

import {
  SECTION_LABELS, SECTION_ORDER, SECTION_PERSONAS,
} from '@/types/analyze';

import { DEFAULT_INPUT_NODE_DATA } from './input-node';
import type { SectionNodeData } from './section-node';

const INPUT_NODE_ID = 'input:run';
const MANAGER_NODE_ID = 'section:manager_check';

/** Horizontal stride between successive nodes in a row (px). */
const COL_W = 230;
/** Vertical stride between rows (px). */
const ROW_H = 150;
/** Left margin for the input node. */
const INPUT_X = 40;
/** Top margin for the topmost row. */
const ROW_Y0 = 60;
/** X position where the first SectionNode column begins (right of input). */
const COL_X0 = 360;

/** Section ids per row, ordered left-to-right. */
const ROWS: string[][] = [
  ['data_health', 'macro', 'sector'],
  ['company_fundamentals', 'financial_statements', 'valuation'],
  ['technical', 'risk_position', 'event_risk'],
  ['evidence_ledger', 'scenarios', 'conviction'],
  ['debate', 'final_strategy', 'executive_summary'],
];

function _sectionNodeId(name: string): string {
  return `section:${name}`;
}

function _buildSectionNode(
  name: string, x: number, y: number,
  opts: { label?: string; enabled?: boolean } = {},
): Node {
  const supports = SECTION_PERSONAS[name] ?? [];
  const data: SectionNodeData = {
    name,
    label: opts.label ?? SECTION_LABELS[name] ?? name,
    enabled: opts.enabled ?? true,
    persona: null,
    supportsPersonas: supports,
  };
  return {
    id: _sectionNodeId(name),
    type: 'section',
    position: { x, y },
    data: data as unknown as Record<string, unknown>,
  };
}

/** Build the default template's nodes + edges. Always returns a fresh
 * deep-cloned object so callers can mutate without affecting future
 * seeds. */
export function getDefaultTemplate(): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // 1) Input node — vertically centred against the middle row.
  const inputY = ROW_Y0 + Math.floor(ROWS.length / 2) * ROW_H;
  nodes.push({
    id: INPUT_NODE_ID,
    type: 'input',
    position: { x: INPUT_X, y: inputY - 40 },
    data: { ...DEFAULT_INPUT_NODE_DATA } as unknown as Record<string, unknown>,
  });

  // 2) Section nodes — one row per pipeline branch.
  for (let r = 0; r < ROWS.length; r++) {
    const row = ROWS[r];
    const y = ROW_Y0 + r * ROW_H;
    let prevId: string = INPUT_NODE_ID;
    for (let c = 0; c < row.length; c++) {
      const name = row[c];
      const x = COL_X0 + c * COL_W;
      nodes.push(_buildSectionNode(name, x, y));
      const id = _sectionNodeId(name);
      edges.push({
        id: `e:${prevId}->${id}`,
        source: prevId,
        target: id,
        animated: c === 0,        // highlight the input→first-of-row hop
      });
      prevId = id;
    }
    // Terminal Manager Check on the last row only.
    if (r === ROWS.length - 1) {
      const x = COL_X0 + row.length * COL_W;
      nodes.push(
        _buildSectionNode('manager_check', x, y, { label: 'Manager Check', enabled: true }),
      );
      edges.push({
        id: `e:${prevId}->${MANAGER_NODE_ID}`,
        source: prevId,
        target: MANAGER_NODE_ID,
      });
    }
  }

  // 3) Sanity: every SECTION_ORDER entry covered by the rows above,
  //    plus 'missing_data' which we tack onto the bottom row as a side
  //    branch off Executive Summary so the canvas surfaces it.
  const covered = new Set<string>();
  for (const row of ROWS) for (const s of row) covered.add(s);
  const missing = SECTION_ORDER.filter((s) => !covered.has(s));
  for (let i = 0; i < missing.length; i++) {
    const name = missing[i];
    const x = COL_X0 + i * COL_W;
    const y = ROW_Y0 + (ROWS.length + 1) * ROW_H;  // a row below the pipeline
    nodes.push(_buildSectionNode(name, x, y));
    edges.push({
      id: `e:${INPUT_NODE_ID}->${_sectionNodeId(name)}`,
      source: INPUT_NODE_ID,
      target: _sectionNodeId(name),
    });
  }

  return { nodes, edges };
}

export const INPUT_NODE_ID_CONST = INPUT_NODE_ID;

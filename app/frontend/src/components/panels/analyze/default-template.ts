// Default canvas seed — Phase 5E redesign per user 2026-05-25.
//
// Pipeline shape (left to right):
//
//   [Input] → [Data Health] → 10 parallel analyses → [Debate] → [Output]
//
// The 10 mid-sections (macro / sector / company_fundamentals /
// financial_statements / valuation / technical / risk_position /
// scenarios / conviction / event_risk) all consume the same upstream
// (shared data + data_health verdict) and produce independent
// SectionPayloads. They feed BOTH Debate (which weighs them) and
// Output (which writes the final report from them + Debate's verdict).
//
// The Output node is a single visual aggregator that the canvas
// serializer expands to four backend SECTION_ORDER entries:
// evidence_ledger, final_strategy, executive_summary, missing_data.

import type { Edge, Node } from '@xyflow/react';

import { SECTION_LABELS, SECTION_PERSONAS } from '@/types/analyze';

import { DEFAULT_INPUT_NODE_DATA } from './input-node';
import type { SectionNodeData } from './section-node';

const INPUT_NODE_ID = 'input:run';
const OUTPUT_NODE_ID = 'output:report';

/** Sections that run in parallel after Data Health. Order here only
 * controls vertical layout on the canvas — the backend dispatches via
 * SECTION_ORDER and (after this change) gathers these concurrently. */
const PARALLEL_SECTIONS: string[] = [
  'macro',
  'sector',
  'company_fundamentals',
  'financial_statements',
  'valuation',
  'technical',
  'risk_position',
  'scenarios',
  'conviction',
  'event_risk',
];

/** The 4 backend sections that the single visual Output node represents. */
export const OUTPUT_BACKEND_SECTIONS: string[] = [
  'evidence_ledger',
  'final_strategy',
  'executive_summary',
  'missing_data',
];

// --- Layout constants. Tuned for nodes at min-w 380-440. ---
const COL_INPUT_X = 40;
const COL_DATAHEALTH_X = 520;
const COL_PARALLEL_LEFT_X = 1000;
const COL_PARALLEL_RIGHT_X = 1500;
const COL_DEBATE_X = 2080;
const COL_OUTPUT_X = 2560;

const PARALLEL_ROW_TOP = 40;
const PARALLEL_ROW_H = 200;
const PARALLEL_ROWS_PER_COL = 5;   // 5 rows × 2 cols = 10 sections

/** Y position for the single-row nodes (Input / Data Health / Debate / Output)
 * so they line up with the vertical middle of the 5-row parallel block. */
const CENTER_Y = PARALLEL_ROW_TOP + Math.floor(PARALLEL_ROWS_PER_COL / 2) * PARALLEL_ROW_H;

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

/** Build the default template — Input → Data Health → 10 parallel →
 * Debate → Output. */
export function getDefaultTemplate(): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // 1) Input — leftmost, centered.
  nodes.push({
    id: INPUT_NODE_ID,
    type: 'input',
    position: { x: COL_INPUT_X, y: CENTER_Y - 40 },
    data: { ...DEFAULT_INPUT_NODE_DATA } as unknown as Record<string, unknown>,
  });

  // 2) Data Health — single gating step after Input, centered.
  const dataHealthId = _sectionNodeId('data_health');
  nodes.push(_buildSectionNode('data_health', COL_DATAHEALTH_X, CENTER_Y));
  edges.push({
    id: `e:${INPUT_NODE_ID}->${dataHealthId}`,
    source: INPUT_NODE_ID,
    target: dataHealthId,
    animated: true,
  });

  // 3) 10 parallel analyses — 2 columns × 5 rows. Each gets an edge
  //    FROM data_health, and edges TO both Debate and Output.
  const debateId = _sectionNodeId('debate');
  PARALLEL_SECTIONS.forEach((name, i) => {
    const col = Math.floor(i / PARALLEL_ROWS_PER_COL);
    const row = i % PARALLEL_ROWS_PER_COL;
    const x = col === 0 ? COL_PARALLEL_LEFT_X : COL_PARALLEL_RIGHT_X;
    const y = PARALLEL_ROW_TOP + row * PARALLEL_ROW_H;
    nodes.push(_buildSectionNode(name, x, y));
    const sid = _sectionNodeId(name);
    edges.push({
      id: `e:${dataHealthId}->${sid}`,
      source: dataHealthId,
      target: sid,
    });
    // → Debate
    edges.push({
      id: `e:${sid}->${debateId}`,
      source: sid,
      target: debateId,
    });
    // → Output (per user 2026-05-25: 10 analyses feed BOTH Debate and Output)
    edges.push({
      id: `e:${sid}->${OUTPUT_NODE_ID}`,
      source: sid,
      target: OUTPUT_NODE_ID,
    });
  });

  // 4) Debate — single node, centered.
  nodes.push(_buildSectionNode('debate', COL_DEBATE_X, CENTER_Y));

  // 5) Output — visual aggregator. Single canvas node that the
  //    serializer expands to OUTPUT_BACKEND_SECTIONS.
  nodes.push({
    id: OUTPUT_NODE_ID,
    type: 'output',
    position: { x: COL_OUTPUT_X, y: CENTER_Y - 40 },
    data: { enabled: true } as Record<string, unknown>,
  });
  edges.push({
    id: `e:${debateId}->${OUTPUT_NODE_ID}`,
    source: debateId,
    target: OUTPUT_NODE_ID,
    animated: true,
  });

  return { nodes, edges };
}

export const INPUT_NODE_ID_CONST = INPUT_NODE_ID;
export const OUTPUT_NODE_ID_CONST = OUTPUT_NODE_ID;

// React Flow canvas for the Analyze panel.
//
// Owns nodes + edges and exposes an imperative handle so the parent
// panel can:
//   * addSection(name) — palette click adds a node
//   * addInputNode() — palette click adds the single Input node
//   * focusInput()    — center viewport on the existing input node
//   * loadFlow(payload) — load a saved AnalyzeFlow template
//   * clear() — wipe canvas (back to default template seed)
//   * resetToDefault() — seed the full-pipeline template
//   * getConfig() — serialize current section nodes into the orchestrator
//                   { included_sections, persona_overrides } pair
//   * getInputData() — read the Input node's run-request fields
//   * hasInputNode() / getPresentSections() — helpers for the palette
//
// Edges are visual decoration only; the backend always dispatches in
// SECTION_ORDER (see src/research/sop_orchestrator.py).

import {
  Background,
  Controls,
  Edge,
  MiniMap,
  Node,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  forwardRef, useCallback, useImperativeHandle, useMemo,
} from 'react';

import { SECTION_LABELS, SECTION_ORDER, SECTION_PERSONAS } from '@/types/analyze';
import type { AnalyzeFlowResponse } from '@/types/analyze-flow';

import {
  getDefaultTemplate, INPUT_NODE_ID_CONST, OUTPUT_BACKEND_SECTIONS,
} from './default-template';
import { FlowCanvasContext, type FlowCanvasContextValue } from './flow-canvas-context';
import { DEFAULT_INPUT_NODE_DATA, InputNode, type InputNodeData } from './input-node';
import { OutputNode, type OutputNodeData } from './output-node';
import { SectionNode, type SectionNodeData } from './section-node';

/** Effective config the orchestrator needs (mirror of AnalyzeFlowCreate
 * minus the cosmetic name/use_personas). */
export interface CanvasConfig {
  included_sections: string[];
  persona_overrides: Record<string, string>;
}

/** Debate-node-derived run settings. Sourced from the Debate node's
 * `usePersonas` + `debateRounds` data when present; falls back to safe
 * defaults when the Debate node is absent from the canvas. */
export interface DebateSettings {
  use_personas: boolean;   // false when Debate node missing
  debate_rounds: number;   // default 3 (clamped 1..5)
}

export interface FlowCanvasHandle {
  addSection: (sectionName: string) => void;
  addInputNode: () => void;
  focusInput: () => void;
  loadFlow: (flow: AnalyzeFlowResponse) => void;
  clear: () => void;
  resetToDefault: () => void;
  getConfig: () => CanvasConfig;
  getInputData: () => InputNodeData | null;
  getDebateSettings: () => DebateSettings;
  getPresentSections: () => Set<string>;
  hasInputNode: () => boolean;
}

const nodeTypes = { section: SectionNode, input: InputNode, output: OutputNode };

function _sectionNodeId(sectionName: string): string {
  return `section:${sectionName}`;
}

function _buildSectionNode(sectionName: string, x: number, y: number): Node {
  const supports = SECTION_PERSONAS[sectionName] ?? [];
  const data: SectionNodeData = {
    name: sectionName,
    label: SECTION_LABELS[sectionName] ?? sectionName,
    enabled: true,
    persona: null,
    supportsPersonas: supports,
  };
  return {
    id: _sectionNodeId(sectionName),
    type: 'section',
    position: { x, y },
    data: data as unknown as Record<string, unknown>,
  };
}

function _buildInputNode(x: number, y: number): Node {
  return {
    id: INPUT_NODE_ID_CONST,
    type: 'input',
    position: { x, y },
    data: { ...DEFAULT_INPUT_NODE_DATA } as unknown as Record<string, unknown>,
  };
}

interface InnerCanvasProps {
  onChange?: () => void;
}

const InnerCanvas = forwardRef<FlowCanvasHandle, InnerCanvasProps>(
  function InnerCanvas({ onChange }, ref) {
    // Seed with the default full-pipeline template on first mount.
    const initialTemplate = useMemo(() => getDefaultTemplate(), []);
    const [nodes, setNodes, onNodesChange] = useNodesState(initialTemplate.nodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialTemplate.edges);
    const rf = useReactFlow();

    // Stable updateNodeData passed via context to every node.
    const updateNodeData = useCallback(
      (nodeId: string, patch: Partial<SectionNodeData> | Record<string, unknown>) => {
        setNodes((curr) =>
          curr.map((n) =>
            n.id === nodeId
              ? { ...n, data: { ...(n.data as object), ...patch } as Record<string, unknown> }
              : n,
          ),
        );
        onChange?.();
      },
      [setNodes, onChange],
    );

    // Stable deleteNode passed via context so node cards can self-remove
    // via their × button. Also drops any edges incident on the removed node.
    const deleteNode = useCallback(
      (nodeId: string) => {
        setNodes((curr) => curr.filter((n) => n.id !== nodeId));
        setEdges((curr) =>
          curr.filter((e) => e.source !== nodeId && e.target !== nodeId),
        );
        onChange?.();
      },
      [setNodes, setEdges, onChange],
    );

    const ctxValue: FlowCanvasContextValue = useMemo(
      () => ({ updateNodeData, deleteNode }),
      [updateNodeData, deleteNode],
    );

    const onConnect = useCallback(
      (params: Parameters<typeof addEdge>[0]) => {
        setEdges((eds) => addEdge(params, eds));
        onChange?.();
      },
      [setEdges, onChange],
    );

    useImperativeHandle(
      ref,
      () => ({
        addSection: (sectionName: string) => {
          const id = _sectionNodeId(sectionName);
          if (nodes.some((n) => n.id === id)) return;
          const viewport = rf.getViewport();
          const baseX = (200 - viewport.x) / (viewport.zoom || 1);
          const baseY = (120 - viewport.y) / (viewport.zoom || 1);
          const offset = (nodes.length % 8) * 30;
          const newNode = _buildSectionNode(sectionName, baseX + offset, baseY + offset);
          setNodes((curr) => [...curr, newNode]);
          onChange?.();
        },
        addInputNode: () => {
          // Idempotent — single input node per canvas
          if (nodes.some((n) => n.id === INPUT_NODE_ID_CONST)) return;
          const viewport = rf.getViewport();
          const x = (40 - viewport.x) / (viewport.zoom || 1);
          const y = (120 - viewport.y) / (viewport.zoom || 1);
          setNodes((curr) => [...curr, _buildInputNode(x, y)]);
          onChange?.();
        },
        focusInput: () => {
          const input = nodes.find((n) => n.id === INPUT_NODE_ID_CONST);
          if (!input) return;
          rf.setCenter(input.position.x + 130, input.position.y + 100, {
            zoom: rf.getViewport().zoom || 1,
            duration: 300,
          });
        },
        loadFlow: (flow: AnalyzeFlowResponse) => {
          const included = new Set(flow.included_sections ?? []);
          const overrides = flow.persona_overrides ?? {};
          // Re-create canvas: every SECTION_ORDER entry becomes a node,
          // with `enabled` derived from included_sections and `persona`
          // from the overrides dict. Always seed the Input node too so
          // the canvas is runnable straight after a load.
          const newNodes: Node[] = SECTION_ORDER.map((name, i) => {
            const node = _buildSectionNode(
              name, 360 + (i % 4) * 230, 60 + Math.floor(i / 4) * 150,
            );
            const data = node.data as unknown as SectionNodeData;
            data.enabled = included.has(name);
            data.persona = overrides[name] ?? null;
            return { ...node, data: data as unknown as Record<string, unknown> };
          });
          newNodes.unshift(_buildInputNode(40, 200));
          setNodes(newNodes);
          setEdges([]);
          onChange?.();
        },
        clear: () => {
          // "New blank" goes back to the default template, not a truly empty
          // canvas — a blank canvas can't run anything which confuses users.
          const t = getDefaultTemplate();
          setNodes(t.nodes);
          setEdges(t.edges);
          onChange?.();
        },
        resetToDefault: () => {
          const t = getDefaultTemplate();
          setNodes(t.nodes);
          setEdges(t.edges);
          onChange?.();
        },
        getConfig: () => {
          const included = new Set<string>();
          const overrides: Record<string, string> = {};
          for (const n of nodes) {
            // The Output node is a visual aggregator — when enabled it
            // expands to the 4 backend SECTION_ORDER entries it represents.
            if (n.type === 'output') {
              const od = n.data as unknown as OutputNodeData;
              if (od.enabled !== false) {
                for (const s of OUTPUT_BACKEND_SECTIONS) included.add(s);
              }
              continue;
            }
            if (n.type !== 'section') continue;
            const d = n.data as unknown as SectionNodeData;
            if (!d.enabled) continue;
            // Only canonical SECTION_ORDER names go to the backend; any
            // visual-only nodes are silently skipped.
            if (!SECTION_ORDER.includes(d.name)) continue;
            included.add(d.name);
            if (d.persona) overrides[d.name] = d.persona;
          }
          const sortedIncluded = Array.from(included).sort(
            (a, b) => SECTION_ORDER.indexOf(a) - SECTION_ORDER.indexOf(b),
          );
          return { included_sections: sortedIncluded, persona_overrides: overrides };
        },
        getInputData: () => {
          const input = nodes.find((n) => n.id === INPUT_NODE_ID_CONST);
          if (!input) return null;
          return input.data as unknown as InputNodeData;
        },
        getDebateSettings: () => {
          // Source of truth for use_personas + debate_rounds is the Debate
          // SectionNode. If absent (user deleted it), default to no-personas
          // and rounds=3 — the backend will still default debate_rounds
          // independently, but we want a defined value here.
          const debateNode = nodes.find(
            (n) => n.type === 'section'
              && (n.data as unknown as SectionNodeData).name === 'debate',
          );
          if (!debateNode) {
            return { use_personas: false, debate_rounds: 3 };
          }
          const d = debateNode.data as unknown as SectionNodeData;
          // Defaults match section-node.tsx UI defaults.
          const usePersonas = d.usePersonas ?? true;
          let rounds = d.debateRounds ?? 3;
          if (!Number.isFinite(rounds)) rounds = 3;
          rounds = Math.max(1, Math.min(5, Math.trunc(rounds)));
          return {
            use_personas: !!usePersonas && d.enabled !== false,
            debate_rounds: rounds,
          };
        },
        getPresentSections: () => {
          const present = new Set<string>();
          for (const n of nodes) {
            // Output node is present if its 4 backend sections are present.
            if (n.type === 'output') {
              for (const s of OUTPUT_BACKEND_SECTIONS) present.add(s);
              continue;
            }
            if (n.type !== 'section') continue;
            const d = n.data as unknown as SectionNodeData;
            present.add(d.name);
          }
          return present;
        },
        hasInputNode: () => nodes.some((n) => n.id === INPUT_NODE_ID_CONST),
      }),
      [nodes, setNodes, setEdges, rf, onChange],
    );

    return (
      <FlowCanvasContext.Provider value={ctxValue}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </FlowCanvasContext.Provider>
    );
  },
);

export interface FlowCanvasProps {
  onChange?: () => void;
}

export const FlowCanvas = forwardRef<FlowCanvasHandle, FlowCanvasProps>(
  function FlowCanvas(props, ref) {
    return (
      <ReactFlowProvider>
        <InnerCanvas ref={ref} onChange={props.onChange} />
      </ReactFlowProvider>
    );
  },
);

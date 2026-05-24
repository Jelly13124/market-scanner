// React Flow canvas for the Analyze panel.
//
// Owns the nodes + edges state and exposes an imperative handle so the
// parent panel can:
//   * addSection(name) — palette click adds a node
//   * loadFlow(payload) — load a saved AnalyzeFlow template
//   * clear() — wipe canvas
//   * getConfig() — serialize current nodes into the orchestrator-shaped
//                   { included_sections, persona_overrides } pair
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

import { FlowCanvasContext, type FlowCanvasContextValue } from './flow-canvas-context';
import { SectionNode, type SectionNodeData } from './section-node';

/** Effective config the orchestrator needs (mirror of AnalyzeFlowCreate
 * minus the cosmetic name/use_personas). */
export interface CanvasConfig {
  included_sections: string[];
  persona_overrides: Record<string, string>;
}

export interface FlowCanvasHandle {
  addSection: (sectionName: string) => void;
  loadFlow: (flow: AnalyzeFlowResponse) => void;
  clear: () => void;
  getConfig: () => CanvasConfig;
  getPresentSections: () => Set<string>;
}

const nodeTypes = { section: SectionNode };

function _nodeIdFor(sectionName: string): string {
  return `section:${sectionName}`;
}

function _buildNode(sectionName: string, x: number, y: number): Node {
  const supports = SECTION_PERSONAS[sectionName] ?? [];
  const data: SectionNodeData = {
    name: sectionName,
    label: SECTION_LABELS[sectionName] ?? sectionName,
    enabled: true,
    persona: null,
    supportsPersonas: supports,
  };
  return {
    id: _nodeIdFor(sectionName),
    type: 'section',
    position: { x, y },
    data: data as unknown as Record<string, unknown>,
  };
}

function _initialNodes(): Node[] {
  // Default canvas: all 16 sections, stacked vertically
  return SECTION_ORDER.map((name, i) =>
    _buildNode(name, 40 + (i % 2) * 280, 40 + Math.floor(i / 2) * 130),
  );
}

interface InnerCanvasProps {
  onChange?: () => void;
}

const InnerCanvas = forwardRef<FlowCanvasHandle, InnerCanvasProps>(
  function InnerCanvas({ onChange }, ref) {
    const [nodes, setNodes, onNodesChange] = useNodesState(_initialNodes());
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
    const rf = useReactFlow();

    // Stable updateNodeData passed via context to every SectionNode
    const updateNodeData = useCallback(
      (nodeId: string, patch: Partial<SectionNodeData>) => {
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

    const ctxValue: FlowCanvasContextValue = useMemo(
      () => ({ updateNodeData }),
      [updateNodeData],
    );

    useImperativeHandle(
      ref,
      () => ({
        addSection: (sectionName: string) => {
          const id = _nodeIdFor(sectionName);
          // Idempotent — if already on canvas, skip
          if (nodes.some((n) => n.id === id)) return;
          const viewport = rf.getViewport();
          // Place near centre of current view; offset by node count to avoid pile-up
          const baseX = (200 - viewport.x) / (viewport.zoom || 1);
          const baseY = (120 - viewport.y) / (viewport.zoom || 1);
          const offset = (nodes.length % 8) * 30;
          const newNode = _buildNode(sectionName, baseX + offset, baseY + offset);
          setNodes((curr) => [...curr, newNode]);
          onChange?.();
        },
        loadFlow: (flow: AnalyzeFlowResponse) => {
          const included = new Set(flow.included_sections ?? []);
          const overrides = flow.persona_overrides ?? {};
          // Re-create canvas: every SECTION_ORDER entry becomes a node,
          // with `enabled` derived from included_sections and `persona`
          // from the overrides dict.
          const newNodes: Node[] = SECTION_ORDER.map((name, i) => {
            const node = _buildNode(
              name, 40 + (i % 2) * 280, 40 + Math.floor(i / 2) * 130,
            );
            const data = node.data as unknown as SectionNodeData;
            data.enabled = included.has(name);
            data.persona = overrides[name] ?? null;
            return { ...node, data: data as unknown as Record<string, unknown> };
          });
          setNodes(newNodes);
          setEdges([]);
          onChange?.();
        },
        clear: () => {
          setNodes([]);
          setEdges([]);
          onChange?.();
        },
        getConfig: () => {
          const included: string[] = [];
          const overrides: Record<string, string> = {};
          for (const n of nodes) {
            const d = n.data as unknown as SectionNodeData;
            if (!d.enabled) continue;
            included.push(d.name);
            if (d.persona) overrides[d.name] = d.persona;
          }
          // Stable ordering matches SECTION_ORDER for predictable diffs
          included.sort(
            (a, b) => SECTION_ORDER.indexOf(a) - SECTION_ORDER.indexOf(b),
          );
          return { included_sections: included, persona_overrides: overrides };
        },
        getPresentSections: () => {
          return new Set(
            nodes.map((n) => (n.data as unknown as SectionNodeData).name),
          );
        },
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

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

import { getDefaultTemplate, INPUT_NODE_ID_CONST } from './default-template';
import { FlowCanvasContext, type FlowCanvasContextValue } from './flow-canvas-context';
import { DEFAULT_INPUT_NODE_DATA, InputNode, type InputNodeData } from './input-node';
import { SectionNode, type SectionNodeData } from './section-node';

/** Effective config the orchestrator needs (mirror of AnalyzeFlowCreate
 * minus the cosmetic name/use_personas). */
export interface CanvasConfig {
  included_sections: string[];
  persona_overrides: Record<string, string>;
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
  getPresentSections: () => Set<string>;
  hasInputNode: () => boolean;
}

const nodeTypes = { section: SectionNode, input: InputNode };

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

    const ctxValue: FlowCanvasContextValue = useMemo(
      () => ({ updateNodeData }),
      [updateNodeData],
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
          const included: string[] = [];
          const overrides: Record<string, string> = {};
          for (const n of nodes) {
            if (n.type !== 'section') continue;
            const d = n.data as unknown as SectionNodeData;
            if (!d.enabled) continue;
            // Only canonical SECTION_ORDER names go to the backend;
            // visual-only nodes (manager_check) are silently skipped.
            if (!SECTION_ORDER.includes(d.name)) continue;
            included.push(d.name);
            if (d.persona) overrides[d.name] = d.persona;
          }
          included.sort(
            (a, b) => SECTION_ORDER.indexOf(a) - SECTION_ORDER.indexOf(b),
          );
          return { included_sections: included, persona_overrides: overrides };
        },
        getInputData: () => {
          const input = nodes.find((n) => n.id === INPUT_NODE_ID_CONST);
          if (!input) return null;
          return input.data as unknown as InputNodeData;
        },
        getPresentSections: () => {
          const present = new Set<string>();
          for (const n of nodes) {
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

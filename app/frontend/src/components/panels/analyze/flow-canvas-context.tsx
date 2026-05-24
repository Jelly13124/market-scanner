// Lightweight context so SectionNode instances can update their own
// data without each node owning the React Flow setNodes setter.

import { createContext } from 'react';

import type { SectionNodeData } from './section-node';

export interface FlowCanvasContextValue {
  /** Merge `patch` into the node with this id. */
  updateNodeData: (nodeId: string, patch: Partial<SectionNodeData>) => void;
}

export const FlowCanvasContext = createContext<FlowCanvasContextValue | null>(null);

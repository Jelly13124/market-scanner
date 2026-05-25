// Phase 6F-2: single chat bubble — user / assistant / user_manual_edit.
// Renders Apply / Reject action footer when the assistant proposed a patch.

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { ChatMessage as ChatMessageType } from '@/types/chat';
import { Check, X } from 'lucide-react';

interface Props {
  message: ChatMessageType;
  onApply?: () => void;
  onReject?: () => void;
}

export function ChatMessage({ message, onApply, onReject }: Props) {
  const isUser = message.role === 'user';
  const isManual = message.role === 'user_manual_edit';
  const isPatch = message.role === 'assistant' && message.spec_patch_json != null;
  const isApplied = message.patch_accepted === true;

  return (
    <div className={cn('flex flex-col gap-1 p-3', isUser && 'items-end')}>
      <div className={cn(
        'rounded px-3 py-2 text-sm max-w-[85%]',
        isUser && 'bg-primary/10',
        isManual && 'bg-amber-50 text-amber-900 border border-amber-200',
        !isUser && !isManual && 'bg-muted',
      )}>
        <div className="text-[10px] uppercase text-muted-foreground mb-1">
          {message.role}
        </div>
        <div className="whitespace-pre-wrap">{message.content}</div>
        {isPatch && !isApplied && onApply && onReject && (
          <div className="flex gap-2 mt-2">
            <Button size="sm" onClick={onApply}>
              <Check className="size-3 mr-1" /> Apply patch
            </Button>
            <Button size="sm" variant="ghost" onClick={onReject}>
              <X className="size-3 mr-1" /> Reject
            </Button>
          </div>
        )}
        {isPatch && isApplied && (
          <div className="mt-2 text-[10px] text-green-700">Applied</div>
        )}
      </div>
    </div>
  );
}

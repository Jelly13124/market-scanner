// Phase 6F-2: middle column of the Lab panel — scrollable chat history +
// input + Apply/Reject patch actions.

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { labChatService } from '@/services/lab-chat-service';
import type { ChatMessage } from '@/types/chat';
import { Loader2, Send } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { ChatMessage as ChatMessageComponent } from './chat-message';

interface Props {
  strategyId: number | null;
  onSpecUpdated: () => void;
}

export function ChatPanel({ strategyId, onSpecUpdated }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const { t } = useTranslation();

  const reload = useCallback(async () => {
    if (strategyId == null) { setMessages([]); return; }
    try {
      setMessages(await labChatService.list(strategyId));
    } catch (e) { toast.error((e as Error).message); }
  }, [strategyId]);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight });
  }, [messages]);

  async function handleSend() {
    if (!input.trim() || strategyId == null || sending) return;
    setSending(true);
    const text = input;
    setInput('');
    try {
      const resp = await labChatService.send(strategyId, { message: text });
      await reload();
      if (resp.kind === 'patch') {
        toast.info(t('lab.chat.patchProposed'));
      }
    } catch (e) { toast.error((e as Error).message); }
    finally { setSending(false); }
  }

  async function handleApply(messageId: number) {
    if (strategyId == null) return;
    try {
      await labChatService.applyPatch(strategyId, { message_id: messageId });
      onSpecUpdated();
      await reload();
      toast.success(t('lab.chat.patchApplied'));
    } catch (e) { toast.error((e as Error).message); }
  }

  if (strategyId == null) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-muted-foreground">
        {t('lab.selectPrompt')}
      </div>
    );
  }

  return (
    <div className="h-full min-h-0 min-w-0 flex flex-col">
      <div ref={scrollerRef} className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
        {messages.map((m) => (
          <ChatMessageComponent
            key={m.id} message={m}
            onApply={() => handleApply(m.id)}
            onReject={() => { /* no-op v1; reject just leaves the message */ }}
          />
        ))}
      </div>
      <div className="border-t p-3 flex gap-2">
        <Input
          value={input} onChange={(e) => setInput(e.target.value)}
          placeholder={t('lab.chat.placeholder')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
          }}
          disabled={sending}
        />
        <Button onClick={handleSend} disabled={sending || !input.trim()}>
          {sending ? <Loader2 className="size-3 animate-spin" /> : <Send className="size-3" />}
        </Button>
      </div>
    </div>
  );
}

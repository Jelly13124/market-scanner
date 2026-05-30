// Standalone pop-out viewer for a saved report. Triggered from the sidebar
// Recent Reports list. Renders the self-contained report HTML in an iframe
// inside a large dialog, so reading a past report doesn't clutter the
// Analyze panel.

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { useReportHtml } from '@/hooks/use-report-html';
import { ExternalLink } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface ReportViewerModalProps {
  reportId: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ReportViewerModal({ reportId, open, onOpenChange }: ReportViewerModalProps) {
  const { t } = useTranslation();
  // Fetch the report HTML with auth (via the global fetch interceptor) and
  // render it from a blob URL — an iframe navigation wouldn't carry the token.
  const { url: src, error } = useReportHtml(reportId);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[95vw] w-[95vw] h-[92vh] p-0 flex flex-col gap-0">
        <DialogHeader className="flex flex-row items-center justify-between px-4 py-2 border-b space-y-0">
          <DialogTitle className="text-sm">
            {t('analyze.reports.reportN', { id: reportId })}
          </DialogTitle>
          {src && (
            <Button
              size="sm"
              variant="outline"
              className="h-7 mr-6"
              onClick={() => window.open(src, '_blank', 'noopener')}
            >
              <ExternalLink className="size-3 mr-1" />
              {t('analyze.reports.openInNewTab')}
            </Button>
          )}
        </DialogHeader>
        {error ? (
          <div className="flex-1 grid place-items-center text-xs text-red-600">
            Failed to load report
          </div>
        ) : src ? (
          <iframe
            key={src}
            src={src}
            title={`report-${reportId}`}
            className="flex-1 w-full border-0 bg-white"
          />
        ) : (
          <div className="flex-1 grid place-items-center text-xs text-muted-foreground">
            Loading report…
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

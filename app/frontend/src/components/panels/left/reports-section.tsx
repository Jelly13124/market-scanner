// Left-sidebar section listing recent SOP analyze reports. Clicking a report
// pops it out in a standalone viewer modal; each row can be deleted. The list
// refreshes whenever a run lands or a report is deleted (via analyze-bus).

import { ReportList } from '@/components/panels/analyze/report-list';
import { ReportViewerModal } from '@/components/panels/analyze/report-viewer-modal';
import { analyzeBus } from '@/services/analyze-bus';
import { analyzeService } from '@/services/analyze-service';
import { ChevronDown, ChevronRight, FileText } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

export function ReportsSection() {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(true);
  const [viewingId, setViewingId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const openReport = (id: number) => {
    setViewingId(id);
    setModalOpen(true);
  };

  const deleteReport = async (id: number) => {
    try {
      await analyzeService.deleteReport(id);
      if (viewingId === id) {
        setModalOpen(false);
        setViewingId(null);
      }
      analyzeBus.notifyReportsChanged(); // refresh the list
      toast.success(t('analyze.reports.deleted', { id, defaultValue: 'Report #{{id}} deleted' }));
    } catch (e) {
      toast.error((e as Error).message);
    }
  };

  return (
    <div className="flex flex-col flex-shrink-0 border-b mt-4">
      <button
        className="p-2 flex justify-between items-center hover-bg"
        onClick={() => setExpanded((v) => !v)}
      >
        <span className="text-primary text-sm font-medium ml-4 flex items-center gap-1.5">
          <FileText size={13} />
          {t('analyze.reports.title')}
        </span>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      {expanded && (
        <div className="px-2 pb-2">
          <ReportList
            tickerFilter={undefined}
            currentReportId={viewingId}
            onSelect={openReport}
            onDelete={deleteReport}
          />
        </div>
      )}
      <ReportViewerModal
        reportId={viewingId}
        open={modalOpen}
        onOpenChange={setModalOpen}
      />
    </div>
  );
}

import { useEffect, useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';

// Fetches the report HTML WITH auth (the global fetch interceptor adds the Bearer token),
// returns a blob object URL safe to use as an <iframe src> or window.open() target.
export function useReportHtml(reportId: number | null) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (reportId == null) { setUrl(null); setError(null); return; }
    let revoked = false; let objUrl: string | null = null;
    setUrl(null); setError(null);
    fetch(`${API_BASE}/research/reports/${reportId}/html`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const html = await r.text();
        if (revoked) return;
        objUrl = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
        setUrl(objUrl);
      })
      .catch((e) => { if (!revoked) setError(String(e)); });
    return () => { revoked = true; if (objUrl) URL.revokeObjectURL(objUrl); };
  }, [reportId]);
  return { url, error };
}

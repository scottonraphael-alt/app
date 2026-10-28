import { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { dateLabel } from './projectUtils';

export default function TemplatePreview({ templateId, startDate, endDate }) {
  const [rows, setRows] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!templateId || !startDate) return undefined;
    let live = true;
    setFailed(false);
    api.get(`/project-extras/templates/${templateId}/preview`, { params: { start_date: startDate, ...(endDate ? { end_date: endDate } : {}) } })
      .then(r => { if (live) setRows(r.data.tasks); })
      .catch(() => { if (live) { setRows(null); setFailed(true); } });
    return () => { live = false; };
  }, [templateId, startDate, endDate]);
  if (failed) return <p className="pj-help">Aperçu des échéances indisponible.</p>;
  if (!rows) return null;
  return <div className="pj-template-dates"><strong>Échéances calculées</strong><ul>{rows.map((t, i) => <li key={i}><span>{t.title}</span><time>{dateLabel(t.due_date)}</time></li>)}</ul></div>;
}

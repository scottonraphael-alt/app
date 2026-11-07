import { lazy, Suspense } from 'react';
import CasePreview from './CasePreview';
const TicketWorkspace = lazy(() => import('../../pages/TicketWorkspacePage'));

export default function TicketPreview({ ticket, onClose, helper, onTicketUpdate, onTicketDeleted, isAdmin = false }) {
  return <CasePreview title={ticket.member?.display_name || ticket.member?.username || 'Dossier du membre'}
    href={`/tickets/${ticket.id}`} onClose={onClose}>
    <Suspense fallback={<p role="status">Chargement du dossier…</p>}>
      <TicketWorkspace key={ticket.id} ticketId={ticket.id} embedded helper={helper} isAdmin={isAdmin} onTicketUpdate={onTicketUpdate} onTicketDeleted={id => { onTicketDeleted?.(id); onClose(); }} />
    </Suspense>
  </CasePreview>;
}

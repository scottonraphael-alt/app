import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { Modal } from '../projects/ProjectUI';
import PreviewAvatar from './PreviewAvatar';

export default function CasePreview({ title, member, avatarUrl, source, href, onClose, children }) {
  const heading = source ? <span className="iris-preview-heading">
    <PreviewAvatar person={member} label={title} url={avatarUrl} />
    <span data-preview-title="">{title}</span>
  </span> : title;
  return <Modal title={heading} sharedFrom={source} eyebrow="APERÇU DU DOSSIER" variant="drawer" onClose={onClose}>
    <div className="iris-preview-actions"><Link className="cw-button vf-button" to={href}>
      Ouvrir la page complète <ArrowUpRight size={15} aria-hidden="true" />
    </Link></div>
    {children}
  </Modal>;
}

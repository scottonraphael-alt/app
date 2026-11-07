import { Link } from 'react-router-dom';
import { ArrowUpRight } from 'lucide-react';
import { Modal } from '../projects/ProjectUI';

export default function CasePreview({ title, href, onClose, children }) {
  return <Modal title={title} eyebrow="APERÇU DU DOSSIER" variant="drawer" onClose={onClose}>
    <div className="iris-preview-actions"><Link className="cw-button vf-button" to={href}>
      Ouvrir la page complète <ArrowUpRight size={15} aria-hidden="true" />
    </Link></div>
    {children}
  </Modal>;
}

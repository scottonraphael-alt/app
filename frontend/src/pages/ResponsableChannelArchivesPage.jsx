import { Archive, ArrowRight, ImageDown, LoaderCircle, MessagesSquare, PlusCircle, Radio, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";


const formatTime = (timestamp) => new Date(timestamp).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });


export default function ResponsableChannelArchivesPage() {
  const [archives, setArchives] = useState([]);
  const [loading, setLoading] = useState(true);
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const loadArchives = useCallback(() => {
    setLoading(true);
    api.get("/channel-archives")
      .then((response) => setArchives(response.data))
      .catch((error) => toast.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadArchives();
  }, [loadArchives]);

  const createArchive = async (event) => {
    event.preventDefault();
    if (!channelId.trim()) return;
    setCreating(true);
    try {
      const response = await api.post("/channel-archives", {
        channel_id: channelId.trim(),
        title: title.trim() || undefined,
      });
      setArchives((current) => [response.data, ...current]);
      setChannelId("");
      setTitle("");
      toast.success("Salon archivé avec succès.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreating(false);
    }
  };

  const deleteArchive = async (archiveId) => {
    if (!window.confirm("Supprimer définitivement cette archive de salon et ses fichiers ? Cette action est irréversible.")) return;
    try {
      await api.delete(`/channel-archives/${archiveId}`);
      setArchives((current) => current.filter((archive) => archive.id !== archiveId));
      toast.success("Archive supprimée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const totalMessages = archives.reduce((sum, archive) => sum + archive.message_count, 0);
  const totalFiles = archives.reduce((sum, archive) => sum + archive.local_attachment_count, 0);
  const latest = archives[0];

  return (
    <section className="page-content dashboard-page" data-testid="responsable-channel-archives-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">RESPONSABLE · ARCHIVAGE</p>
          <h1>Sauvegarder un salon Discord entier.</h1>
        </div>
      </header>

      <div className="metrics-grid" data-testid="channel-archive-statistics">
        <div className="metric-block">
          <Archive size={18} />
          <span>Salons archivés</span>
          <strong>{archives.length}</strong>
        </div>
        <div className="metric-block">
          <MessagesSquare size={18} />
          <span>Messages sauvegardés</span>
          <strong>{totalMessages}</strong>
        </div>
        <div className="metric-block">
          <ImageDown size={18} />
          <span>Fichiers copiés</span>
          <strong>{totalFiles}</strong>
        </div>
      </div>

      <section className="care-hero" data-testid="latest-channel-archive-hero">
        <div>
          <p className="eyebrow">DERNIÈRE ARCHIVE</p>
          <h2>{latest ? latest.title : "Aucun salon archivé pour le moment."}</h2>
          <p>
            {latest
              ? `#${latest.channel_name} · ${latest.message_count} messages · dernière synchro le ${formatTime(latest.last_synced_at)}`
              : "Archivez un premier salon avec le formulaire ci-contre."}
          </p>
        </div>
        {latest ? (
          <Link to={`/responsable/archives-salons/${latest.id}`} className="care-open" data-testid="open-latest-channel-archive">
            <span>Ouvrir l’archive</span>
            <ArrowRight size={20} />
          </Link>
        ) : (
          <Radio size={32} />
        )}
      </section>

      <div className="dashboard-grid">
        <section className="activity-pane" data-testid="channel-archives-list-panel">
          <div className="section-heading">
            <span>SALONS ARCHIVÉS</span>
            <span className="live-dot">CONFIDENTIEL</span>
          </div>

          {loading ? (
            <p className="dashboard-loading">Chargement…</p>
          ) : archives.length === 0 ? (
            <div className="dashboard-empty" data-testid="channel-archives-empty">
              <Radio size={28} />
              <p>Aucun salon archivé pour le moment.</p>
            </div>
          ) : (
            <div className="ticket-table">
              {archives.map((archive) => (
                <div className="meeting-row-stacked" key={archive.id} data-testid={`channel-archive-row-${archive.id}`}>
                  <div className="meeting-row-top">
                    <div className="meeting-row-heading">
                      <strong>{archive.title}</strong>
                      <span className="meeting-row-date-inline">#{archive.channel_name} · {archive.channel_id}</span>
                    </div>
                    <span className="status-dot active">
                      {archive.local_attachment_count} FICHIER{archive.local_attachment_count > 1 ? "S" : ""}
                    </span>
                  </div>

                  <p className="meeting-agenda-full">{archive.message_count} messages · dernière synchro le {formatTime(archive.last_synced_at)}</p>

                  <div className="meeting-row-buttons">
                    <Link to={`/responsable/archives-salons/${archive.id}`} className="btn-consult" data-testid={`open-channel-archive-${archive.id}`}>
                      Consulter <ArrowRight size={14} />
                    </Link>
                    <button
                      type="button"
                      className="icon-btn-danger"
                      onClick={() => deleteArchive(archive.id)}
                      aria-label="Supprimer l’archive"
                      data-testid={`delete-channel-archive-row-${archive.id}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <aside className="system-pane" data-testid="new-channel-archive-panel">
          <p className="eyebrow">ARCHIVER UN SALON</p>
          <form className="new-note-form" onSubmit={createArchive} data-testid="new-channel-archive-form">
            <label htmlFor="archive-channel-id">ID du salon Discord</label>
            <input id="archive-channel-id" value={channelId} onChange={(event) => setChannelId(event.target.value)} placeholder="123456789012345678" required data-testid="archive-channel-id-input" />
            <label htmlFor="archive-title">Titre (optionnel)</label>
            <input id="archive-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Nom donné à l’archive" maxLength={160} data-testid="archive-title-input" />
            <button type="submit" disabled={creating} data-testid="create-channel-archive-button">
              {creating ? <LoaderCircle className="spin" size={15} /> : <PlusCircle size={15} />} {creating ? "Import en cours…" : "Archiver ce salon"}
            </button>
          </form>
          <p className="admin-empty">Iris importe tout l’historique et copie localement chaque pièce jointe (images, documents, vidéos…).</p>
        </aside>
      </div>
    </section>
  );
}

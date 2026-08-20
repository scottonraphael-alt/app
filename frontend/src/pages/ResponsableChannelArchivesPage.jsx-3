import { Archive, ChevronLeft, ImageDown, LoaderCircle, MessagesSquare, PlusCircle, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";


const formatTime = (timestamp) => new Date(timestamp).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });


export default function ResponsableChannelArchivesPage() {
  const [archives, setArchives] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const loadArchives = useCallback(() => {
    setLoading(true);
    setError("");
    api.get("/channel-archives")
      .then((response) => setArchives(response.data))
      .catch((requestError) => setError(getErrorMessage(requestError)))
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
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setCreating(false);
    }
  };

  return (
    <section className="page-content new-ticket-page" data-testid="responsable-channel-archives-page">
      <Link className="back-link" to="/responsable/auth-logs" data-testid="channel-archives-back-link"><ChevronLeft size={16} /> Retour</Link>
      <div className="new-ticket-layout">
        <div className="new-ticket-intro">
          <p className="eyebrow">RESPONSABLE · ARCHIVAGE</p>
          <h1>Sauvegarder un salon Discord entier.</h1>
          <p>Saisissez l’ID du salon : Iris importera tout l’historique des messages et fera une copie locale de chaque fichier joint (images, documents, vidéos…), indépendamment de tout dossier d’aide.</p>
          <div className="process-list">
            <div><MessagesSquare size={18} /><span><b>01 · Historique</b>Import paginé de tous les messages du salon</span></div>
            <div><ImageDown size={18} /><span><b>02 · Fichiers</b>Copie locale de chaque pièce jointe pour ne rien perdre</span></div>
            <div><Archive size={18} /><span><b>03 · Archive privée</b>Consultable à tout moment dans Iris</span></div>
          </div>
        </div>
        <form className="new-note-form" onSubmit={createArchive} data-testid="new-channel-archive-form">
          <label htmlFor="archive-channel-id">ID du salon Discord</label>
          <input id="archive-channel-id" value={channelId} onChange={(event) => setChannelId(event.target.value)} placeholder="123456789012345678" required data-testid="archive-channel-id-input" />
          <label htmlFor="archive-title">Titre (optionnel)</label>
          <input id="archive-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Nom donné à l’archive" maxLength={160} data-testid="archive-title-input" />
          <button type="submit" disabled={creating} data-testid="create-channel-archive-button">
            {creating ? <LoaderCircle className="spin" size={15} /> : <PlusCircle size={15} />} {creating ? "Import en cours…" : "Archiver ce salon"}
          </button>
        </form>
      </div>

      <section className="channel-archives-section" data-testid="channel-archives-list">
        <div className="column-header">
          <span><Archive size={16} /> ARCHIVES DE SALONS</span>
          <button className="secondary-button" type="button" onClick={loadArchives} data-testid="refresh-channel-archives-button"><RefreshCw size={16} /> Actualiser</button>
        </div>
        {loading && <div className="loading-page" data-testid="channel-archives-loading"><LoaderCircle className="spin" size={22} /> Chargement des archives…</div>}
        {error && <p className="admin-error" data-testid="channel-archives-error">{error}</p>}
        {!loading && !error && archives.length === 0 && <p className="admin-empty" data-testid="channel-archives-empty">Aucun salon archivé pour le moment.</p>}
        {!loading && archives.length > 0 && (
          <div className="admin-helper-grid" data-testid="channel-archives-grid">
            {archives.map((archive) => (
              <article className="admin-helper-card" key={archive.id} data-testid={`channel-archive-card-${archive.id}`}>
                <header>
                  <span><h2>{archive.title}</h2><p data-testid={`channel-archive-channel-${archive.id}`}>#{archive.channel_name} · {archive.channel_id}</p></span>
                </header>
                <div className="admin-helper-counts">
                  <span>{archive.message_count} message{archive.message_count > 1 ? "s" : ""}</span>
                  <b>{archive.local_attachment_count} fichier{archive.local_attachment_count > 1 ? "s" : ""} copié{archive.local_attachment_count > 1 ? "s" : ""}</b>
                </div>
                <p className="admin-empty">Dernière synchro · {formatTime(archive.last_synced_at)}</p>
                <Link className="calm-primary-button" to={`/responsable/archives-salons/${archive.id}`} data-testid={`open-channel-archive-${archive.id}`}>Ouvrir l’archive</Link>
              </article>
            ))}
          </div>
        )}
      </section>
    </section>
  );
}

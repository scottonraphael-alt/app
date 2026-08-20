import { FileDown, ImageOff, LoaderCircle, MessagesSquare, RefreshCw, Trash2 } from "lucide-react";
import { ChevronLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";


const formatTime = (timestamp) => new Date(timestamp).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });

// Les routes de l'API sont appelées en relatif (ex: "/tickets") ailleurs dans l'app,
// donc api.defaults.baseURL contient déjà le préfixe "/api" ; on s'en sert pour
// construire l'URL absolue de l'image mirrorée localement.
const attachmentSrc = (attachment) =>
  attachment.local_url ? `${api.defaults?.baseURL || "/api"}${attachment.local_url}` : attachment.url;


export default function ChannelArchiveWorkspacePage() {
  const { archiveId } = useParams();
  const navigate = useNavigate();
  const [archive, setArchive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError("");
      try {
        const response = await api.get(`/channel-archives/${archiveId}`);
        setArchive(response.data);
      } catch (requestError) {
        setError(getErrorMessage(requestError));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [archiveId]);

  const sync = async () => {
    setSyncing(true);
    try {
      const response = await api.post(`/channel-archives/${archiveId}/sync`);
      setArchive(response.data);
      toast.success("Salon resynchronisé.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setSyncing(false);
    }
  };

  const deleteArchive = async () => {
    if (!window.confirm("Supprimer définitivement cette archive de salon et ses images ? Cette action est irréversible.")) return;
    try {
      await api.delete(`/channel-archives/${archiveId}`);
      toast.success("Archive supprimée.");
      navigate("/responsable/archives-salons");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    }
  };

  if (loading) return <div className="loading-page" data-testid="channel-archive-loading"><LoaderCircle className="spin" size={26} /> Chargement de l’archive…</div>;
  if (error || !archive) return <div className="loading-page error-page" data-testid="channel-archive-load-error">{error || "Archive introuvable."}</div>;

  return (
    <section className="workspace-page" data-testid="channel-archive-workspace-page">
      <header className="workspace-header">
        <div className="workspace-title">
          <Link to="/responsable/archives-salons" className="back-link" data-testid="channel-archive-back-link"><ChevronLeft size={16} /> Archives de salons</Link>
          <div className="member-title" data-testid="channel-archive-header">
            <span><p>{archive.id} · SALON ARCHIVÉ</p><h1>#{archive.channel_name}</h1></span>
          </div>
        </div>
        <div className="workspace-actions">
          <button className="secondary-button" disabled={syncing} onClick={sync} type="button" data-testid="sync-channel-archive-button">
            {syncing ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} Synchroniser
          </button>
          <button className="danger-button" onClick={deleteArchive} type="button" data-testid="delete-channel-archive-button"><Trash2 size={16} /> Supprimer</button>
        </div>
      </header>

      <div className="ticket-meta" data-testid="channel-archive-metadata">
        <span>SALON · {archive.channel_id}</span>
        <span>{archive.message_count} MESSAGES</span>
        <span>{archive.local_attachment_count} FICHIER{archive.local_attachment_count > 1 ? "S" : ""} COPIÉ{archive.local_attachment_count > 1 ? "S" : ""} LOCALEMENT</span>
        <span>DERNIÈRE SYNCHRO · {formatTime(archive.last_synced_at)}</span>
      </div>

      <div className="workspace-grid">
        <section className="workspace-column transcript-column" data-testid="channel-archive-transcript-panel">
          <div className="column-header"><span><MessagesSquare size={16} /> HISTORIQUE COMPLET</span><b>{archive.message_count}</b></div>
          <div className="transcript-scroll">
            {archive.transcript.length === 0 && <p className="empty-transcript" data-testid="channel-archive-empty-transcript">Aucun message dans ce salon.</p>}
            {archive.transcript.map((message) => (
              <article className="transcript-message member-message" key={message.id} data-testid={`channel-archive-message-${message.id}`}>
                <img src={message.author.avatar_url} alt="" />
                <div>
                  <div className="message-line"><strong>{message.author.display_name || message.author.username}</strong><time>{formatTime(message.timestamp)}</time></div>
                  {message.content && <p>{message.content}</p>}
                  {message.attachments.map((attachment) => {
                    const isImage = attachment.content_type?.startsWith("image/")
                      || /\.(png|jpe?g|gif|webp)$/i.test(attachment.filename);
                    const href = attachment.local_url ? attachmentSrc(attachment) : attachment.url;

                    if (isImage) {
                      return (
                        <a
                          href={href}
                          key={attachment.id}
                          target="_blank"
                          rel="noreferrer"
                          data-testid={`channel-archive-attachment-${attachment.id}`}
                        >
                          <img
                            src={href}
                            alt={attachment.filename}
                            loading="lazy"
                            className="transcript-attachment-image"
                            style={{ maxWidth: "420px", width: "100%", maxHeight: "420px", objectFit: "cover", borderRadius: "12px", display: "block", marginTop: "8px" }}
                          />
                          {!attachment.local_url && (
                            <span className="admin-empty" data-testid={`channel-archive-attachment-missing-${attachment.id}`}>
                              <ImageOff size={12} /> copie locale indisponible, lien Discord d’origine
                            </span>
                          )}
                        </a>
                      );
                    }

                    return (
                      <a href={href} key={attachment.id} target="_blank" rel="noreferrer" data-testid={`channel-archive-attachment-${attachment.id}`}>
                        <FileDown size={13} /> {attachment.filename}
                        {!attachment.local_url && (
                          <span className="admin-empty" data-testid={`channel-archive-attachment-missing-${attachment.id}`}>
                            (copie locale indisponible, lien Discord d’origine)
                          </span>
                        )}
                      </a>
                    );
                  })}
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

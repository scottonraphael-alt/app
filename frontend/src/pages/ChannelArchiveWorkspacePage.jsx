import { FileDown, Filter, ImageOff, LoaderCircle, MessagesSquare, RefreshCw, Search, Trash2, User, X } from "lucide-react";
import { ChevronLeft } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";


const formatTime = (timestamp) => new Date(timestamp).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });

// Les routes de l'API sont appelées en relatif (ex: "/tickets") ailleurs dans l'app,
// donc api.defaults.baseURL contient déjà le préfixe "/api" ; on s'en sert pour
// construire l'URL absolue de l'image mirrorée localement.
const attachmentSrc = (attachment) =>
  attachment.local_url ? `${api.defaults?.baseURL || "/api"}${attachment.local_url}` : attachment.url;

const FILE_TYPE_OPTIONS = [
  { value: "all", label: "Tous types de fichier" },
  { value: "image", label: "Images" },
  { value: "video", label: "Vidéos" },
  { value: "audio", label: "Audio" },
  { value: "document", label: "Documents" },
  { value: "archive", label: "Archives (zip…)" },
  { value: "other", label: "Autres" },
];

const EXTENSION_CATEGORIES = {
  image: ["png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"],
  video: ["mp4", "mov", "webm", "avi", "mkv"],
  audio: ["mp3", "wav", "ogg", "m4a", "flac"],
  document: ["pdf", "doc", "docx", "txt", "xls", "xlsx", "ppt", "pptx", "csv"],
  archive: ["zip", "rar", "7z", "tar", "gz"],
};

const categorizeFilename = (filename) => {
  const extension = filename.includes(".") ? filename.split(".").pop().toLowerCase() : "";
  for (const [category, extensions] of Object.entries(EXTENSION_CATEGORIES)) {
    if (extensions.includes(extension)) return category;
  }
  return "other";
};


export default function ChannelArchiveWorkspacePage() {
  const { archiveId } = useParams();
  const navigate = useNavigate();
  const [archive, setArchive] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState("");

  const [searchText, setSearchText] = useState("");
  const [searchAuthor, setSearchAuthor] = useState("");
  const [searchFileType, setSearchFileType] = useState("all");
  const [highlightedMessageId, setHighlightedMessageId] = useState(null);
  const highlightTimeoutRef = useRef(null);

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

  useEffect(() => () => {
    if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
  }, []);

  // Tant que l'archive est en cours d'import (création initiale ou resynchronisation), on
  // réinterroge régulièrement pour suivre la progression sans que l'utilisateur ait à
  // recharger la page.
  useEffect(() => {
    if (!archive || archive.status !== "importing") return undefined;
    const interval = setInterval(async () => {
      try {
        const response = await api.get(`/channel-archives/${archiveId}`);
        setArchive(response.data);
      } catch {
        // erreur transitoire de polling, on retentera au prochain tick
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [archive?.status, archiveId]);

  const normalizedText = searchText.trim().toLowerCase();
  const normalizedAuthor = searchAuthor.trim().toLowerCase();
  const hasActiveSearch = Boolean(normalizedText || normalizedAuthor || searchFileType !== "all");

  const searchResults = useMemo(() => {
    if (!archive || !hasActiveSearch) return [];
    return archive.transcript.filter((message) => {
      if (normalizedText && !message.content.toLowerCase().includes(normalizedText)) return false;

      if (normalizedAuthor) {
        const authorName = `${message.author.display_name || ""} ${message.author.username || ""}`.toLowerCase();
        if (!authorName.includes(normalizedAuthor)) return false;
      }

      if (searchFileType !== "all") {
        const hasMatchingFile = message.attachments.some(
          (attachment) => categorizeFilename(attachment.filename) === searchFileType
        );
        if (!hasMatchingFile) return false;
      }

      return true;
    });
  }, [archive, hasActiveSearch, normalizedText, normalizedAuthor, searchFileType]);

  const clearSearch = () => {
    setSearchText("");
    setSearchAuthor("");
    setSearchFileType("all");
  };

  const jumpToMessage = (messageId) => {
    const target = document.getElementById(`transcript-message-${messageId}`);
    target?.scrollIntoView({ behavior: "smooth", block: "center" });

    setHighlightedMessageId(messageId);
    if (highlightTimeoutRef.current) clearTimeout(highlightTimeoutRef.current);
    highlightTimeoutRef.current = setTimeout(() => setHighlightedMessageId(null), 2500);
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const response = await api.post(`/channel-archives/${archiveId}/sync`);
      setArchive(response.data);
      toast.success("Resynchronisation lancée en arrière-plan.");
    } catch (requestError) {
      toast.error(getErrorMessage(requestError));
    } finally {
      setSyncing(false);
    }
  };

  const deleteArchive = async () => {
    if (!window.confirm("Supprimer définitivement cette archive de salon et ses fichiers ? Cette action est irréversible.")) return;
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
          <button className="secondary-button" disabled={syncing || archive.status === "importing"} onClick={sync} type="button" data-testid="sync-channel-archive-button">
            {syncing || archive.status === "importing" ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />} Synchroniser
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

          {archive.status === "importing" && (
            <div
              data-testid="channel-archive-import-banner"
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "6px",
                padding: "10px 14px",
                margin: "0 0 14px",
                border: "1px solid rgba(47,111,79,0.25)",
                borderRadius: "12px",
                background: "rgba(47,111,79,0.06)",
              }}
            >
              {archive.phase === "mirroring_files" ? (
                <>
                  <span style={{ fontSize: "13px" }}>
                    Copie des fichiers en cours… {archive.local_attachment_count}/{archive.files_total ?? "?"}
                  </span>
                  <div style={{ height: "6px", borderRadius: "4px", background: "rgba(0,0,0,0.08)", overflow: "hidden" }}>
                    <div
                      style={{
                        height: "100%",
                        width: `${archive.files_total ? Math.min(100, Math.round((archive.local_attachment_count / archive.files_total) * 100)) : 100}%`,
                        background: "#2f6f4f",
                        transition: "width 0.4s ease",
                      }}
                    />
                  </div>
                </>
              ) : (
                <span style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px" }}>
                  <LoaderCircle className="spin" size={14} /> Récupération des messages… {archive.message_count} importés pour l’instant.
                </span>
              )}
            </div>
          )}

          {archive.status === "failed" && (
            <div
              data-testid="channel-archive-import-error-banner"
              style={{ padding: "10px 14px", margin: "0 0 14px", border: "1px solid rgba(185,28,28,0.3)", borderRadius: "12px", background: "rgba(185,28,28,0.06)", color: "#b91c1c", fontSize: "13px" }}
            >
              Le dernier import a échoué{archive.error_message ? ` : ${archive.error_message}` : "."} Cliquez sur « Synchroniser » pour réessayer.
            </div>
          )}

          <div
            data-testid="channel-archive-search-panel"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "10px",
              padding: "12px 14px",
              margin: "0 0 14px",
              border: "1px solid rgba(0,0,0,0.08)",
              borderRadius: "12px",
              background: "rgba(0,0,0,0.02)",
            }}
          >
            <div style={{ display: "flex", flexWrap: "wrap", gap: "10px", alignItems: "center" }}>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                <Search size={14} />
                <input
                  type="text"
                  value={searchText}
                  onChange={(event) => setSearchText(event.target.value)}
                  placeholder="Contient…"
                  data-testid="search-text-input"
                  style={{ padding: "6px 10px", borderRadius: "8px", border: "1px solid rgba(0,0,0,0.15)", fontSize: "13px" }}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                <User size={14} />
                <input
                  type="text"
                  value={searchAuthor}
                  onChange={(event) => setSearchAuthor(event.target.value)}
                  placeholder="Pseudo…"
                  data-testid="search-author-input"
                  style={{ padding: "6px 10px", borderRadius: "8px", border: "1px solid rgba(0,0,0,0.15)", fontSize: "13px" }}
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px" }}>
                <Filter size={14} />
                <select
                  value={searchFileType}
                  onChange={(event) => setSearchFileType(event.target.value)}
                  data-testid="search-filetype-select"
                  style={{ padding: "6px 10px", borderRadius: "8px", border: "1px solid rgba(0,0,0,0.15)", fontSize: "13px" }}
                >
                  {FILE_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
              {hasActiveSearch && (
                <button
                  type="button"
                  onClick={clearSearch}
                  data-testid="clear-search-button"
                  style={{ display: "inline-flex", alignItems: "center", gap: "4px", padding: "6px 10px", borderRadius: "8px", border: "1px solid rgba(0,0,0,0.15)", background: "transparent", cursor: "pointer", fontSize: "13px" }}
                >
                  <X size={14} /> Effacer
                </button>
              )}
            </div>

            {hasActiveSearch && (
              <div data-testid="channel-archive-search-results">
                <p className="admin-empty">
                  {searchResults.length} message{searchResults.length > 1 ? "s" : ""} trouvé{searchResults.length > 1 ? "s" : ""}
                </p>
                {searchResults.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: "8px", maxHeight: "260px", overflowY: "auto" }}>
                    {searchResults.map((message) => (
                      <button
                        type="button"
                        key={message.id}
                        onClick={() => jumpToMessage(message.id)}
                        data-testid={`search-result-${message.id}`}
                        style={{ display: "flex", flexDirection: "column", gap: "2px", textAlign: "left", padding: "8px 10px", borderRadius: "10px", border: "1px solid rgba(0,0,0,0.08)", background: "white", cursor: "pointer" }}
                      >
                        <span style={{ display: "flex", justifyContent: "space-between", gap: "10px", fontSize: "12px", opacity: 0.7 }}>
                          <strong>{message.author.display_name || message.author.username}</strong>
                          <span>{formatTime(message.timestamp)}</span>
                        </span>
                        <span style={{ fontSize: "13px" }}>
                          {message.content
                            ? message.content.slice(0, 140)
                            : (message.attachments[0]?.filename || "(message sans texte)")}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="transcript-scroll">
            {archive.transcript.length === 0 && <p className="empty-transcript" data-testid="channel-archive-empty-transcript">Aucun message dans ce salon.</p>}
            {archive.transcript.map((message) => (
              <article
                className="transcript-message member-message"
                key={message.id}
                id={`transcript-message-${message.id}`}
                data-testid={`channel-archive-message-${message.id}`}
                style={{
                  backgroundColor: message.id === highlightedMessageId ? "#fef3c7" : "transparent",
                  borderRadius: "10px",
                  transition: "background-color 1.2s ease",
                }}
              >
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
                          style={{ display: "block" }}
                        >
                          <img
                            src={href}
                            alt={attachment.filename}
                            loading="lazy"
                            className="transcript-attachment-image"
                            style={{ width: "100%", maxWidth: "100%", height: "auto", borderRadius: "12px", display: "block", marginTop: "8px" }}
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

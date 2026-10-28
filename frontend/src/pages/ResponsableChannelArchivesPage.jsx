import {
  Archive,
  ArrowRight,
  LoaderCircle,
  MessagesSquare,
  Radio,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";

import "../Casier.css";
import "../ResponsableChannelArchives.css";

const formatTime = (timestamp) =>
  new Date(timestamp).toLocaleString("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
  });

const POLL_INTERVAL_MS = 2000;

function ImportProgress({ archive, onRetry }) {
  if (archive.status === "failed") {
    return (
      <div className="rca-progress rca-progress--failed">
        <p>Import interrompu.</p>

        <button
          type="button"
          className="cz-button cz-button--compact"
          onClick={() => onRetry(archive.id)}
        >
          <RotateCcw size={14} aria-hidden="true" />
          Réessayer
        </button>
      </div>
    );
  }

  if (archive.status !== "importing") return null;

  if (archive.phase === "mirroring_files") {
    const percent = archive.files_total
      ? Math.min(
          100,
          Math.round(
            (archive.local_attachment_count / archive.files_total) * 100
          )
        )
      : 100;

    return (
      <div className="rca-progress">
        <div className="rca-progress-copy">
          <span>Copie des fichiers</span>
          <b>{percent}%</b>
        </div>

        <div className="rca-progress-track">
          <span style={{ width: `${percent}%` }} />
        </div>
      </div>
    );
  }

  return (
    <div className="rca-progress">
      <div className="rca-progress-copy">
        <span>Récupération des messages</span>
        <b>{archive.message_count}</b>
      </div>

      <div className="rca-progress-track">
        <span className="is-indeterminate" />
      </div>
    </div>
  );
}

export default function ResponsableChannelArchivesPage() {
  const [archives, setArchives] = useState([]);
  const [loading, setLoading] = useState(true);
  const [channelId, setChannelId] = useState("");
  const [title, setTitle] = useState("");
  const [creating, setCreating] = useState(false);

  const archivesRef = useRef(archives);

  useEffect(() => {
    document.body.classList.add("casier-no-nav");

    return () => {
      document.body.classList.remove("casier-no-nav");
    };
  }, []);

  const loadArchives = useCallback(() => {
    setLoading(true);

    api
      .get("/channel-archives")
      .then((response) => setArchives(response.data))
      .catch((error) => toast.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadArchives();
  }, [loadArchives]);

  useEffect(() => {
    archivesRef.current = archives;
  }, [archives]);

  useEffect(() => {
    const interval = setInterval(() => {
      const hasActiveImport = archivesRef.current.some(
        (archive) => archive.status === "importing"
      );

      if (!hasActiveImport) return;

      api
        .get("/channel-archives")
        .then((response) => setArchives(response.data))
        .catch(() => undefined);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, []);

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

      toast.success(
        "Import lancé — la progression s’affiche dans la liste."
      );
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setCreating(false);
    }
  };

  const retryArchive = async (archiveId) => {
    try {
      const response = await api.post(
        `/channel-archives/${archiveId}/sync`
      );

      setArchives((current) =>
        current.map((archive) =>
          archive.id === archiveId ? response.data : archive
        )
      );

      toast.success("Nouvel essai lancé.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const deleteArchive = async (archiveId) => {
    if (
      !window.confirm(
        "Supprimer définitivement cette archive de salon et ses fichiers ? Cette action est irréversible."
      )
    ) {
      return;
    }

    try {
      await api.delete(`/channel-archives/${archiveId}`);

      setArchives((current) =>
        current.filter((archive) => archive.id !== archiveId)
      );

      toast.success("Archive supprimée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const totalMessages = archives.reduce(
    (sum, archive) => sum + archive.message_count,
    0
  );

  const totalFiles = archives.reduce(
    (sum, archive) => sum + archive.local_attachment_count,
    0
  );

  const importingCount = archives.filter(
    (archive) => archive.status === "importing"
  ).length;

  return (
    <section
      className="cz-page rca-page"
      data-testid="responsable-channel-archives-page"
    >
      <header className="cz-header">
        <div className="cz-header-copy">
          <p className="cz-eyebrow">ESPACE RESPONSABLE</p>

          <h1>Sauvegardes de salons</h1>

          <p className="cz-intro">
            Importez un salon Discord, suivez la progression et
            consultez les archives disponibles.
          </p>
        </div>

        <div className="cz-header-actions">
          <Link to="/" className="cz-home">
            Accueil
            <ArrowRight size={18} aria-hidden="true" />
          </Link>
        </div>
      </header>

      <section className="cz-panel rca-create-panel">
        <header className="cz-panel-header">
          <span className="cz-panel-icon" aria-hidden="true">
            <Radio size={23} />
          </span>

          <div className="cz-panel-heading">
            <h2>Importer un salon Discord</h2>
            <p>
              La progression de l’import apparaît automatiquement
              dans la liste.
            </p>
          </div>
        </header>

        <div className="cz-panel-toolbar">
          <form className="rca-create" onSubmit={createArchive}>
            <input
              value={channelId}
              onChange={(event) => setChannelId(event.target.value)}
              placeholder="ID du salon Discord"
              required
            />

            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Titre facultatif"
            />

            <button
              type="submit"
              className="cz-button cz-button--primary"
              disabled={creating || !channelId.trim()}
            >
              {creating ? (
                <LoaderCircle className="spin" size={16} aria-hidden="true" />
              ) : (
                <Radio size={16} aria-hidden="true" />
              )}
              {creating ? "Import en cours…" : "Lancer l’import"}
            </button>
          </form>
        </div>
      </section>

      <div className="rca-metrics">
        <div className="rca-metric">
          <span>Archives</span>
          <strong>{archives.length}</strong>
        </div>

        <div className="rca-metric">
          <span>Messages</span>
          <strong>{totalMessages}</strong>
        </div>

        <div className="rca-metric">
          <span>Fichiers</span>
          <strong>{totalFiles}</strong>
        </div>

        <div className="rca-metric rca-metric--amber">
          <span>Imports en cours</span>
          <strong>{importingCount}</strong>
        </div>
      </div>

      <section className="cz-panel">
        <header className="cz-panel-header">
          <span className="cz-panel-icon" aria-hidden="true">
            <Archive size={23} />
          </span>

          <div className="cz-panel-heading">
            <h2>Archives disponibles</h2>
            <p>Consultez une sauvegarde ou suivez son import.</p>
          </div>

          <span className="cz-count-live">
            <span className="cz-count">
              {archives.length} archive{archives.length > 1 ? "s" : ""}
            </span>
          </span>
        </header>

        <div className="cz-panel-scroll">
          {loading ? (
            <div className="rca-state" role="status">
              <LoaderCircle className="spin" size={26} aria-hidden="true" />
              <p>Chargement des sauvegardes…</p>
            </div>
          ) : archives.length === 0 ? (
            <div className="rca-state">
              <Archive size={32} aria-hidden="true" />
              <h2>Aucune sauvegarde pour le moment.</h2>
              <p>
                Importez un salon Discord pour créer la première archive.
              </p>
            </div>
          ) : (
            <div className="rca-list">
              {archives.map((archive) => (
                <article
                  key={archive.id}
                  className="rca-card"
                  data-testid={`channel-archive-${archive.id}`}
                >
                  <span className="rca-card-icon">
                    <MessagesSquare size={22} aria-hidden="true" />
                  </span>

                  <div className="rca-card-copy">
                    <h2>
                      {archive.title || `Salon ${archive.channel_id}`}
                    </h2>

                    <p>
                      {archive.message_count} message
                      {archive.message_count > 1 ? "s" : ""} ·{" "}
                      {archive.local_attachment_count} fichier
                      {archive.local_attachment_count > 1 ? "s" : ""}
                    </p>

                    <small>
                      Créée le {formatTime(archive.created_at)}
                    </small>

                    <ImportProgress
                      archive={archive}
                      onRetry={retryArchive}
                    />
                  </div>

                  <div className="rca-card-actions">
                    <Link
                      to={`/responsable/archives-salons/${archive.id}`}
                      className="cz-button cz-button--primary"
                    >
                      Consulter
                      <ArrowRight size={15} aria-hidden="true" />
                    </Link>

                    <button
                      type="button"
                      className="rca-danger"
                      onClick={() => deleteArchive(archive.id)}
                      aria-label={`Supprimer ${
                        archive.title || archive.channel_id
                      }`}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </section>
  );
}

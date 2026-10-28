import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Download,
  Eye,
  FileArchive,
  FileImage,
  FileText,
  FileUp,
  FolderOpen,
  LoaderCircle,
  Search,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";
import "../ResourcesLibrary.css";

const MAX_SIZE = 250 * 1024 * 1024;

function normalize(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function formatSize(size) {
  const value = Number(size || 0);

  if (!value) return "—";
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} Ko`;

  return `${(value / (1024 * 1024)).toFixed(value > 10 * 1024 * 1024 ? 1 : 2)} Mo`;
}

function formatDate(date) {
  if (!date) return "Non renseignée";

  const parsed = new Date(date);

  if (Number.isNaN(parsed.getTime())) return "Non renseignée";

  return parsed.toLocaleDateString("fr-FR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function ResourceIcon({ type, size = 28 }) {
  const value = String(type || "");

  if (value.includes("image")) return <FileImage size={size} aria-hidden="true" />;
  if (value.includes("pdf")) return <FileArchive size={size} aria-hidden="true" />;

  return <FileText size={size} aria-hidden="true" />;
}

function typeLabel(resource) {
  const type = String(resource.content_type || "");

  if (type.includes("pdf")) return "PDF";
  if (type.includes("image")) return "Image";

  const extension = String(resource.original_filename || "")
    .split(".")
    .pop();

  return extension && extension.length <= 5 ? extension.toUpperCase() : "Fichier";
}

export default function ResourcesPage({ isAdmin = false }) {
  const [resources, setResources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");

  const [file, setFile] = useState(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("Général");
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const inputRef = useRef(null);

  const loadResources = () => {
    setLoading(true);

    api
      .get("/resources")
      .then((response) => setResources(response.data.resources || []))
      .catch((error) => toast.error(getErrorMessage(error)))
      .finally(() => setLoading(false));
  };

  useEffect(loadResources, []);

  useEffect(() => {
    document.body.classList.add("resources-library-no-nav");

    return () => {
      document.body.classList.remove("resources-library-no-nav");
    };
  }, []);

  const categories = useMemo(
    () =>
      [...new Set(resources.map((item) => item.category).filter(Boolean))].sort(
        (a, b) => a.localeCompare(b, "fr")
      ),
    [resources]
  );

  const visibleResources = useMemo(() => {
    const term = normalize(search.trim());

    return resources.filter((resource) => {
      if (categoryFilter !== "all" && resource.category !== categoryFilter) {
        return false;
      }

      if (!term) return true;

      return normalize(
        [
          resource.title,
          resource.description,
          resource.category,
          resource.original_filename,
        ].join(" ")
      ).includes(term);
    });
  }, [resources, search, categoryFilter]);

  const hasFilters = Boolean(search.trim() || categoryFilter !== "all");

  const clearFilters = () => {
    setSearch("");
    setCategoryFilter("all");
  };

  const chooseFile = (selected) => {
    if (!selected) return;

    if (selected.size > MAX_SIZE) {
      toast.error("La taille maximale est de 250 Mo.");
      return;
    }

    setFile(selected);

    if (!title) {
      setTitle(selected.name.replace(/\.[^.]+$/, ""));
    }
  };

  const upload = async (event) => {
    event.preventDefault();

    if (!file || !title.trim()) return;

    const formData = new FormData();
    formData.append("file", file);
    formData.append("title", title.trim());
    formData.append("description", description.trim());
    formData.append("category", category.trim() || "Général");

    setUploading(true);
    setProgress(0);

    try {
      const response = await api.post("/resources", formData, {
        onUploadProgress: (progressEvent) => {
          if (progressEvent.total) {
            setProgress(
              Math.round((progressEvent.loaded * 100) / progressEvent.total)
            );
          }
        },
      });

      setResources((current) => [response.data, ...current]);
      setFile(null);
      setTitle("");
      setDescription("");
      setCategory("Général");

      if (inputRef.current) inputRef.current.value = "";

      toast.success("Ressource publiée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setUploading(false);
      setProgress(0);
    }
  };

  const download = async (resource) => {
    try {
      const response = await api.get(`/resources/${resource.id}/download`, {
        responseType: "blob",
      });

      const url = URL.createObjectURL(response.data);
      const link = document.createElement("a");

      link.href = url;
      link.download = resource.original_filename;
      document.body.appendChild(link);
      link.click();
      link.remove();

      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const preview = async (resource) => {
    try {
      const response = await api.get(`/resources/${resource.id}/download`, {
        responseType: "blob",
      });

      const url = URL.createObjectURL(response.data);

      window.open(url, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  const remove = async (resource) => {
    try {
      await api.delete(`/resources/${resource.id}`);
      setResources((current) => current.filter((item) => item.id !== resource.id));
      toast.success("Ressource retirée.");
    } catch (error) {
      toast.error(getErrorMessage(error));
    }
  };

  return (
    <section className="rl-page" data-testid="resources-page">
      <header className="rl-header">
        <div>
          <p className="rl-eyebrow">BIBLIOTHÈQUE PARTAGÉE</p>

          <h1>Ressources</h1>

          <p className="rl-intro">
            Règlements, repères et documents utiles à consulter à tout moment.
          </p>
        </div>

        <div className="rl-header-actions">
          <Link to="/" className="rl-ghost-button">
            Accueil
            <ArrowRight size={17} aria-hidden="true" />
          </Link>
        </div>
      </header>

      {isAdmin && (
        <form
          className="rl-upload"
          onSubmit={upload}
          data-testid="resource-upload-form"
        >
          <div className="rl-upload-copy">
            <span className="rl-upload-icon">
              <UploadCloud size={22} aria-hidden="true" />
            </span>

            <div>
              <h2>Ajouter une ressource</h2>
              <p>PDF, Word, image ou texte jusqu’à 250 Mo.</p>
            </div>
          </div>

          <div className="rl-upload-fields">
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,.doc,.docx,.jpg,.jpeg,.png,.webp,.gif,.txt"
              onChange={(event) => chooseFile(event.target.files?.[0])}
              data-testid="resource-file-input"
            />

            <div className="rl-upload-text">
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Titre de la ressource"
                required
                data-testid="resource-title-input"
              />

              <input
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                placeholder="Catégorie"
                required
                data-testid="resource-category-input"
              />
            </div>

            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="Courte description (facultatif)"
              data-testid="resource-description-input"
            />

            {file && (
              <p className="rl-upload-file" data-testid="selected-resource-file">
                {file.name} · {formatSize(file.size)}
              </p>
            )}

            {uploading && (
              <div className="rl-upload-progress" data-testid="resource-upload-progress">
                <span style={{ width: `${progress}%` }} />
                <b>{progress}%</b>
              </div>
            )}

            <button
              className="rl-primary-button"
              disabled={uploading || !file || !title.trim()}
              type="submit"
              data-testid="upload-resource-button"
            >
              {uploading ? (
                <LoaderCircle className="spin" size={16} aria-hidden="true" />
              ) : (
                <FileUp size={16} aria-hidden="true" />
              )}
              {uploading ? "Publication…" : "Publier la ressource"}
            </button>
          </div>
        </form>
      )}

      <section className="rl-toolbar" aria-label="Filtres de ressources">
        <label className="rl-search">
          <Search size={17} aria-hidden="true" />

          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Rechercher un document, un thème ou un fichier…"
            aria-label="Rechercher une ressource"
          />
        </label>

        <div className="rl-filters">
          <button
            type="button"
            className={categoryFilter === "all" ? "is-selected" : ""}
            aria-pressed={categoryFilter === "all"}
            onClick={() => setCategoryFilter("all")}
          >
            Toutes les catégories
          </button>

          {categories.map((value) => (
            <button
              key={value}
              type="button"
              className={categoryFilter === value ? "is-selected" : ""}
              aria-pressed={categoryFilter === value}
              onClick={() => setCategoryFilter(value)}
            >
              {value}
            </button>
          ))}

          {hasFilters && (
            <button type="button" className="rl-reset" onClick={clearFilters}>
              <X size={13} aria-hidden="true" />
              Effacer
            </button>
          )}
        </div>
      </section>

      {loading ? (
        <div className="rl-state" role="status" data-testid="resources-loading">
          <LoaderCircle className="spin" size={26} aria-hidden="true" />
          <p>Chargement des ressources…</p>
        </div>
      ) : visibleResources.length === 0 ? (
        <div className="rl-state" data-testid="resources-empty">
          <FolderOpen size={32} aria-hidden="true" />

          <h2>
            {hasFilters
              ? "Aucune ressource ne correspond à cette sélection."
              : "Aucune ressource publiée pour le moment."}
          </h2>

          {hasFilters && (
            <button type="button" className="rl-empty-button" onClick={clearFilters}>
              Afficher toutes les ressources
            </button>
          )}
        </div>
      ) : (
        <>
          <p className="rl-result" role="status">
            {visibleResources.length} ressource
            {visibleResources.length > 1 ? "s" : ""} disponible
            {visibleResources.length > 1 ? "s" : ""}
          </p>

          <div className="rl-grid" data-testid="resource-grid">
            {visibleResources.map((resource) => (
              <article
                key={resource.id}
                className="rl-card"
                data-testid={`resource-card-${resource.id}`}
              >
                <span
                  className={`rl-card-preview ${
                    String(resource.content_type || "").includes("pdf")
                      ? "rl-card-preview-pdf"
                      : ""
                  }`}
                >
                  <ResourceIcon type={resource.content_type} />
                  {typeLabel(resource)}
                </span>

                <div className="rl-card-body">
                  {resource.category && (
                    <span className="rl-card-category">{resource.category}</span>
                  )}

                  <h2>{resource.title}</h2>

                  <p>{resource.description || resource.original_filename}</p>

                  <span className="rl-card-meta">
                    {formatSize(resource.size)} · {formatDate(resource.created_at)}
                  </span>
                </div>

                <div className="rl-card-actions">
                  <button
                    type="button"
                    onClick={() => preview(resource)}
                    data-testid={`preview-resource-${resource.id}`}
                  >
                    <Eye size={15} aria-hidden="true" />
                    Prévisualiser
                  </button>

                  <button
                    type="button"
                    onClick={() => download(resource)}
                    data-testid={`download-resource-${resource.id}`}
                  >
                    <Download size={15} aria-hidden="true" />
                    Télécharger
                  </button>

                  {isAdmin && (
                    <button
                      type="button"
                      className="rl-danger"
                      onClick={() => remove(resource)}
                      data-testid={`delete-resource-${resource.id}`}
                      aria-label={`Retirer ${resource.title}`}
                    >
                      <Trash2 size={15} aria-hidden="true" />
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}

      <footer className="rl-footer">
        <span>
          <BookOpen size={15} aria-hidden="true" />
          Les ressources restent accessibles aux helpers.
        </span>

        <Link to="/archives">
          Consulter les archives
          <ArrowRight size={15} aria-hidden="true" />
        </Link>
      </footer>
    </section>
  );
}

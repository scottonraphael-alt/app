import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  Ban,
  DoorOpen,
  Eye,
  MegaphoneOff,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  TriangleAlert,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { api, getErrorMessage } from "../api/client";
import TiptapSummaryEditor from "../components/TiptapSummaryEditor";
import SummaryReader from "../components/SummaryReader";

const SANCTION_TYPES = [
  { value: "avertissement", label: "Avertissement", icon: TriangleAlert },
  { value: "rappel_a_lordre", label: "Rappel à l'ordre", icon: MegaphoneOff },
  { value: "kick", label: "Kick", icon: DoorOpen },
  { value: "bannissement", label: "Bannissement", icon: Ban },
];

const STATUS_LABELS = {
  vierge: "Vierge",
  vigilance: "Vigilance",
  surveillance: "Surveillance",
  sanctionne: "Sanctionné",
  bloque: "Banni",
};

function sanctionMeta(type) {
  return SANCTION_TYPES.find((item) => item.value === type) || { label: type, icon: Shield };
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("fr-FR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function MemberAvatar({ member, size = 34 }) {
  const label = member?.display_name || member?.username || "?";

  return (
    <span className="moderation-avatar" style={{ width: size, height: size }} title={label} aria-label={label}>
      {member?.avatar_url ? <img src={member.avatar_url} alt="" /> : <Shield size={Math.round(size * 0.5)} />}
    </span>
  );
}

function StatusBadge({ status }) {
  const label = STATUS_LABELS[status] || status;
  return <span className={`casier-status-badge is-${status}`}>{label}</span>;
}

/* ---------------------------------- */
/* Modal: créer un casier             */
/* ---------------------------------- */

function CreateCasierModal({ open, onClose, onCreated }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState([]);
  const [selectedMember, setSelectedMember] = useState(null);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [manualMode, setManualMode] = useState(false);
  const [manualDiscordId, setManualDiscordId] = useState("");
  const [manualUsername, setManualUsername] = useState("");

  const inputRef = useRef(null);
  const debounceRef = useRef(null);
  const requestIdRef = useRef(0);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setResults([]);
    setSelectedMember(null);
    setLoading(false);
    setSubmitting(false);
    setManualMode(false);
    setManualDiscordId("");
    setManualUsername("");
    const timer = setTimeout(() => inputRef.current?.focus(), 0);
    return () => clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const needle = query.trim();

    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (needle.length < 2 || selectedMember) {
      setLoading(false);
      if (needle.length < 2) setResults([]);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      const requestId = ++requestIdRef.current;
      setLoading(true);
      try {
        const response = await api.get("/moderation/casiers/search-members", { params: { q: needle } });
        if (!aliveRef.current || requestId !== requestIdRef.current) return;
        setResults(Array.isArray(response?.data) ? response.data : []);
      } catch (error) {
        if (!aliveRef.current || requestId !== requestIdRef.current) return;
        setResults([]);
        toast.error(getErrorMessage(error));
      } finally {
        if (aliveRef.current && requestId === requestIdRef.current) setLoading(false);
      }
    }, 250);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, open, selectedMember]);

  const handlePickMember = (member) => {
    if (!member?.id) return;
    setSelectedMember(member);
    setQuery(member.display_name || member.username || "");
    setResults([]);
  };

  const handleSubmit = async () => {
    if (manualMode) {
      const discordId = manualDiscordId.trim();
      const username = manualUsername.trim();

      if (!/^\d{17,21}$/.test(discordId)) {
        toast.error("L'ID Discord doit être une suite de 17 à 21 chiffres.");
        return;
      }
      if (!username) {
        toast.error("Renseigne un pseudo pour identifier ce membre.");
        return;
      }

      setSubmitting(true);
      try {
        const response = await api.post("/moderation/casiers", { discord_id: discordId, username });
        toast.success("Casier créé en prévention.");
        onCreated?.(response?.data);
        onClose?.();
      } catch (error) {
        toast.error(getErrorMessage(error));
      } finally {
        setSubmitting(false);
      }
      return;
    }

    if (!selectedMember?.id) {
      toast.error("Sélectionne un membre dans la liste.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.post("/moderation/casiers", { discord_id: selectedMember.id });
      toast.success("Casier créé.");
      onCreated?.(response?.data);
      onClose?.();
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return createPortal(
    <div className="casier-modal-backdrop" role="presentation" onClick={() => (!submitting ? onClose?.() : null)}>
      <div
        className="casier-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-casier-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="casier-modal-header">
          <div>
            <p className="eyebrow">MODÉRATION</p>
            <h2 id="create-casier-title">Créer un casier</h2>
          </div>
          <button type="button" className="icon-button" onClick={() => onClose?.()} aria-label="Fermer" disabled={submitting}>
            <X size={16} />
          </button>
        </div>

        <div className="casier-modal-body">
          {!manualMode ? (
            <>
              <div className="moderation-field">
                <label htmlFor="discord-member-search">Membre Discord</label>
                <div className="casier-search-wrap">
                  <Search size={16} />
                  <input
                    ref={inputRef}
                    id="discord-member-search"
                    value={query}
                    onChange={(event) => {
                      const value = event.target.value;
                      setQuery(value);
                      if (selectedMember && value !== (selectedMember.display_name || selectedMember.username || "")) {
                        setSelectedMember(null);
                      }
                    }}
                    placeholder="Pseudo ou nickname"
                    autoComplete="off"
                  />
                </div>
                <small>Tape au moins 2 caractères puis choisis un membre dans la liste.</small>
              </div>

              {!selectedMember && query.trim().length >= 2 && (
                <div className="casier-results-list">
                  {loading ? (
                    <p className="resources-empty">Recherche…</p>
                  ) : results.length === 0 ? (
                    <p className="resources-empty">Aucun membre trouvé.</p>
                  ) : (
                    results.map((member) => (
                      <button key={member.id} type="button" className="casier-result-row" onClick={() => handlePickMember(member)}>
                        <MemberAvatar member={member} size={38} />
                        <div className="casier-result-copy">
                          <strong>{member.display_name || member.username}</strong>
                          <small>@{member.username}</small>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              )}

              {selectedMember && (
                <div className="casier-selection-row">
                  <MemberAvatar member={selectedMember} size={42} />
                  <div>
                    <strong>{selectedMember.display_name || selectedMember.username}</strong>
                    <small>@{selectedMember.username}</small>
                  </div>
                </div>
              )}

              <button type="button" className="casier-manual-toggle" onClick={() => setManualMode(true)}>
                Le membre n'est pas encore sur le serveur ? Créer une fiche en prévention
              </button>
            </>
          ) : (
            <>
              <p className="fiche-s-warning">
                Ce casier sera créé en <strong>prévention</strong>, avant l'arrivée du membre. Dès qu'il
                rejoindra le serveur, ses infos Discord (pseudo, avatar) se mettront à jour automatiquement.
              </p>

              <div className="moderation-field">
                <label htmlFor="manual-discord-id">ID Discord</label>
                <input
                  id="manual-discord-id"
                  value={manualDiscordId}
                  onChange={(event) => setManualDiscordId(event.target.value.replace(/[^\d]/g, ""))}
                  placeholder="Ex. 123456789012345678"
                  autoComplete="off"
                  inputMode="numeric"
                />
                <small>Suite de 17 à 21 chiffres (identifiant Discord du membre).</small>
              </div>

              <div className="moderation-field">
                <label htmlFor="manual-username">Pseudo</label>
                <input
                  id="manual-username"
                  value={manualUsername}
                  onChange={(event) => setManualUsername(event.target.value)}
                  placeholder="Pseudo connu du membre"
                  autoComplete="off"
                  maxLength={80}
                />
              </div>

              <button type="button" className="casier-manual-toggle" onClick={() => setManualMode(false)}>
                Retour à la recherche sur le serveur
              </button>
            </>
          )}

          <div className="casier-actions">
            <button type="button" className="calm-primary-button is-secondary" onClick={() => onClose?.()} disabled={submitting}>
              Annuler
            </button>
            <button
              type="button"
              className="calm-primary-button"
              onClick={handleSubmit}
              disabled={manualMode ? !manualDiscordId.trim() || !manualUsername.trim() || submitting : !selectedMember?.id || submitting}
            >
              <ShieldAlert size={16} />
              {submitting ? "Création…" : manualMode ? "Créer en prévention" : "Créer le casier"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}

/* ---------------------------------- */
/* Modal: ajouter une sanction        */
/* ---------------------------------- */

function AddSanctionModal({ open, casier, onClose, onAdded }) {
  const [type, setType] = useState("avertissement");
  const [reason, setReason] = useState("");
  const [duration, setDuration] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setType("avertissement");
    setReason("");
    setDuration("");
    setSubmitting(false);
  }, [open]);

  if (!open || !casier) return null;

  const needsDuration = type === "bannissement";

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (!reason.trim()) {
      toast.error("Ajoute un motif.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.post(`/moderation/casiers/${casier.id}/sanctions`, {
        type,
        reason: reason.trim(),
        duration: needsDuration && duration.trim() ? duration.trim() : null,
      });

      toast.success("Sanction enregistrée.");
      onAdded?.(response?.data);
      onClose?.();
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  return createPortal(
    <div className="casier-modal-backdrop" role="presentation" onClick={() => (!submitting ? onClose?.() : null)}>
      <div
        className="casier-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-sanction-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="casier-modal-header">
          <div>
            <p className="eyebrow">MODÉRATION</p>
            <h2 id="add-sanction-title">Ajouter une sanction</h2>
          </div>
          <button type="button" className="icon-button" onClick={() => onClose?.()} aria-label="Fermer" disabled={submitting}>
            <X size={16} />
          </button>
        </div>

        <form className="casier-modal-body" onSubmit={handleSubmit}>
          <div className="casier-selection-row">
            <MemberAvatar member={casier.member} size={40} />
            <div>
              <strong>{casier.member?.display_name || casier.member?.username}</strong>
              <small>@{casier.member?.username}</small>
            </div>
          </div>

          <div className="moderation-field">
            <label>Type de sanction</label>
            <div className="casier-type-grid">
              {SANCTION_TYPES.map((item) => {
                const Icon = item.icon;
                const isActive = item.value === type;
                return (
                  <button
                    key={item.value}
                    type="button"
                    className={`casier-type-option ${isActive ? "is-active" : ""}`}
                    onClick={() => setType(item.value)}
                  >
                    <Icon size={16} />
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="moderation-field">
            <label htmlFor="sanction-reason">Motif</label>
            <textarea
              id="sanction-reason"
              rows={4}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Décris les faits précisément."
              maxLength={1000}
            />
          </div>

          {needsDuration && (
            <div className="moderation-field">
              <label htmlFor="sanction-duration">Durée (optionnel)</label>
              <input
                id="sanction-duration"
                value={duration}
                onChange={(event) => setDuration(event.target.value)}
                placeholder="Ex. 7 jours, permanent…"
              />
            </div>
          )}

          <div className="casier-actions">
            <button type="button" className="calm-primary-button is-secondary" onClick={() => onClose?.()} disabled={submitting}>
              Annuler
            </button>
            <button type="submit" className="calm-primary-button" disabled={submitting}>
              <ShieldAlert size={16} />
              {submitting ? "Enregistrement…" : "Enregistrer la sanction"}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}

/* ---------------------------------- */
/* Modal: rédiger une fiche S         */
/* ---------------------------------- */

function AddFicheSModal({ open, casier, onClose, onAdded }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setTitle("");
    setContent("");
    setSubmitting(false);
  }, [open]);

  if (!open || !casier) return null;

  const isContentEmpty = !content || !content.replace(/<[^>]*>/g, "").trim();

  const handleSubmit = async (event) => {
    event.preventDefault();

    if (!title.trim() || isContentEmpty) {
      toast.error("Renseigne un titre et des observations.");
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.post(`/moderation/casiers/${casier.id}/fiches-s`, {
        title: title.trim(),
        content,
      });

      toast.success("Fiche S créée — membre placé en surveillance.");
      onAdded?.(response?.data);
      onClose?.();
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  return createPortal(
    <div className="casier-modal-backdrop" role="presentation" onClick={() => (!submitting ? onClose?.() : null)}>
      <div
        className="casier-modal casier-fiche-s-modal casier-modal-wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-fiche-s-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="casier-modal-header">
          <div>
            <p className="eyebrow fiche-s-eyebrow">
              <Eye size={13} /> FICHE S
            </p>
            <h2 id="add-fiche-s-title">Rédiger une fiche S</h2>
          </div>
          <button type="button" className="icon-button" onClick={() => onClose?.()} aria-label="Fermer" disabled={submitting}>
            <X size={16} />
          </button>
        </div>

        <form className="casier-modal-body fiche-s-modal-body" onSubmit={handleSubmit}>
          <div className="casier-selection-row">
            <MemberAvatar member={casier.member} size={40} />
            <div>
              <strong>{casier.member?.display_name || casier.member?.username}</strong>
              <small>@{casier.member?.username}</small>
            </div>
          </div>

          <p className="fiche-s-warning">
            Créer une fiche S place immédiatement ce membre en <strong>surveillance</strong>, même sans
            sanction. Réserve-la aux comportements préoccupants à documenter dans la durée.
          </p>

          <div className="fiche-s-field">
            <label htmlFor="fiche-s-title">Titre</label>
            <input
              id="fiche-s-title"
              className="fiche-s-title-input"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Ex. Comportement suspect répété en vocal"
              maxLength={160}
            />
          </div>

          <div className="fiche-s-field">
            <label>Observations</label>
            <TiptapSummaryEditor
              value={content}
              onChange={setContent}
              placeholder="Décris les faits observés, le contexte, et pourquoi ce membre doit être suivi. Tapez / pour les commandes."
            />
          </div>

          <div className="casier-actions">
            <button type="button" className="calm-primary-button is-secondary" onClick={() => onClose?.()} disabled={submitting}>
              Annuler
            </button>
            <button type="submit" className="calm-primary-button is-fiche-s" disabled={submitting}>
              <Eye size={16} />
              {submitting ? "Création…" : "Créer la fiche S"}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body
  );
}

/* ---------------------------------- */
/* Page principale                    */
/* ---------------------------------- */

export default function ModerationCasierPage() {
  const [casiers, setCasiers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedCasierId, setSelectedCasierId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [sanctionOpen, setSanctionOpen] = useState(false);
  const [ficheSOpen, setFicheSOpen] = useState(false);
  const [closingFicheId, setClosingFicheId] = useState(null);

  const fetchCasiers = async () => {
    setLoading(true);
    try {
      const response = await api.get("/moderation/casiers");
      const data = Array.isArray(response?.data) ? response.data : [];
      setCasiers(data);
      if (!selectedCasierId && data.length > 0) {
        setSelectedCasierId(data[0].id);
      }
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCasiers();
  }, []);

  const fetchDetail = async (casierId) => {
    if (!casierId) {
      setDetail(null);
      return;
    }

    setDetailLoading(true);
    try {
      const response = await api.get(`/moderation/casiers/${casierId}`);
      setDetail(response?.data || null);
    } catch (error) {
      setDetail(null);
      toast.error(getErrorMessage(error));
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    fetchDetail(selectedCasierId);
  }, [selectedCasierId]);

  const filteredCasiers = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return casiers;

    return casiers.filter((casier) => {
      const username = casier.member?.username?.toLowerCase() || "";
      const displayName = casier.member?.display_name?.toLowerCase() || "";
      return username.includes(needle) || displayName.includes(needle);
    });
  }, [casiers, search]);

  const handleCasierCreated = () => {
    fetchCasiers();
  };

  const handleDetailUpdated = (updatedDetail) => {
    if (updatedDetail) {
      setDetail(updatedDetail);
    } else {
      fetchDetail(selectedCasierId);
    }
    fetchCasiers();
  };

  const handleCloseFicheS = async (ficheId) => {
    if (!detail?.id) return;

    setClosingFicheId(ficheId);
    try {
      const response = await api.patch(`/moderation/casiers/${detail.id}/fiches-s/${ficheId}/close`);
      toast.success("Fiche S clôturée.");
      handleDetailUpdated(response?.data);
    } catch (error) {
      toast.error(getErrorMessage(error));
    } finally {
      setClosingFicheId(null);
    }
  };

  return (
    <section className="page-content staff-page moderation-page casier-page" data-testid="moderation-casier-page">
      <header className="page-header casier-hero">
        <div>
          <p className="eyebrow">ESPACE OPERATEUR</p>
          <h1>Casier</h1>
        </div>

        <div className="dashboard-actions">
          <button className="calm-primary-button" type="button" onClick={() => setCreateOpen(true)}>
            <ShieldCheck size={17} />
            Créer un casier
          </button>
        </div>
      </header>

      <div className="casier-layout">
        <aside className="casier-list-column">
          <div className="casier-search-wrap">
            <Search size={16} />
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filtrer par pseudo" autoComplete="off" />
          </div>

          <div className="casier-list">
            {loading ? (
              <p className="resources-empty">Chargement…</p>
            ) : filteredCasiers.length === 0 ? (
              <div className="casier-empty-state">
                <ShieldCheck size={18} />
                <p>Aucun casier pour l’instant.</p>
              </div>
            ) : (
              filteredCasiers.map((casier) => {
                const isSelected = casier.id === selectedCasierId;
                return (
                  <button
                    key={casier.id}
                    type="button"
                    className={`casier-list-row ${isSelected ? "is-selected" : ""}`}
                    onClick={() => setSelectedCasierId(casier.id)}
                  >
                    <MemberAvatar member={casier.member} size={40} />
                    <div className="casier-list-copy">
                      <div className="casier-list-heading">
  <strong>{casier.member?.display_name || casier.member?.username}</strong>
  <StatusBadge status={casier.status} />
  {casier.is_prevention && (
    <span className="casier-status-badge is-prevention" title="Membre pas encore sur le serveur">
      Prévention
    </span>
  )}
  {casier.has_active_fiche_s && (
    <span className="fiche-s-tag" title="Fiche S active">
      <Eye size={11} /> S
    </span>
  )}
</div>
</div>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        <div className="casier-detail-column">
          {detailLoading ? (
            <p className="resources-empty">Chargement du casier…</p>
          ) : !detail ? (
            <div className="casier-empty-state">
              <Shield size={18} />
              <p>Sélectionne un casier pour voir le détail.</p>
            </div>
          ) : (
            <>
              <div className="casier-detail-header">
                <div className="casier-detail-identity">
                  <MemberAvatar member={detail.member} size={56} />
                  <div>
                    <h2>{detail.member?.display_name || detail.member?.username}</h2>
                    <small>@{detail.member?.username}</small>
                    <small className="casier-detail-id">ID Discord : {detail.member?.id}</small>
                  </div>
                </div>

                <div className="casier-detail-summary">
  <StatusBadge status={detail.status} />
  {detail.is_prevention && (
    <span className="casier-status-badge is-prevention" title="Membre pas encore sur le serveur">
      Prévention
    </span>
  )}
     <span className="casier-status-badge is-count">
  {detail.sanctions_count} sanction{detail.sanctions_count === 1 ? "" : "s"}
</span>
  <div className="casier-detail-type-badges">
    {detail.sanctions_summary?.avertissement > 0 && (
      <span className="casier-type-badge is-avertissement">
        {detail.sanctions_summary.avertissement} warn
      </span>
    )}
    {detail.sanctions_summary?.kick > 0 && (
      <span className="casier-type-badge is-kick">
        {detail.sanctions_summary.kick} kick
      </span>
    )}
    {detail.sanctions_summary?.bannissement > 0 && (
      <span className="casier-type-badge is-bannissement">
        {detail.sanctions_summary.bannissement} ban
      </span>
    )}
    {detail.sanctions_summary?.rappel_a_lordre > 0 && (
      <span className="casier-type-badge is-rappel">
        {detail.sanctions_summary.rappel_a_lordre} rappel
      </span>
    )}
  </div>
</div>

                <div className="casier-detail-actions">
                  <button className="calm-primary-button is-fiche-s" type="button" onClick={() => setFicheSOpen(true)}>
                    <Eye size={16} />
                    Rédiger une fiche S
                  </button>
                  <button className="calm-primary-button" type="button" onClick={() => setSanctionOpen(true)}>
                    <ShieldAlert size={16} />
                    Ajouter une sanction
                  </button>
                </div>
              </div>

              {detail.fiches_s.length > 0 && (
                <div className="fiche-s-section">
                  <p className="fiche-s-section-title">
                    <Eye size={14} /> Fiches S
                  </p>

                  <div className="fiche-s-list">
                    {detail.fiches_s.map((fiche) => (
                      <article key={fiche.id} className={`fiche-s-card ${fiche.active ? "is-active" : "is-closed"}`}>
                        <div className="fiche-s-card-head">
                          <strong>{fiche.title}</strong>
                          <span className={`fiche-s-status ${fiche.active ? "is-active" : "is-closed"}`}>
                            {fiche.active ? "Active" : "Clôturée"}
                          </span>
                        </div>

                        <div className="fiche-s-card-content tiptap-readonly">
                          <SummaryReader content={fiche.content} />
                        </div>

                        <div className="fiche-s-card-foot">
                          <small>
                            Rédigée par {fiche.created_by?.display_name || fiche.created_by?.username || "Staff"} ·{" "}
                            {formatDate(fiche.created_at)}
                          </small>
                          {fiche.active ? (
                            <button
                              type="button"
                              className="fiche-s-close-button"
                              onClick={() => handleCloseFicheS(fiche.id)}
                              disabled={closingFicheId === fiche.id}
                            >
                              {closingFicheId === fiche.id ? "Clôture…" : "Clôturer"}
                            </button>
                          ) : (
                            <small>
                              Clôturée par {fiche.closed_by?.display_name || fiche.closed_by?.username || "Staff"} ·{" "}
                              {formatDate(fiche.closed_at)}
                            </small>
                          )}
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              )}

              <div className="casier-sanctions">
                {detail.sanctions.length === 0 ? (
                  <div className="casier-empty-state">
                    <ShieldCheck size={18} />
                    <p>Aucune sanction enregistrée pour ce membre.</p>
                  </div>
                ) : (
                  detail.sanctions.map((sanction, index) => {
                    const meta = sanctionMeta(sanction.type);
                    const Icon = meta.icon;
                    return (
                      <article key={index} className={`casier-sanction-row is-${sanction.type}`}>
                        <span className="casier-sanction-icon">
                          <Icon size={16} />
                        </span>
                        <div className="casier-sanction-body">
                          <div className="casier-sanction-head">
                            <strong>{meta.label}</strong>
                            <small>{formatDate(sanction.created_at)}</small>
                          </div>
                          <p>{sanction.reason}</p>
                          <small>
                            Par {sanction.created_by?.display_name || sanction.created_by?.username || "Staff"}
                            {sanction.duration ? ` · Durée ${sanction.duration}` : ""}
                          </small>
                        </div>
                      </article>
                    );
                  })
                )}
              </div>
            </>
          )}
        </div>
      </div>

      <CreateCasierModal open={createOpen} onClose={() => setCreateOpen(false)} onCreated={handleCasierCreated} />

      <AddSanctionModal open={sanctionOpen} casier={detail} onClose={() => setSanctionOpen(false)} onAdded={handleDetailUpdated} />

      <AddFicheSModal open={ficheSOpen} casier={detail} onClose={() => setFicheSOpen(false)} onAdded={handleDetailUpdated} />
    </section>
  );
}

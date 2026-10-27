import { useCallback, useId, useMemo, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { Check, ChevronDown, RefreshCw, Search, UserPlus, Users, UserX, X } from "lucide-react";

import "@/Agenda.css";

import { useAgendaPortalContainer } from "./AgendaDialog";
import { agendaQueries } from "./agendaApi";
import { TEXT_LIMITS } from "./agendaConstants";
import { helperName } from "./calendarModel";
import HelperAvatar from "./HelperAvatar";

const ALL_VALUE = "__tout-le-staff__";
const NONE_VALUE = "__personne__";
const MISSING_LABEL = "ne fait plus partie du staff";

// Minuscules sans accents : « Élodie » est trouvée en tapant « elo ».
export function normalizeSearch(text) {
  return String(text || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .trim();
}

function filterPeople(value, search, keywords) {
  const needle = normalizeSearch(search);
  if (!needle) return 1;
  const haystack = normalizeSearch([value, ...(keywords || [])].join(" "));
  return haystack.includes(needle) ? 1 : 0;
}

function asList(selected) {
  if (Array.isArray(selected)) return selected.filter((person) => person && person.id);
  return selected && selected.id ? [selected] : [];
}

function toIdentity(person) {
  return {
    id: String(person.id),
    username: person.username || "",
    display_name: person.display_name ?? null,
    avatar_url: person.avatar_url ?? null,
  };
}

function joinClasses(...values) {
  return values.filter(Boolean).join(" ");
}

// Sélecteur de membres du staff (GET /agenda/people). `selected` contient des identités complètes :
// une personne qui n'est plus dans l'annuaire reste affichée, cochée et retirable.
export default function PeoplePicker({
  mode = "multiple",
  selected,
  onChange,
  label = null,
  placeholder = null,
  emptyLabel = "Personne pour l'instant.",
  noneLabel = "Non attribuée",
  allowNone = true,
  showAll = true,
  max = TEXT_LIMITS.participants,
  size = "md",
  disabled = false,
  invalid = false,
  describedBy,
  id,
  className = "",
  align = "start",
}) {
  const single = mode === "single";
  const generatedId = useId();
  const baseId = id || `ag-people-${generatedId.replace(/[^A-Za-z0-9_-]/g, "")}`;
  const labelId = `${baseId}-label`;
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const container = useAgendaPortalContainer();

  const peopleQuery = useQuery({ ...agendaQueries.people(), enabled: !disabled || open });
  const hasDirectory = Array.isArray(peopleQuery.data);
  const directory = useMemo(() => (Array.isArray(peopleQuery.data) ? peopleQuery.data : []), [peopleQuery.data]);
  const directoryIds = useMemo(() => new Set(directory.map((person) => String(person.id))), [directory]);

  const chosen = useMemo(() => asList(selected), [selected]);
  const chosenIds = useMemo(() => new Set(chosen.map((person) => String(person.id))), [chosen]);
  const missing = useMemo(
    () => (hasDirectory ? chosen.filter((person) => !directoryIds.has(String(person.id))) : []),
    [chosen, directoryIds, hasDirectory],
  );
  const missingIds = useMemo(() => new Set(missing.map((person) => String(person.id))), [missing]);
  const allSelected = directory.length > 0 && directory.every((person) => chosenIds.has(String(person.id)));
  const atMax = !single && chosen.length >= max;

  const emit = useCallback(
    (list) => {
      if (!onChange) return;
      if (single) onChange(list.length ? toIdentity(list[0]) : null);
      else onChange(list.slice(0, max).map(toIdentity));
    },
    [max, onChange, single],
  );

  const handleOpenChange = useCallback((next) => {
    setOpen(next);
    if (!next) setSearch("");
  }, []);

  const toggle = useCallback(
    (person) => {
      const key = String(person.id);
      if (single) {
        emit([person]);
        handleOpenChange(false);
        return;
      }
      if (chosenIds.has(key)) {
        emit(chosen.filter((item) => String(item.id) !== key));
      } else if (chosen.length < max) {
        emit([...chosen, person]);
      }
    },
    [chosen, chosenIds, emit, handleOpenChange, max, single],
  );

  const remove = useCallback(
    (person) => emit(chosen.filter((item) => String(item.id) !== String(person.id))),
    [chosen, emit],
  );

  const toggleAll = useCallback(() => {
    if (allSelected) {
      emit(chosen.filter((person) => !directoryIds.has(String(person.id))));
      return;
    }
    const additions = directory.filter((person) => !chosenIds.has(String(person.id)));
    emit([...chosen, ...additions]);
  }, [allSelected, chosen, chosenIds, directory, directoryIds, emit]);

  const clearSingle = useCallback(() => {
    emit([]);
    handleOpenChange(false);
  }, [emit, handleOpenChange]);

  const current = single ? chosen[0] || null : null;
  const triggerText = single
    ? current
      ? helperName(current)
      : placeholder || noneLabel
    : chosen.length
      ? "Ajouter"
      : placeholder || "Choisir";

  const trigger = single ? (
    <button
      type="button"
      id={baseId}
      className={joinClasses(
        "ag-people-trigger",
        size === "sm" ? "ag-people-trigger--sm" : "",
        invalid ? "is-invalid" : "",
      )}
      disabled={disabled}
      aria-labelledby={label ? `${labelId} ${baseId}` : undefined}
      aria-describedby={describedBy}
    >
      {current ? (
        <span className="ag-person">
          <HelperAvatar person={current} size={size === "sm" ? 22 : 26} decorative />
          <span className="ag-person-name">{helperName(current)}</span>
          {missingIds.has(String(current.id)) ? <span className="ag-sr-only"> ({MISSING_LABEL})</span> : null}
        </span>
      ) : (
        <span className="ag-people-placeholder">{triggerText}</span>
      )}
      {disabled ? null : <ChevronDown size={16} aria-hidden="true" />}
    </button>
  ) : (
    <button
      type="button"
      id={baseId}
      className="ag-people-add"
      disabled={disabled || (atMax && !open)}
      aria-labelledby={label ? `${labelId} ${baseId}` : undefined}
      aria-describedby={describedBy}
    >
      <UserPlus size={14} aria-hidden="true" />
      {triggerText}
    </button>
  );

  const renderOption = (person, isMissing) => {
    const key = String(person.id);
    const checked = chosenIds.has(key);
    const name = helperName(person);
    const secondary = isMissing ? MISSING_LABEL : person.username && person.username !== name ? `@${person.username}` : "";
    return (
      <Command.Item
        key={key}
        value={key}
        keywords={[name, person.username || ""]}
        className="ag-people-option"
        disabled={!checked && atMax}
        aria-checked={checked}
        onSelect={() => toggle(person)}
      >
        <HelperAvatar person={person} size={28} decorative />
        <span className="ag-people-option-text">
          <strong>{name}</strong>
          {secondary ? <small className={isMissing ? "is-missing" : undefined}>{secondary}</small> : null}
        </span>
        <span className="ag-people-check" aria-hidden="true">
          {checked ? <Check size={16} /> : null}
        </span>
        {checked ? <span className="ag-sr-only">(sélectionné)</span> : null}
      </Command.Item>
    );
  };

  const popover = (
    <Popover.Portal container={container}>
      <Popover.Content
        className="ag-popover ag-people-popover"
        align={align}
        side="bottom"
        sideOffset={6}
        collisionPadding={12}
      >
        <Command
          className="ag-people-command"
          label={single ? "Choisir une personne" : "Choisir des personnes"}
          filter={filterPeople}
          loop
        >
          <div className="ag-people-search">
            <Search size={15} aria-hidden="true" />
            <Command.Input
              className="ag-people-input"
              value={search}
              onValueChange={setSearch}
              placeholder="Rechercher un membre…"
              aria-label="Rechercher un membre du staff"
              maxLength={60}
            />
          </div>
          {peopleQuery.isError && !hasDirectory ? (
            <div className="ag-people-error" role="alert">
              <span>Liste du staff indisponible.</span>
              <button
                type="button"
                className="ag-error-retry"
                onClick={() => peopleQuery.refetch()}
                disabled={peopleQuery.isFetching}
              >
                <RefreshCw size={13} aria-hidden="true" className={peopleQuery.isFetching ? "ag-spin" : undefined} />
                Réessayer
              </button>
            </div>
          ) : null}
          <Command.List className="ag-people-list" label="Membres du staff">
            {peopleQuery.isPending ? (
              <Command.Loading label="Chargement du staff">
                <p className="ag-people-status">Chargement du staff…</p>
              </Command.Loading>
            ) : null}
            {hasDirectory ? <Command.Empty className="ag-people-status">Aucun membre ne correspond.</Command.Empty> : null}
            {single && allowNone && current ? (
              <Command.Item value={NONE_VALUE} keywords={[noneLabel, "aucun", "personne"]} className="ag-people-option" onSelect={clearSingle}>
                <span className="ag-people-option-icon" aria-hidden="true">
                  <UserX size={15} />
                </span>
                <span className="ag-people-option-text">
                  <strong>{noneLabel}</strong>
                </span>
              </Command.Item>
            ) : null}
            {!single && showAll && directory.length > 1 ? (
              <Command.Item
                value={ALL_VALUE}
                keywords={["tout le staff", "tous", "toutes", "everyone"]}
                className="ag-people-option"
                onSelect={toggleAll}
                disabled={!allSelected && directory.length + missing.length > max}
              >
                <span className="ag-people-option-icon" aria-hidden="true">
                  <Users size={15} />
                </span>
                <span className="ag-people-option-text">
                  <strong>{allSelected ? "Retirer tout le staff" : "Tout le staff"}</strong>
                  <small>{directory.length} membres</small>
                </span>
              </Command.Item>
            ) : null}
            {directory.length ? (
              <Command.Group heading="Staff" className="ag-people-group">
                {directory.map((person) => renderOption(person, false))}
              </Command.Group>
            ) : null}
            {missing.length ? (
              <Command.Group heading="Hors de l'annuaire" className="ag-people-group">
                {missing.map((person) => renderOption(person, true))}
              </Command.Group>
            ) : null}
            {!hasDirectory && chosen.length ? (
              <Command.Group heading="Sélection" className="ag-people-group">
                {chosen.map((person) => renderOption(person, false))}
              </Command.Group>
            ) : null}
          </Command.List>
          {!single && atMax ? (
            <p className="ag-people-hint">{max} personnes au maximum.</p>
          ) : !single && chosen.length ? (
            <p className="ag-people-hint">
              {chosen.length} {chosen.length > 1 ? "personnes sélectionnées" : "personne sélectionnée"}
            </p>
          ) : null}
        </Command>
      </Popover.Content>
    </Popover.Portal>
  );

  return (
    <div
      className={joinClasses("ag-people", single ? "ag-people--single" : "", className)}
      role={label ? "group" : undefined}
      aria-labelledby={label ? labelId : undefined}
    >
      {label ? (
        <span className="ag-label" id={labelId}>
          {label}
        </span>
      ) : null}
      <Popover.Root open={open} onOpenChange={handleOpenChange}>
        {single ? (
          <Popover.Trigger asChild>{trigger}</Popover.Trigger>
        ) : (
          <Popover.Anchor asChild>
            <div className={joinClasses("ag-people-field", invalid ? "is-invalid" : "")}>
              {chosen.length ? (
                <ul className="ag-people-chips" aria-label="Personnes sélectionnées">
                  {chosen.map((person) => {
                    const isMissing = missingIds.has(String(person.id));
                    const name = helperName(person);
                    return (
                      <li key={person.id} className={joinClasses("ag-people-chip", isMissing ? "is-missing" : "")}>
                        <HelperAvatar person={person} size={24} decorative />
                        <span className="ag-people-chip-text">
                          <span>{name}</span>
                          {isMissing ? <small>{MISSING_LABEL}</small> : null}
                        </span>
                        {disabled ? null : (
                          <button
                            type="button"
                            className="ag-people-chip-remove"
                            onClick={() => remove(person)}
                            aria-label={`Retirer ${name}`}
                          >
                            <X size={13} aria-hidden="true" />
                          </button>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <span className="ag-people-none">{emptyLabel}</span>
              )}
              {disabled ? null : <Popover.Trigger asChild>{trigger}</Popover.Trigger>}
            </div>
          </Popover.Anchor>
        )}
        {popover}
      </Popover.Root>
    </div>
  );
}

export { PeoplePicker };

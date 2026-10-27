import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { insertOrUpdateBlock, locales } from "@blocknote/core";
import {
  BlockNoteContext,
  FilePanelController,
  FormattingToolbarController,
  LinkToolbarController,
  SuggestionMenuController,
  getDefaultReactSlashMenuItems,
  useCreateBlockNote,
} from "@blocknote/react";
import { BlockNoteView } from "@blocknote/mantine";
import { CalendarDays, Gavel, SquareCheckBig } from "lucide-react";
import { toast } from "sonner";
import "@blocknote/mantine/style.css";
import "./editor-theme.css";
import { api } from "../api/client";

export const DEFAULT_UPLOAD_URL = "/staff/meetings/upload-image";

const VARIANTS = new Set(["default", "focus", "compact"]);
const MAX_DEPTH = 20;
const MEDIA_TYPES = new Set(["image", "video", "audio", "file"]);
// Mêmes schémas que le nettoyage du serveur (http, https, mailto), plus les liens sans schéma.
const SAFE_LINK_SCHEMES = new Set(["http", "https", "mailto"]);
// L'ancien éditeur écrivait les images avec cette origine en dur.
const LEGACY_MEDIA_URL = /^https?:\/\/api\.loasis\.app(\/api\/staff\/meetings\/images\/[A-Za-z0-9._-]+)$/i;

// Menus en position fixe : ils ne sont pas rognés par une fenêtre ou un panneau qui défile.
const FLOATING_OPTIONS = { strategy: "fixed" };

// Origine du backend, déduite du client API (baseURL = `${REACT_APP_BACKEND_URL}/api`).
const BACKEND_ORIGIN = String(api.defaults.baseURL || "")
  .replace(/\/api\/?$/, "")
  .replace(/^undefined$/, "")
  .replace(/\/+$/, "");

export const IRIS_EDITOR_THEME = {
  colors: {
    editor: { text: "#1c2622", background: "#ffffff" },
    menu: { text: "#1c2622", background: "#ffffff" },
    tooltip: { text: "#ffffff", background: "#1c2622" },
    hovered: { text: "#1c2622", background: "#e8efea" },
    selected: { text: "#ffffff", background: "#4a675c" },
    disabled: { text: "#a3aca6", background: "#f5f6f2" },
    shadow: "#dfe6e0",
    border: "#e2e8e2",
    sideMenu: "#a3aca6",
  },
  borderRadius: 10,
  fontFamily: "\"IBM Plex Sans\", sans-serif",
};

// L'éditeur reste en thème clair, même si le système est en mode sombre.
export const IRIS_COLOR_SCHEME = { colorSchemePreference: "light" };

const SLASH_MENU_FR = {
  heading: { title: "Titre 1", subtext: "Grand titre de section", aliases: ["h1", "titre", "titre1"], group: "Titres" },
  heading_2: { title: "Titre 2", subtext: "Titre de partie", aliases: ["h2", "titre2", "sous-titre"], group: "Titres" },
  heading_3: { title: "Titre 3", subtext: "Petit titre", aliases: ["h3", "titre3", "sous-titre"], group: "Titres" },
  bullet_list: {
    title: "Liste à puces",
    subtext: "Liste simple, sans ordre",
    aliases: ["ul", "liste", "puces", "liste a puces"],
    group: "Listes",
  },
  numbered_list: {
    title: "Liste numérotée",
    subtext: "Étapes dans l'ordre",
    aliases: ["ol", "liste", "numerotee", "liste numerotee"],
    group: "Listes",
  },
  check_list: {
    title: "Liste de tâches",
    subtext: "Cases à cocher",
    aliases: ["tache", "taches", "todo", "case", "cases a cocher", "checklist"],
    group: "Listes",
  },
  paragraph: { title: "Texte", subtext: "Paragraphe simple", aliases: ["p", "paragraphe", "texte"], group: "Blocs" },
  table: { title: "Tableau", subtext: "Lignes et colonnes", aliases: ["tableau", "table", "grille"], group: "Blocs" },
  code_block: { title: "Code", subtext: "Bloc de code", aliases: ["code", "pre", "bloc de code"], group: "Blocs" },
  image: {
    title: "Image",
    subtext: "Importer ou intégrer une image",
    aliases: ["image", "img", "photo", "capture"],
    group: "Médias",
  },
  video: { title: "Vidéo", subtext: "Importer ou intégrer une vidéo", aliases: ["video", "mp4", "film"], group: "Médias" },
  audio: { title: "Audio", subtext: "Importer ou intégrer un son", aliases: ["audio", "son", "mp3"], group: "Médias" },
  file: { title: "Fichier", subtext: "Importer un fichier", aliases: ["fichier", "piece jointe", "document"], group: "Médias" },
  emoji: { title: "Émoji", subtext: "Insérer un émoji", aliases: ["emoji", "smiley", "emoticone"], group: "Autres" },
};

const SLASH_ORDER = [
  "heading",
  "heading_2",
  "heading_3",
  "bullet_list",
  "numbered_list",
  "check_list",
  "paragraph",
  "table",
  "code_block",
  "image",
  "video",
  "audio",
  "file",
];

// Dictionnaire français de BlockNote : menu « / », barres d'outils et textes d'invite.
export function buildEditorDictionary(placeholder) {
  const fr = locales.fr;
  return {
    ...fr,
    slash_menu: { ...fr.slash_menu, ...SLASH_MENU_FR },
    placeholders: {
      ...fr.placeholders,
      default: typeof placeholder === "string" && placeholder.trim() ? placeholder : fr.placeholders.default,
      heading: "Titre",
      bulletListItem: "Liste",
      numberedListItem: "Liste",
      checkListItem: "Tâche",
    },
    formatting_toolbar: {
      ...fr.formatting_toolbar,
      underline: { ...fr.formatting_toolbar.underline, tooltip: "Souligné" },
      unnest: { ...fr.formatting_toolbar.unnest, tooltip: "Diminuer le retrait du bloc", secondary_tooltip: "Maj+Tab" },
    },
    file_panel: {
      ...fr.file_panel,
      upload: {
        ...fr.file_panel.upload,
        title: "Importer",
        file_placeholder: {
          image: "Importer une image",
          video: "Importer une vidéo",
          audio: "Importer un fichier audio",
          file: "Importer un fichier",
        },
        upload_error: "Erreur : l'envoi du fichier a échoué.",
      },
      embed: { ...fr.file_panel.embed, title: "Lien", url_placeholder: "Collez l'adresse (https://…)" },
    },
  };
}

/* ---------- Médias ---------- */

// URL affichable d'un média : les chemins /api/… et les anciennes URL https://api.loasis.app/… pointent
// vers le backend courant (production, préproduction ou aperçu). Les autres URL restent telles quelles.
export function resolveMediaUrl(url) {
  if (typeof url !== "string") return "";
  const trimmed = url.trim();
  if (trimmed.startsWith("/api/")) return `${BACKEND_ORIGIN}${trimmed}`;
  const legacy = trimmed.match(LEGACY_MEDIA_URL);
  if (legacy) return `${BACKEND_ORIGIN}${legacy[1]}`;
  return trimmed;
}

export const resolveFileUrl = async (url) => resolveMediaUrl(url);

function uploadErrorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (error?.response?.status === 413) return "Fichier trop volumineux (max 50 Mo).";
  return "L'envoi du fichier a échoué. Réessayez.";
}

// Applique les transactions de `action` hors de l'historique : Ctrl+Z ne ramène pas l'ancien contenu.
function withoutHistory(editor, action) {
  const dispatch = editor.dispatch;
  if (typeof dispatch !== "function") return action();
  const ownDispatch = Object.prototype.hasOwnProperty.call(editor, "dispatch");
  editor.dispatch = (tr) => dispatch.call(editor, tr.setMeta("addToHistory", false));
  try {
    return action();
  } finally {
    if (ownDispatch) editor.dispatch = dispatch;
    else delete editor.dispatch;
  }
}

function removeBlockQuietly(editor, blockId) {
  try {
    if (editor?.getBlock(blockId)) withoutHistory(editor, () => editor.removeBlocks([blockId]));
  } catch {
    // Bloc déjà retiré par l'utilisateur.
  }
}

// `blockId` n'est fourni que pour un collage ou un glisser-déposer ; le panneau « Importer » n'en donne pas.
async function uploadMedia({ uploadUrl, file, blockId, editor }) {
  const formData = new FormData();
  formData.append("file", file);
  try {
    const response = await api.post(uploadUrl || DEFAULT_UPLOAD_URL, formData);
    const stored = response?.data?.url;
    if (typeof stored !== "string" || !stored) throw new Error("Réponse d'envoi inattendue.");
    // URL relative enregistrée telle quelle dans le JSON ; resolveFileUrl la résout à l'affichage.
    return stored;
  } catch (error) {
    toast.error(uploadErrorMessage(error));
    // Panneau « Importer » : BlockNote affiche aussi son propre message.
    if (!blockId) throw error;
    // Collage ou dépôt : le bloc vide inséré par BlockNote est retiré, sans erreur non gérée.
    window.setTimeout(() => removeBlockQuietly(editor, blockId), 0);
    return { props: {} };
  }
}

/* ---------- Lecture du contenu enregistré ---------- */

const isBlockLike = (block) =>
  Boolean(block) && typeof block === "object" && !Array.isArray(block) && typeof block.type === "string";

export function textToBlocks(text) {
  return String(text ?? "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => ({
      type: "paragraph",
      content: line ? [{ type: "text", text: line, styles: {} }] : [],
    }));
}

function blocksFromArray(list) {
  if (list.length === 0) return { kind: "empty" };
  const blocks = list.filter(isBlockLike);
  return blocks.length ? { kind: "blocknote", blocks } : null;
}

// Contenu enregistré → { kind: "blocknote" | "html" | "text" | "empty", blocks?, html? }.
export function parseStoredContent(value) {
  if (Array.isArray(value)) return blocksFromArray(value) || { kind: "empty" };
  if (typeof value !== "string" || !value.trim()) return { kind: "empty" };
  const trimmed = value.trim();
  if (trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        const result = blocksFromArray(parsed);
        if (result) return result;
      }
    } catch {
      // Pas du JSON : ancien texte.
    }
  }
  if (trimmed.startsWith("<") && /<\/[a-zA-Z][a-zA-Z0-9-]*\s*>/.test(trimmed)) {
    return { kind: "html", html: value };
  }
  return { kind: "text", blocks: textToBlocks(value) };
}

/* ---------- Nettoyage (défense en profondeur, le serveur nettoie aussi) ---------- */

const isControlCode = (code) => code < 0x20 || (code >= 0x7f && code <= 0x9f);

// Comme le navigateur : espaces et caractères de contrôle ignorés avant de lire le schéma.
function compactUrl(text) {
  let out = "";
  for (const char of text) {
    const code = char.codePointAt(0);
    if (code !== 0x20 && !isControlCode(code)) out += char;
  }
  return out;
}

function hasControlChar(text) {
  for (let index = 0; index < text.length; index += 1) {
    const code = text.charCodeAt(index);
    if (code < 0x20 || code === 0x7f) return true;
  }
  return false;
}

function isSafeHref(href) {
  if (typeof href !== "string") return false;
  const compact = compactUrl(href);
  if (!compact) return false;
  const scheme = compact.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):/);
  return !scheme || SAFE_LINK_SCHEMES.has(scheme[1].toLowerCase());
}

function isSafeMediaUrl(url) {
  if (typeof url !== "string") return false;
  const trimmed = url.trim();
  if (hasControlChar(trimmed)) return false;
  return /^https:\/\//i.test(trimmed) || /^\/(?![/\\])/.test(trimmed);
}

// Types connus de l'éditeur ; sans schéma, aucun type n'est converti.
const schemaCache = new WeakMap();
function knownTypes(schema) {
  if (!schema || typeof schema !== "object") return null;
  if (!schemaCache.has(schema)) {
    schemaCache.set(schema, {
      blocks: new Set(Object.keys(schema.blockSchema || {})),
      inline: new Set(Object.keys(schema.inlineContentSchema || {})),
      styles: new Set(Object.keys(schema.styleSchema || {})),
    });
  }
  return schemaCache.get(schema);
}

function cleanStyles(styles, known) {
  if (!styles || typeof styles !== "object" || Array.isArray(styles)) return {};
  if (!known) return styles;
  return Object.fromEntries(Object.entries(styles).filter(([key]) => known.styles.has(key)));
}

function textItem(item, known) {
  return { ...item, type: "text", styles: cleanStyles(item.styles, known) };
}

function textItems(content, known) {
  if (typeof content === "string") return content ? [{ type: "text", text: content, styles: {} }] : [];
  if (!Array.isArray(content)) return [];
  return content
    .map((item) => (typeof item === "string" ? { type: "text", text: item, styles: {} } : item))
    .filter((item) => isBlockLike(item) && item.type === "text" && typeof item.text === "string")
    .map((item) => textItem(item, known));
}

function sanitizeInline(content, known) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return [];
  const out = [];
  content.forEach((item) => {
    if (typeof item === "string") {
      out.push(item);
      return;
    }
    if (!isBlockLike(item)) return;
    if (item.type === "link") {
      const inner = textItems(item.content, known);
      if (isSafeHref(item.href)) out.push({ ...item, href: item.href.trim(), content: inner });
      else out.push(...inner);
      return;
    }
    if (item.type === "text") {
      if (typeof item.text === "string") out.push(textItem(item, known));
      return;
    }
    // Contenu en ligne inconnu de l'éditeur : seul son texte est gardé.
    if (known && !known.inline.has(item.type)) {
      const text = typeof item.text === "string" ? item.text : inlineText(item.content, 1);
      if (text) out.push({ type: "text", text, styles: {} });
      return;
    }
    out.push(item);
  });
  return out;
}

// BlockNote 0.23 attend des cellules en listes d'éléments en ligne.
function sanitizeCell(cell, known) {
  if (Array.isArray(cell) || typeof cell === "string") return sanitizeInline(cell, known);
  if (cell && typeof cell === "object") return sanitizeInline(cell.content, known);
  return [];
}

function sanitizeTable(table, known) {
  const rows = Array.isArray(table.rows) ? table.rows : [];
  return {
    ...table,
    rows: rows
      .filter((row) => row && typeof row === "object" && !Array.isArray(row))
      .map((row) => ({
        ...row,
        cells: (Array.isArray(row.cells) ? row.cells : []).map((cell) => sanitizeCell(cell, known)),
      })),
  };
}

function tableLines(table) {
  const lines = [];
  collectLines([{ type: "table", content: table }], lines, 1);
  return lines.join("\n");
}

function sanitizeBlockList(blocks, depth, known) {
  if (!Array.isArray(blocks)) return [];
  const out = [];
  blocks.forEach((block) => {
    if (!isBlockLike(block)) return;
    const children = block.children === undefined ? undefined : depth < MAX_DEPTH ? sanitizeBlockList(block.children, depth + 1, known) : [];
    const { content } = block;
    // Bloc inconnu de l'éditeur : converti en paragraphe avec son texte.
    if (known && !known.blocks.has(block.type)) {
      const text =
        content && typeof content === "object" && !Array.isArray(content) && content.type === "tableContent"
          ? tableLines(content)
          : inlineText(content, depth);
      const paragraph = { type: "paragraph", content: text ? [{ type: "text", text, styles: {} }] : [] };
      if (typeof block.id === "string") paragraph.id = block.id;
      if (children) paragraph.children = children;
      out.push(paragraph);
      return;
    }
    const next = { ...block };
    if (Array.isArray(content) || typeof content === "string") next.content = sanitizeInline(content, known);
    else if (content && typeof content === "object" && content.type === "tableContent") next.content = sanitizeTable(content, known);
    else if (content !== undefined) delete next.content;
    if (MEDIA_TYPES.has(block.type) && block.props && typeof block.props === "object") {
      const { url } = block.props;
      if (typeof url === "string" && url && !isSafeMediaUrl(url)) next.props = { ...block.props, url: "" };
    }
    if (children) next.children = children;
    out.push(next);
  });
  return out;
}

// Liens limités à http, https, mailto et aux chemins ; médias en https ou chemin relatif.
// Avec le schéma d'un éditeur (`editor.schema`), les blocs, contenus et styles inconnus deviennent du texte.
export function sanitizeBlocks(blocks, schema) {
  return sanitizeBlockList(blocks, 1, knownTypes(schema));
}

const INERT_DROPPED_TAGS =
  "script, style, template, noscript, iframe, frame, frameset, object, embed, applet, link, meta, base, form, svg, math";
const INERT_URL_ATTRIBUTES = new Set(["src", "poster", "background", "lowsrc", "dynsrc"]);
const INERT_DROPPED_ATTRIBUTES = new Set(["srcset", "style", "action", "formaction", "ping", "xlink:href"]);

// Ancien HTML rendu inerte avant d'être confié à BlockNote : lu par DOMParser (document sans fenêtre, rien
// n'est exécuté ni chargé), puis débarrassé des gestionnaires d'événements et des URL douteuses.
export function inertHtml(html) {
  try {
    const doc = new DOMParser().parseFromString(String(html ?? ""), "text/html");
    doc.querySelectorAll(INERT_DROPPED_TAGS).forEach((node) => node.remove());
    doc.body.querySelectorAll("*").forEach((element) => {
      Array.from(element.attributes).forEach(({ name, value }) => {
        const key = name.toLowerCase();
        const unsafe =
          key.startsWith("on") ||
          INERT_DROPPED_ATTRIBUTES.has(key) ||
          (key === "href" && !isSafeHref(value)) ||
          (INERT_URL_ATTRIBUTES.has(key) && !isSafeMediaUrl(value));
        if (unsafe) element.removeAttribute(name);
      });
    });
    return doc.body.innerHTML;
  } catch {
    return "";
  }
}

/* ---------- Texte brut et statistiques ---------- */

function inlineText(content, depth) {
  if (depth > MAX_DEPTH) return "";
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return "";
      if (item.type === "link") return inlineText(item.content, depth + 1);
      return typeof item.text === "string" ? item.text : "";
    })
    .join("");
}

function collectLines(blocks, lines, depth) {
  if (!Array.isArray(blocks) || depth > MAX_DEPTH) return;
  blocks.forEach((block) => {
    if (!block || typeof block !== "object") return;
    const { content } = block;
    if (content && typeof content === "object" && !Array.isArray(content)) {
      if (content.type === "tableContent") {
        (Array.isArray(content.rows) ? content.rows : []).forEach((row) => {
          (Array.isArray(row?.cells) ? row.cells : []).forEach((cell) => {
            const text = Array.isArray(cell) || typeof cell === "string" ? inlineText(cell, depth) : inlineText(cell?.content, depth);
            if (text.trim()) lines.push(text);
          });
        });
      }
    } else {
      const text = inlineText(content, depth);
      if (text.trim()) lines.push(text);
    }
    collectLines(block.children, lines, depth + 1);
  });
}

// Même parcours que le serveur : texte en ligne des blocs, liens et cellules de tableau, une ligne chacun.
export function blocksToPlainText(blocks) {
  const lines = [];
  collectLines(blocks, lines, 1);
  return lines.join("\n");
}

export function htmlToPlainText(html) {
  const marked = String(html ?? "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6]|tr|blockquote|pre|ul|ol|table)\s*>/gi, (tag) => `${tag}\n`);
  let text = "";
  try {
    // Document inerte : ni script exécuté, ni image chargée.
    const doc = new DOMParser().parseFromString(marked, "text/html");
    doc.querySelectorAll("script, style, template, noscript").forEach((node) => node.remove());
    text = doc.body ? doc.body.textContent || "" : "";
  } catch {
    text = marked.replace(/<[^>]*>/g, "");
  }
  return text
    .split("\n")
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n");
}

export function contentToPlainText(value) {
  const parsed = parseStoredContent(value);
  if (parsed.kind === "blocknote") return blocksToPlainText(parsed.blocks);
  if (parsed.kind === "html") return htmlToPlainText(parsed.html);
  if (parsed.kind === "text") return String(value).replace(/\r\n?/g, "\n");
  return "";
}

// Même règle que le `word_count` du serveur : nombre de suites de caractères non blancs.
export function countWords(text) {
  return (String(text ?? "").match(/\S+/g) || []).length;
}

// 200 mots par minute, une minute au minimum.
export function readingMinutes(words) {
  return Math.max(1, Math.ceil((Number(words) || 0) / 200));
}

export function contentStats(blocks) {
  const text = blocksToPlainText(blocks);
  return { words: countWords(text), characters: text.replace(/\n/g, "").length };
}

function hasMedia(blocks, depth) {
  if (!Array.isArray(blocks) || depth > MAX_DEPTH) return false;
  return blocks.some((block) => {
    if (!isBlockLike(block)) return false;
    const url = block.props?.url;
    if (MEDIA_TYPES.has(block.type) && typeof url === "string" && url.trim()) return true;
    return hasMedia(block.children, depth + 1);
  });
}

// Faux pour un document sans texte ni média (paragraphes vides, par exemple).
export function hasVisibleContent(blocks) {
  return Boolean(blocksToPlainText(blocks).trim()) || hasMedia(blocks, 1);
}

/* ---------- Chargement dans BlockNote ---------- */

function replaceDocument(editor, blocks) {
  try {
    withoutHistory(editor, () => editor.replaceBlocks(editor.document, blocks.length ? blocks : [{ type: "paragraph" }]));
    return true;
  } catch (error) {
    console.warn("Contenu refusé par l'éditeur :", error);
    return false;
  }
}

// Charge des blocs nettoyés ; s'ils sont refusés, leur texte brut. Renvoie false si rien n'a pu être chargé.
export function loadBlocksIntoEditor(editor, blocks) {
  if (replaceDocument(editor, sanitizeBlocks(blocks, editor.schema))) return true;
  return replaceDocument(editor, textToBlocks(blocksToPlainText(blocks)));
}

// Contenu analysé par parseStoredContent, sauf le HTML (asynchrone : convertHtmlToBlocks).
export function loadStoredContent(editor, parsed) {
  if (!parsed || parsed.kind === "empty") return replaceDocument(editor, []);
  if (parsed.kind === "html") return loadBlocksIntoEditor(editor, textToBlocks(htmlToPlainText(parsed.html)));
  return loadBlocksIntoEditor(editor, parsed.blocks);
}

// Ancien HTML → blocs, après passage par inertHtml ; repli sur le texte brut.
export async function convertHtmlToBlocks(editor, html) {
  const safe = inertHtml(html);
  if (safe.trim()) {
    try {
      const blocks = await editor.tryParseHTMLToBlocks(safe);
      if (Array.isArray(blocks) && blocks.length) return blocks;
    } catch {
      // Repli sur le texte brut ci-dessous.
    }
  }
  return textToBlocks(htmlToPlainText(html));
}

const isEmptyParagraph = (block) =>
  block?.type === "paragraph" &&
  (!Array.isArray(block.content) || block.content.length === 0) &&
  (!Array.isArray(block.children) || block.children.length === 0);

// Signature (sans les paragraphes vides de fin, ajoutés par BlockNote) et JSON complet envoyé à onChange.
function serializeDocument(blocks) {
  let end = blocks.length;
  while (end > 0 && isEmptyParagraph(blocks[end - 1])) end -= 1;
  const signature = JSON.stringify(end === blocks.length ? blocks : blocks.slice(0, end));
  if (end === blocks.length) return { signature, json: signature };
  const tail = JSON.stringify(blocks.slice(end));
  return { signature, json: end > 0 ? `${signature.slice(0, -1)},${tail.slice(1)}` : tail };
}

function focusAtEnd(editor) {
  if (!editor.prosemirrorView || !editor.isEditable) return;
  try {
    const blocks = editor.document;
    const last = blocks[blocks.length - 1];
    if (last) editor.setTextCursorPosition(last, "end");
  } catch {
    // Bloc sans texte : position par défaut.
  }
  editor.focus();
}

const cssString = (text) => `"${String(text ?? "").replace(/[\\"]/g, "\\$&").replace(/[\r\n\t]+/g, " ")}"`;

/* ---------- Menu « / » ---------- */

const fold = (text) =>
  String(text ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();

// Recherche insensible aux accents (« decision » trouve « Décision »).
function filterSlashItems(items, query) {
  const needle = fold(query).trim();
  if (!needle) return items;
  return items.filter(
    ({ title, aliases }) => fold(title).includes(needle) || (aliases || []).some((alias) => fold(alias).includes(needle)),
  );
}

// « 27 octobre 2026 », « 1er novembre 2026 » (date de Paris).
export function todayLabel(date = new Date()) {
  const options = { day: "numeric", month: "long", year: "numeric" };
  let parts;
  try {
    parts = new Intl.DateTimeFormat("fr-FR", { ...options, timeZone: "Europe/Paris" }).formatToParts(date);
  } catch {
    parts = new Intl.DateTimeFormat("fr-FR", options).formatToParts(date);
  }
  const part = (type) => parts.find((item) => item.type === type)?.value || "";
  const day = part("day");
  return `${day === "1" ? "1er" : day} ${part("month")} ${part("year")}`;
}

function insertDecision(editor) {
  const block = insertOrUpdateBlock(editor, {
    type: "paragraph",
    content: [
      { type: "text", text: "Décision :", styles: { bold: true } },
      { type: "text", text: " ", styles: {} },
    ],
  });
  try {
    editor.setTextCursorPosition(block, "end");
  } catch {
    // Curseur laissé où BlockNote l'a placé.
  }
}

function meetingSlashItems(editor) {
  const today = todayLabel();
  return [
    {
      title: "Date du jour",
      subtext: `Insère « ${today} »`,
      aliases: ["date", "aujourd'hui", "aujourdhui", "jour"],
      group: "Réunion",
      icon: <CalendarDays size={18} aria-hidden="true" />,
      onItemClick: () => editor.insertInlineContent([{ type: "text", text: today, styles: {} }]),
    },
    {
      title: "Décision",
      subtext: "Paragraphe « Décision : … »",
      aliases: ["decision", "decide", "vote"],
      group: "Réunion",
      icon: <Gavel size={18} aria-hidden="true" />,
      onItemClick: () => insertDecision(editor),
    },
    {
      title: "Action",
      subtext: "Case à cocher pour une action à suivre",
      aliases: ["action", "tache", "todo", "suivi", "a faire"],
      group: "Réunion",
      icon: <SquareCheckBig size={18} aria-hidden="true" />,
      onItemClick: () => insertOrUpdateBlock(editor, { type: "checkListItem" }),
    },
  ];
}

function buildSlashItems(editor, { allowFiles, extraSlashItems }) {
  const byKey = new Map(getDefaultReactSlashMenuItems(editor).map((item) => [item.key, item]));
  const items = SLASH_ORDER.filter((key) => key !== "file" || allowFiles)
    .map((key) => byKey.get(key))
    .filter(Boolean);
  if (extraSlashItems) items.push(...meetingSlashItems(editor));
  if (byKey.has("emoji")) items.push(byKey.get("emoji"));
  return items;
}

export function EditorSkeleton() {
  return (
    <div className="iris-editor-skeleton" role="status" aria-label="Chargement du contenu…">
      <span />
      <span />
      <span />
    </div>
  );
}

export default function TiptapSummaryEditor({
  value,
  onChange,
  placeholder = "Rédiger le résumé…",
  uploadUrl = DEFAULT_UPLOAD_URL,
  variant = "default",
  autoFocus = false,
  editable = true,
  resetKey,
  onStats,
  onEditorReady,
  extraSlashItems = false,
  allowFiles = false,
}) {
  const latest = useRef({ value, onChange, onStats, onEditorReady, uploadUrl, autoFocus, editor: null });

  const editor = useCreateBlockNote(
    {
      dictionary: buildEditorDictionary(placeholder),
      uploadFile: (file, blockId) =>
        uploadMedia({ uploadUrl: latest.current.uploadUrl, file, blockId, editor: latest.current.editor }),
      resolveFileUrl,
    },
    [],
  );

  useLayoutEffect(() => {
    latest.current = { value, onChange, onStats, onEditorReady, uploadUrl, autoFocus, editor };
  });

  // L'ancien HTML se convertit de façon asynchrone : squelette affiché tant que le contenu n'est pas chargé.
  const [htmlPending, setHtmlPending] = useState(() => parseStoredContent(value).kind === "html");
  const loadingRef = useRef(false);
  const signatureRef = useRef(null);

  const runLoad = useCallback(
    (load) => {
      loadingRef.current = true;
      try {
        load();
      } finally {
        loadingRef.current = false;
      }
      const blocks = editor.document;
      signatureRef.current = serializeDocument(blocks).signature;
      const handler = latest.current.onStats;
      if (typeof handler === "function") handler(contentStats(blocks));
    },
    [editor],
  );

  // Chargement au montage puis à chaque changement de resetKey, sans jamais appeler onChange.
  useLayoutEffect(() => {
    const parsed = parseStoredContent(latest.current.value);
    if (parsed.kind !== "html") {
      runLoad(() => loadStoredContent(editor, parsed));
      setHtmlPending(false);
      return undefined;
    }
    let cancelled = false;
    setHtmlPending(true);
    convertHtmlToBlocks(editor, parsed.html).then((blocks) => {
      if (cancelled) return;
      runLoad(() => loadBlocksIntoEditor(editor, blocks));
      setHtmlPending(false);
    });
    return () => {
      cancelled = true;
    };
  }, [editor, resetKey, runLoad]);

  useEffect(() => {
    const handler = latest.current.onEditorReady;
    if (typeof handler === "function") handler(editor);
  }, [editor]);

  useEffect(() => {
    if (htmlPending || !latest.current.autoFocus) return undefined;
    // La vue ProseMirror est créée juste après le montage : on attend le tour suivant.
    const timer = window.setTimeout(() => focusAtEnd(editor), 0);
    return () => window.clearTimeout(timer);
  }, [editor, htmlPending]);

  const handleChange = useCallback(() => {
    if (loadingRef.current) return;
    const blocks = editor.document;
    const { signature, json } = serializeDocument(blocks);
    if (signature === signatureRef.current) return;
    signatureRef.current = signature;
    const { onChange: changeHandler, onStats: statsHandler } = latest.current;
    if (typeof changeHandler === "function") changeHandler(json);
    if (typeof statsHandler === "function") statsHandler(contentStats(blocks));
  }, [editor]);

  const getItems = useCallback(
    async (query) => filterSlashItems(buildSlashItems(editor, { allowFiles, extraSlashItems }), query),
    [editor, allowFiles, extraSlashItems],
  );

  const safeVariant = VARIANTS.has(variant) ? variant : "default";
  const className = [
    "tiptap-editor",
    "iris-editor",
    `iris-editor--${safeVariant}`,
    editable ? "" : "iris-editor--locked",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      className={className}
      style={{ "--iris-editor-placeholder": cssString(placeholder) }}
      aria-busy={htmlPending || undefined}
    >
      {htmlPending && <EditorSkeleton />}
      <BlockNoteContext.Provider value={IRIS_COLOR_SCHEME}>
        <BlockNoteView
          editor={editor}
          theme={IRIS_EDITOR_THEME}
          editable={editable}
          formattingToolbar={false}
          linkToolbar={false}
          slashMenu={false}
          filePanel={false}
          onChange={handleChange}
          style={htmlPending ? { display: "none" } : undefined}
        >
          <FormattingToolbarController floatingOptions={FLOATING_OPTIONS} />
          <LinkToolbarController floatingOptions={FLOATING_OPTIONS} />
          <SuggestionMenuController triggerCharacter="/" getItems={getItems} floatingOptions={FLOATING_OPTIONS} />
          {editor.filePanel && <FilePanelController floatingOptions={FLOATING_OPTIONS} />}
        </BlockNoteView>
      </BlockNoteContext.Provider>
    </div>
  );
}

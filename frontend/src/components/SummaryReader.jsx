import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { BlockNoteContext, useCreateBlockNote } from "@blocknote/react";
import { BlockNoteView } from "@blocknote/mantine";
import "@blocknote/mantine/style.css";
import "./editor-theme.css";
import {
  EditorSkeleton,
  IRIS_COLOR_SCHEME,
  IRIS_EDITOR_THEME,
  buildEditorDictionary,
  convertHtmlToBlocks,
  hasVisibleContent,
  loadBlocksIntoEditor,
  loadStoredContent,
  parseStoredContent,
  resolveFileUrl,
  sanitizeBlocks,
} from "./TiptapSummaryEditor";

// Lecture seule tolérante : JSON BlockNote, ancien HTML ou texte brut ; suit les changements de `content`.
export default function SummaryReader({
  content,
  emptyLabel = "Aucun résumé rédigé pour le moment.",
  onEditorReady,
  className = "",
}) {
  const parsed = useMemo(() => parseStoredContent(content), [content]);
  const editor = useCreateBlockNote({ dictionary: buildEditorDictionary(), resolveFileUrl }, []);

  // Dernier HTML converti : { html, empty }. Tant qu'il ne correspond pas au contenu, le squelette s'affiche.
  const [loadedHtml, setLoadedHtml] = useState(null);
  const htmlPending = parsed.kind === "html" && loadedHtml?.html !== parsed.html;

  const onReadyRef = useRef(onEditorReady);
  useLayoutEffect(() => {
    onReadyRef.current = onEditorReady;
  });

  useLayoutEffect(() => {
    if (parsed.kind === "empty") return undefined;
    if (parsed.kind !== "html") {
      loadStoredContent(editor, parsed);
      setLoadedHtml(null);
      return undefined;
    }
    let cancelled = false;
    convertHtmlToBlocks(editor, parsed.html).then((blocks) => {
      if (cancelled) return;
      loadBlocksIntoEditor(editor, blocks);
      setLoadedHtml({ html: parsed.html, empty: !hasVisibleContent(editor.document) });
    });
    return () => {
      cancelled = true;
    };
  }, [editor, parsed]);

  useEffect(() => {
    const handler = onReadyRef.current;
    if (typeof handler === "function") handler(editor);
  }, [editor]);

  // Vide aussi quand il ne reste rien après nettoyage (paragraphes vides, média à l'adresse refusée).
  const isEmpty = useMemo(() => {
    if (parsed.kind === "empty") return true;
    if (parsed.kind === "html") return false;
    return !hasVisibleContent(sanitizeBlocks(parsed.blocks));
  }, [parsed]);

  if (isEmpty || (parsed.kind === "html" && !htmlPending && loadedHtml?.empty)) {
    return emptyLabel ? <p className="dashboard-empty">{emptyLabel}</p> : null;
  }

  const classes = ["tiptap-editor", "tiptap-readonly", "iris-editor", "iris-editor--readonly", className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} aria-busy={htmlPending || undefined}>
      {htmlPending && <EditorSkeleton />}
      <BlockNoteContext.Provider value={IRIS_COLOR_SCHEME}>
        <BlockNoteView
          editor={editor}
          theme={IRIS_EDITOR_THEME}
          editable={false}
          style={htmlPending ? { display: "none" } : undefined}
        />
      </BlockNoteContext.Provider>
    </div>
  );
}

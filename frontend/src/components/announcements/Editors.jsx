import { useRef } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Field } from '../projects/ProjectUI';
import { BLOCK_LABELS, linkButton, media } from './document';
export function MarkdownField({
  label,
  value,
  onChange,
  catalogue
}) {
  const ref = useRef(null);
  const insert = (before, after = '', placeholder = 'texte') => {
    const el = ref.current;
    const start = el?.selectionStart || 0,
      end = el?.selectionEnd || start;
    const selected = value.slice(start, end) || placeholder;
    onChange(value.slice(0, start) + before + selected + after + value.slice(end));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + before.length, start + before.length + selected.length);
    });
  };
  return <div className="an-markdown-field"><label>{label}</label><div className="an-format-toolbar">{[['Gras', '**', '**'], ['Italique', '*', '*'], ['Souligné', '__', '__'], ['Barré', '~~', '~~'], ['Code', '`', '`'], ['Spoiler', '||', '||'], ['Titre', '## ', ''], ['Liste', '- ', ''], ['Citation', '> ', ''], ['Petit texte', '-# ', ''], ['Lien', '[', '](https://exemple.fr)']].map(([title, a, b]) => <button type="button" key={title} onMouseDown={e => e.preventDefault()} onClick={() => insert(a, b)}>{title}</button>)}</div><textarea ref={ref} aria-label={label} value={value} maxLength={4000} rows={7} onChange={e => onChange(e.target.value)} /><div className="an-insert-row"><select aria-label={`Insérer un rôle dans ${label}`} value="" onChange={e => {
        if (e.target.value) insert(`<@&${e.target.value}>`, '', '');
      }}><option value="">Insérer un rôle…</option>{catalogue.roles.map(role => <option key={role.id} value={role.id}>{role.name}</option>)}</select><select aria-label={`Insérer un salon dans ${label}`} value="" onChange={e => {
        if (e.target.value) insert(`<#${e.target.value}>`, '', '');
      }}><option value="">Insérer un salon…</option>{catalogue.channels.map(channel => <option key={channel.id} value={channel.id}>#{channel.name}</option>)}</select><span>{value.length} caractères</span></div><small className="an-help">Les mentions insérées ici ne notifieront que les destinataires autorisés dans Distribution.</small></div>;
}
function Check({
  label,
  value,
  onChange
}) {
  return <label className="an-check"><input type="checkbox" checked={value} onChange={e => onChange(e.target.checked)} />{label}</label>;
}
export function MediaEditor({
  value,
  onChange,
  assets,
  thumbnail = false
}) {
  const options = Object.values(assets).filter(a => a.content_type.startsWith('image/') || !thumbnail && a.content_type.startsWith('video/'));
  return <div className="an-fields"><Field label="Média de la bibliothèque"><select value={value.asset_id || ''} onChange={e => onChange({
        ...value,
        asset_id: e.target.value || null,
        url: ''
      })}><option value="">Utiliser une URL externe</option>{options.map(asset => <option key={asset.id} value={asset.id}>{asset.original_filename}</option>)}</select></Field>{!value.asset_id && <Field label="URL HTTPS du média"><input type="url" value={value.url} maxLength={2048} onChange={e => onChange({
        ...value,
        url: e.target.value,
        asset_id: null
      })} placeholder="https://…" /></Field>}{!value.asset_id && /^https:\/\/(?:cdn|media)\.discordapp\.(?:com|net)\/attachments\//i.test(value.url) && <p className="an-help">Ce lien de pièce jointe Discord est temporaire. Pour une annonce durable ou programmée, ajoutez l’image dans Fichiers puis sélectionnez-la dans la bibliothèque.</p>}<Field label="Description alternative"><input value={value.description} maxLength={1024} onChange={e => onChange({
        ...value,
        description: e.target.value
      })} placeholder="Décrivez l’image pour les lecteurs d’écran" /></Field><Check label="Masquer comme spoiler" value={value.spoiler} onChange={spoiler => onChange({
      ...value,
      spoiler
    })} /></div>;
}
export function ButtonEditor({
  value,
  onChange
}) {
  return <div className="an-fields"><Field label="Libellé du bouton"><input maxLength={80} value={value.label} onChange={e => onChange({
        ...value,
        label: e.target.value
      })} /></Field><Field label="Lien HTTP ou HTTPS"><input type="url" maxLength={512} value={value.url} onChange={e => onChange({
        ...value,
        url: e.target.value
      })} /></Field><Field label="Emoji facultatif"><input value={value.emoji} maxLength={64} onChange={e => onChange({
        ...value,
        emoji: e.target.value
      })} placeholder="🌿 ou <:nom:identifiant>" /></Field><Check label="Bouton désactivé" value={value.disabled} onChange={disabled => onChange({
      ...value,
      disabled
    })} /></div>;
}
export default function BlockEditor({
  block,
  onChange,
  catalogue,
  assets
}) {
  const change = (key, value) => onChange({
    ...block,
    [key]: value
  });
  return <section className="an-inspector"><header><p className="cz-eyebrow">BLOC SÉLECTIONNÉ</p><h3>{BLOCK_LABELS[block.kind]}</h3></header><div className="an-inspector-body">{block.kind === 'text' ? <MarkdownField label="Texte du bloc" value={block.text} onChange={text => change('text', text)} catalogue={catalogue} /> : block.kind === 'section' ? <>
    {block.texts.map((text, index) => <div className="an-section-text" key={index}><MarkdownField label={`Texte de section ${index + 1}`} value={text} onChange={text => change('texts', block.texts.map((t, i) => i === index ? text : t))} catalogue={catalogue} />{block.texts.length > 1 && <button className="an-button an-danger" onClick={() => change('texts', block.texts.filter((_, i) => i !== index))}>Retirer ce texte</button>}</div>)}<button className="an-button" disabled={block.texts.length >= 3} onClick={() => change('texts', [...block.texts, 'Texte complémentaire.'])}><Plus size={15} /> Ajouter un texte à la section</button>
    <Field label="Accessoire de la section"><select value={block.accessory} onChange={e => change('accessory', e.target.value)}><option value="thumbnail">Vignette</option><option value="button">Bouton de lien</option></select></Field>{block.accessory === 'thumbnail' ? <MediaEditor value={block.thumbnail} onChange={v => change('thumbnail', v)} assets={assets} thumbnail /> : <ButtonEditor value={block.button} onChange={v => change('button', v)} />}</> : block.kind === 'gallery' ? <>
      <p className="an-help">Une galerie contient jusqu’à dix images ou vidéos. Ajoutez vos fichiers dans l’onglet Fichiers.</p>{block.items.map((item, index) => <div key={index} className="an-sub-editor"><header><strong>Média {index + 1}</strong><button className="an-icon an-danger" aria-label={`Retirer le média ${index + 1}`} onClick={() => change('items', block.items.filter((_, i) => i !== index))}><Trash2 size={15} /></button></header><MediaEditor value={item} onChange={v => change('items', block.items.map((m, i) => i === index ? v : m))} assets={assets} /></div>)}<button className="an-button" disabled={block.items.length >= 10} onClick={() => change('items', [...block.items, media()])}><Plus size={15} /> Ajouter un média</button></> : block.kind === 'buttons' ? <>
      <p className="an-help">Jusqu’à cinq boutons de lien par ligne. Les boutons d’action nécessitant un traitement par le bot ne sont pas proposés.</p>{block.buttons.map((btn, index) => <div className="an-sub-editor" key={index}><header><strong>Bouton {index + 1}</strong><button className="an-icon an-danger" aria-label={`Retirer le bouton ${index + 1}`} onClick={() => change('buttons', block.buttons.filter((_, i) => i !== index))}><Trash2 size={15} /></button></header><ButtonEditor value={btn} onChange={v => change('buttons', block.buttons.map((b, i) => i === index ? v : b))} /></div>)}<button className="an-button" disabled={block.buttons.length >= 5} onClick={() => change('buttons', [...block.buttons, linkButton()])}><Plus size={15} /> Ajouter un bouton</button></> : block.kind === 'separator' ? <div className="an-fields"><Check label="Afficher le trait de séparation" value={block.divider} onChange={v => change('divider', v)} /><Field label="Espacement"><select value={block.spacing} onChange={e => change('spacing', Number(e.target.value))}><option value={1}>Compact</option><option value={2}>Aéré</option></select></Field></div> : <div className="an-fields"><p className="an-help">Le fichier doit être téléversé dans la bibliothèque. Il sera joint au message Discord.</p><Field label="Fichier à joindre"><select value={block.file_asset_id || ''} onChange={e => change('file_asset_id', e.target.value || null)}><option value="">Choisir un fichier…</option>{Object.values(assets).map(asset => <option key={asset.id} value={asset.id}>{asset.original_filename}</option>)}</select></Field><Check label="Fichier marqué comme spoiler" value={block.spoiler} onChange={v => change('spoiler', v)} /></div>}</div></section>;
}

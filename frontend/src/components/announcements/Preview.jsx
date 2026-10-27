import { useState } from 'react';
import { FileText, ExternalLink } from 'lucide-react';
import { assetUrl, safeUrl } from './document';
function Inline({
  text,
  catalogue
}) {
  const tokens = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|__[^_]+__|~~[^~]+~~|\|\|[^|]+\|\||`[^`]+`|\[[^\]]+\]\(https?:\/\/[^\s)]+\)|<@&?\d+>|<#\d+>)/g);
  return tokens.map((t, i) => {
    if (t.startsWith('**')) return <strong key={i}>{t.slice(2, -2)}</strong>;
    if (t.startsWith('*')) return <em key={i}>{t.slice(1, -1)}</em>;
    if (t.startsWith('__')) return <u key={i}>{t.slice(2, -2)}</u>;
    if (t.startsWith('~~')) return <del key={i}>{t.slice(2, -2)}</del>;
    if (t.startsWith('`')) return <code key={i}>{t.slice(1, -1)}</code>;
    if (t.startsWith('||')) return <details key={i} className="an-inline-spoiler"><summary>Spoiler</summary>{t.slice(2, -2)}</details>;
    const link = t.match(/^\[(.+)\]\((.+)\)$/);
    if (link && safeUrl(link[2])) return <a key={i} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    if (/^<[@#]/.test(t)) {
      const id = t.replace(/\D/g, '');
      const entry = t.startsWith('<#') ? catalogue.channels?.find(c => c.id === id) : catalogue.roles?.find(r => r.id === id);
      return <span key={i} className="an-mention">{t.startsWith('<#') ? '#' : '@'}{entry?.name || id}</span>;
    }
    return t;
  });
}
export function Markdown({
  text = '',
  catalogue
}) {
  return <div className="an-markdown">{text.split('\n').map((line, i) => {
      const heading = line.match(/^(#{1,3}) (.*)$/);
      const content = <Inline text={heading ? heading[2] : line.replace(/^(-# |>|- |\d+\. )/, '')} catalogue={catalogue} />;
      if (heading) {
        const Tag = `h${Number(heading[1].length) + 1}`;
        return <Tag key={i}>{content}</Tag>;
      }
      if (line.startsWith('-# ')) return <small key={i}>{content}</small>;
      if (line.startsWith('>')) return <blockquote key={i}>{content}</blockquote>;
      if (/^(- |\d+\. )/.test(line)) return <div key={i} className="an-bullet">• {content}</div>;
      return <p key={i}>{line ? content : <br />}</p>;
    })}</div>;
}
function MediaPreview({
  media,
  assets,
  base,
  thumb = false
}) {
  const [revealed, setRevealed] = useState(false);
  const asset = assets[media.asset_id];
  const source = asset ? assetUrl(base, asset.id) : safeUrl(media.url, true) ? media.url : null;
  if (!source) return <div className="an-media-placeholder">{thumb ? 'Vignette' : 'Média à choisir'}</div>;
  return <div className={`an-preview-media ${thumb ? 'is-thumbnail' : ''} ${media.spoiler && !revealed ? 'is-spoiler' : ''}`}>
  {asset?.content_type.startsWith('video/') ? <video controls preload="none" src={source} /> : <img src={source} alt={media.description || ''} loading="lazy" referrerPolicy="no-referrer" />}{media.spoiler && !revealed && <button type="button" onClick={() => setRevealed(true)}>Afficher le média</button>}</div>;
}
function ButtonPreview({
  button
}) {
  return <a className={`an-discord-button ${button.disabled ? 'is-disabled' : ''}`} href={!button.disabled && safeUrl(button.url) ? button.url : undefined} target="_blank" rel="noreferrer">{button.emoji && !button.emoji.startsWith('<') ? `${button.emoji} ` : ''}{button.label || 'Bouton'} <ExternalLink size={13} /></a>;
}
export default function Preview({
  document,
  assets,
  catalogue,
  base,
  theme
}) {
  return <div className={`an-discord-preview ${theme === 'light' ? 'is-light' : ''}`}><div className="an-preview-author"><span>🌿</span><strong>Iris</strong><b>APP</b><small>Aperçu</small></div><div className="an-preview-message">{document.groups.map(group => <div key={group.id} className={`${group.boxed ? 'an-preview-container' : 'an-preview-unboxed'} ${group.spoiler ? 'is-container-spoiler' : ''}`} style={group.boxed && group.color ? {
        borderLeftColor: group.color
      } : undefined}>
    {group.spoiler && <span className="an-spoiler-note">Panneau marqué comme spoiler</span>}{group.blocks.map(b => <div key={b.id} className="an-preview-block">{b.kind === 'text' ? <Markdown text={b.text} catalogue={catalogue} /> : b.kind === 'section' ? <div className="an-preview-section"><div>{b.texts.map((text, i) => <Markdown key={i} text={text} catalogue={catalogue} />)}</div>{b.accessory === 'thumbnail' ? <MediaPreview media={b.thumbnail} assets={assets} base={base} thumb /> : <ButtonPreview button={b.button} />}</div> : b.kind === 'gallery' ? <div className="an-preview-gallery">{b.items.map((m, i) => <MediaPreview key={i} media={m} assets={assets} base={base} />)}</div> : b.kind === 'separator' ? <div className={`an-preview-separator ${b.spacing === 2 ? 'is-large' : ''}`}>{b.divider && <hr />}</div> : b.kind === 'buttons' ? <div className="an-preview-buttons">{b.buttons.map((btn, i) => <ButtonPreview key={i} button={btn} />)}</div> : <div className="an-preview-file"><FileText size={23} /><span>{assets[b.file_asset_id]?.original_filename || 'Fichier à choisir'}</span>{b.spoiler && <small>Spoiler</small>}</div>}</div>)}
  </div>)}</div></div>;
}

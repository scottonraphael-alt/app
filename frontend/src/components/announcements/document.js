export const uid = () => globalThis.crypto?.randomUUID?.() || `ann-${Date.now()}-${Math.random().toString(36).slice(2)}`;
export const media = () => ({
  url: '',
  asset_id: null,
  description: '',
  spoiler: false
});
export const linkButton = () => ({
  label: 'En savoir plus',
  url: '',
  emoji: '',
  disabled: false
});
export const BLOCK_LABELS = {
  text: 'Texte Markdown',
  section: 'Texte + accessoire',
  gallery: 'Galerie de médias',
  separator: 'Séparateur',
  buttons: 'Boutons de lien',
  file: 'Fichier joint'
};
export function newBlock(kind = 'text') {
  return {
    id: uid(),
    kind,
    text: 'Votre message ici.',
    texts: ['Un point à mettre en avant.'],
    accessory: 'thumbnail',
    thumbnail: media(),
    button: linkButton(),
    items: kind === 'gallery' ? [media()] : [],
    buttons: kind === 'buttons' ? [linkButton()] : [],
    divider: true,
    spacing: 1,
    file_asset_id: null,
    spoiler: false
  };
}
export const newGroup = () => ({
  id: uid(),
  name: 'Panneau',
  boxed: true,
  color: '#78618c',
  spoiler: false,
  blocks: [newBlock()]
});
export function newDocument(preset = 'simple') {
  const group = newGroup();
  group.blocks[0].text = preset === 'event' ? '# Une nouvelle animation 🌿\nRendez-vous pour un moment ensemble !' : preset === 'maintenance' ? '# Informations importantes\nVoici les changements à connaître.' : '# Une nouvelle annonce\nPartagez l’essentiel avec la communauté.';
  if (preset === 'event') group.blocks.push({
    ...newBlock('text'),
    text: '## Au programme\n- Date et heure : à préciser\n- Salon : à préciser\n- Comment participer : à compléter'
  });
  if (preset === 'maintenance') group.blocks.push(newBlock('separator'), {
    ...newBlock(),
    text: '## Ce qui change\n- Premier point\n- Deuxième point\n\nMerci pour votre compréhension.'
  });
  return {
    schema_version: 1,
    groups: [group],
    mentions: {
      roles: [],
      users: [],
      everyone: false
    },
    silent: false
  };
}
export function cloneDocument(document) {
  const copy = JSON.parse(JSON.stringify(document));
  copy.groups.forEach(g => {
    g.id = uid();
    g.blocks.forEach(b => {
      b.id = uid();
    });
  });
  return copy;
}
export function blockTitle(block) {
  return (block.kind === 'text' ? block.text : block.kind === 'section' ? block.texts?.[0] : BLOCK_LABELS[block.kind])?.replace(/[#*_`~]/g, '').trim().split('\n')[0].slice(0, 65) || BLOCK_LABELS[block.kind];
}
export function safeUrl(value, mediaOnly = false) {
  try {
    const u = new URL(value);
    if (!(mediaOnly ? ['https:'] : ['https:', 'http:']).includes(u.protocol) || u.username || u.password) return false;
    return !/^(localhost|127\.|10\.|192\.168\.|0\.|\[?::1\]?)/i.test(u.hostname) && !u.hostname.endsWith('.local');
  } catch {
    return false;
  }
}
export const assetUrl = (base, id) => `${base}/responsable/annonces/assets/${encodeURIComponent(id)}/download`;
export function compileDocument(doc, assetMap = {}) {
  let count = 0,
    textCount = 0;
  const errors = [],
    used = new Set();
  const fail = (label, msg) => errors.push(`${label} : ${msg}`);
  const text = (value, label) => {
    count++;
    textCount += value.length;
    if (!value.trim()) fail(label, 'le texte est vide.');
    return {
      type: 10,
      content: value
    };
  };
  const getMedia = (m, label, thumbnail = false) => {
    let url = m.url;
    if (m.asset_id) {
      const a = assetMap[m.asset_id];
      if (!a) fail(label, 'fichier introuvable.');else {
        used.add(a.id);
        if (!a.content_type.startsWith(thumbnail ? 'image/' : 'image/') && !(a.content_type.startsWith('video/') && !thumbnail)) fail(label, 'type de média incompatible.');
      }
      url = a ? `attachment://${a.discord_filename}` : '';
      if (m.url) fail(label, 'choisissez une URL ou un fichier.');
    } else if (!safeUrl(url, true)) fail(label, 'une URL HTTPS publique est nécessaire.');
    return {
      media: {
        url
      },
      description: m.description,
      spoiler: m.spoiler
    };
  };
  const button = (b, label) => {
    count++;
    if (!b.label.trim()) fail(label, 'libellé de bouton vide.');
    if (!safeUrl(b.url)) fail(label, 'lien HTTP ou HTTPS nécessaire.');
    const result = {
      type: 2,
      style: 5,
      label: b.label,
      url: b.url,
      disabled: b.disabled
    };
    if (b.emoji) {
      const m = b.emoji.match(/^<(a?):\w+:([0-9]{15,22})>$/);
      result.emoji = m ? {
        id: m[2],
        animated: !!m[1]
      } : {
        name: b.emoji
      };
    }
    return result;
  };
  const components = [];
  doc.groups.forEach((g, gi) => {
    const children = [];
    if (!g.blocks.length) fail(`Panneau ${gi + 1}`, 'ajoutez un bloc.');
    g.blocks.forEach((b, bi) => {
      const label = `Panneau ${gi + 1}, bloc ${bi + 1}`;
      let item;
      if (b.kind === 'text') item = text(b.text, label);else if (b.kind === 'section') {
        count++;
        if (!b.texts.length) fail(label, 'la section nécessite du texte.');
        const c = b.texts.map(t => text(t, label));
        let accessory;
        if (b.accessory === 'button') accessory = button(b.button, label);else {
          count++;
          accessory = {
            type: 11,
            ...getMedia(b.thumbnail, label, true)
          };
        }
        item = {
          type: 9,
          components: c,
          accessory
        };
      } else if (b.kind === 'gallery') {
        count++;
        if (!b.items.length) fail(label, 'ajoutez un média.');
        item = {
          type: 12,
          items: b.items.map(m => getMedia(m, label))
        };
      } else if (b.kind === 'separator') {
        count++;
        item = {
          type: 14,
          divider: b.divider,
          spacing: b.spacing
        };
      } else if (b.kind === 'buttons') {
        count++;
        if (!b.buttons.length) fail(label, 'ajoutez un bouton.');
        item = {
          type: 1,
          components: b.buttons.map(v => button(v, label))
        };
      } else {
        count++;
        const a = assetMap[b.file_asset_id];
        if (a) used.add(a.id);else fail(label, 'sélectionnez un fichier.');
        item = {
          type: 13,
          file: {
            url: a ? `attachment://${a.discord_filename}` : ''
          },
          spoiler: b.spoiler
        };
      }
      children.push(item);
    });
    if (g.boxed) {
      count++;
      const c = {
        type: 17,
        components: children,
        spoiler: g.spoiler
      };
      if (g.color) c.accent_color = parseInt(g.color.slice(1), 16);
      components.push(c);
    } else components.push(...children);
  });
  if (count > 40) fail('Message', `${count}/40 composants.`);
  if (textCount > 4000) fail('Message', `${textCount}/4000 caractères de texte.`);
  if (used.size > 10) fail('Fichiers', '10 fichiers au maximum.');
  const size = [...used].reduce((n, id) => n + (assetMap[id]?.size || 0), 0);
  if (size > 10 * 1024 * 1024) fail('Fichiers', 'le total dépasse 10 Mo.');
  ['roles', 'users'].forEach(k => {
    if (doc.mentions[k].some(id => !/^\d{15,22}$/.test(id))) fail('Mentions', 'identifiant Discord invalide.');
    if (doc.mentions[k].length > 100) fail('Mentions', '100 identifiants au maximum.');
  });
  return {
    payload: {
      flags: 32768 | (doc.silent ? 4096 : 0),
      components,
      allowed_mentions: {
        parse: doc.mentions.everyone ? ['everyone'] : [],
        roles: [...new Set(doc.mentions.roles)],
        users: [...new Set(doc.mentions.users)],
        replied_user: false
      }
    },
    errors,
    component_count: count,
    text_count: textCount,
    file_size: size
  };
}
export function downloadJson(value, name) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {
    type: 'application/json'
  }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

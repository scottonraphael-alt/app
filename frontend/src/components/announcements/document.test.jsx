import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { cloneDocument, compileDocument, newBlock, newDocument, safeUrl } from './document';
import Preview from './Preview';
import { announcementLogSummary } from './auditLabels';
global.IS_REACT_ACT_ENVIRONMENT = true;
it('compile tous les blocs V2 sans contenu classique ni mentions implicites', () => {
  const d = newDocument();
  d.groups[0].blocks = [newBlock('text'), {
    ...newBlock('section'),
    accessory: 'button',
    button: {
      label: 'Site',
      url: 'https://example.com',
      emoji: '',
      disabled: false
    }
  }, {
    ...newBlock('gallery'),
    items: [{
      url: 'https://example.com/a.png',
      description: 'Image',
      spoiler: false
    }]
  }, newBlock('separator'), {
    ...newBlock('buttons'),
    buttons: [{
      label: 'Site',
      url: 'https://example.com',
      emoji: '',
      disabled: false
    }]
  }];
  const r = compileDocument(d);
  expect(r.errors).toEqual([]);
  expect(r.component_count).toBe(9);
  expect(r.payload.flags).toBe(32768);
  expect(r.payload.content).toBeUndefined();
  expect(r.payload.allowed_mentions.parse).toEqual([]);
  const cloned = cloneDocument(d);
  expect(cloned.groups[0].id).not.toBe(d.groups[0].id);
  expect(cloned.groups[0].blocks[0].id).not.toBe(d.groups[0].blocks[0].id);
});
it('compte les emoji en UTF16 et les fichiers uniques dans les limites', () => {
  const d = newDocument();
  d.groups[0].blocks[0].text = '🌿'.repeat(2001);
  expect(compileDocument(d).errors.join(' ')).toContain('4002/4000');
  d.groups[0].blocks = [{
    ...newBlock('file'),
    file_asset_id: 'asset'
  }, {
    ...newBlock('file'),
    file_asset_id: 'asset'
  }];
  const r = compileDocument(d, {
    asset: {
      id: 'asset',
      discord_filename: 'unique.pdf',
      size: 120,
      content_type: 'application/pdf'
    }
  });
  expect(r.errors).toEqual([]);
  expect(r.file_size).toBe(120);
  expect(r.payload.components[0].components[0].file.url).toBe('attachment://unique.pdf');
});
it('refuse les URL dangereuses et ne traite jamais le Markdown comme du HTML', async () => {
  expect(safeUrl('javascript:alert(1)')).toBe(false);
  expect(safeUrl('http://localhost/x')).toBe(false);
  const d = newDocument();
  d.groups[0].blocks[0].text = '<img src=x onerror=alert(1)>\n**Fort** et *italique*\n[Site](https://example.com)';
  const container = document.createElement('div'),
    root = createRoot(container);
  await act(async () => root.render(<Preview document={d} assets={{}} catalogue={{
    roles: [],
    channels: []
  }} base="/api" theme="dark" />));
  expect(container.querySelector('img')).toBeNull();
  expect(container.querySelector('.an-markdown strong').textContent).toBe('Fort');
  expect(container.querySelector('em').textContent).toBe('italique');
  expect(container.querySelector('.an-markdown a').getAttribute('href')).toBe('https://example.com');
  await act(async () => root.unmount());
});
it('décrit les actions et les versions dans les logs français', () => {
  const r = announcementLogSummary('announcement.draft.updated', {
    title: 'Été',
    revision: 3,
    before_revision: 2
  });
  expect(r.text).toContain('enregistré');
  expect(r.extras).toContainEqual(['Version', '3']);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {vocalNotice} from './messages.mjs';

test('vocal panel retains consent information and the actual Activity controls',()=>{
  const panel=vocalNotice();
  assert.equal(panel.flags,32768);
  assert.equal(panel.content,undefined);
  assert.deepEqual(panel.allowedMentions,{parse:[]});
  const text=panel.components[0].components.map(c=>c.content||'').join('\n');
  for(const phrase of ['facultative','Activer les scores','Désactiver les scores','Aucun enregistrement vocal n’est conservé','retirer ton accord','casque'])assert.ok(text.includes(phrase));
  assert.equal(panel.components[0].type,17);
});

test('welcome panel mentions only the arriving member',()=>{
  const member='555555555555555555',panel=vocalNotice(member);
  assert.deepEqual(panel.allowedMentions,{parse:[],users:[member]});
  assert.ok(panel.components[0].components[1].content.includes(`<@${member}>`));
});

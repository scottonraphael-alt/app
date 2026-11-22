import { getErrorMessage } from './client';

const errorWith = detail => ({ response: { data: { detail } } });

test('keeps readable API errors', () => {
  expect(getErrorMessage(errorWith('Accès refusé.'))).toBe('Accès refusé.');
});

test('converts validation lists to renderable text', () => {
  expect(getErrorMessage(errorWith([{ msg: 'Date invalide' }, { msg: 'Champ requis' }])))
    .toBe('Date invalide\nChamp requis');
});

test('extracts structured messages without exposing document contents', () => {
  expect(getErrorMessage(errorWith({ message: 'Conflit', current: { secret: 'privé' } }))).toBe('Conflit');
});

test.each([undefined, null, {}, [{ loc: ['body'] }], 42, ''])('unknown error details use a string fallback: %p', detail => {
  expect(getErrorMessage(errorWith(detail))).toBe('Une erreur est survenue. Réessayez.');
});

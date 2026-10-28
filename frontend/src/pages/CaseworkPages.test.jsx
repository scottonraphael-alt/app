import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ContactsStaffPage, ConvocationsPage, BullesPage, VerificationTicketsPage } from './CaseworkPages';
import { api } from '../api/client';
jest.mock('react-router-dom', () => ({
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
  useParams: () => ({ caseId: mockCaseId }),
}), { virtual: true });
jest.mock('../api/client', () => ({ api: { get: jest.fn(), post: jest.fn() }, getErrorMessage: () => 'Accès refusé' }));
jest.mock('../components/projects/ProjectUI', () => ({ Modal: ({ title, children, onClose }) => <div role="dialog"><h2>{title}</h2>{children}<button onClick={onClose}>Fermer</button></div> }));
global.IS_REACT_ACT_ENVIRONMENT = true;
let mockCaseId;
const row = { id: 'case-1', guild_id: '100000000000000001', kind: 'contact_staff', member: { id: '500000000000000001', display_name: 'Alex' }, status: 'open', visibility: 'staff', revision: 1,
  assigned: null, channel_id: '600000000000000001', message_count: 55, sync: { status: 'ready', generation: 'v1', files_complete: true }, notes: [], events: [] };
let container, root;
const button = text => [...container.querySelectorAll('button')].find(el => el.textContent.trim() === text);
const render = async element => { await act(async () => root.render(element)); };
const click = async element => { await act(async () => element.click()); };
beforeEach(() => {
  jest.clearAllMocks(); mockCaseId = null; container = document.createElement('div'); document.body.append(container); root = createRoot(container);
  Object.defineProperty(global, 'crypto', { configurable: true, value: { randomUUID: () => 'test-case-request-0001' } });
  api.get.mockImplementation(async url => ({ data: url.endsWith('/messages') ? { items: [], total: 55 } : url === '/casework' ? { items: [row], total: 1 } : row }));
  api.post.mockResolvedValue({ data: { ...row, status: 'closing' } });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

test.each([[ContactsStaffPage, 'contact_staff'], [ConvocationsPage, 'summons'], [BullesPage, 'bubble'], [VerificationTicketsPage, 'verification']])('dedicated family page queries only its family', async (Page, kind) => {
  api.get.mockResolvedValue({ data: { items: [], total: 0 } });
  await render(<Page />);
  expect(api.get).toHaveBeenCalledWith('/casework', { params: { kind, archived: false, attention: false, offset: 0, limit: 25 } });
  expect(document.body.classList.contains('casier-no-nav')).toBe(true);
});

test('archive remains readable after Discord deletion without live-channel controls', async () => {
  mockCaseId = 'case-1';
  api.get.mockImplementation(async url => ({ data: url.endsWith('/messages') ? { items: [], total: 0 } : { ...row, status: 'archived', archive: { complete: false } } }));
  await render(<ContactsStaffPage />);
  expect(container.textContent).toContain('Dernière sauvegarde conservée');
  expect(button('Actualiser les messages')).toBeUndefined();
  expect(button('Préparer la clôture')).toBeUndefined();
});

test('closing needs explicit confirmation and preserves the request key on retry', async () => {
  mockCaseId = 'case-1'; await render(<ContactsStaffPage />);
  const form = [...container.querySelectorAll('form')].find(el => el.textContent.includes('Motif de clôture'));
  await act(async () => form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })));
  expect(api.post).not.toHaveBeenCalled();
  expect(container.querySelector('[role=dialog]').textContent).toContain('Une pièce jointe manquante bloque cette suppression.');
  api.post.mockRejectedValueOnce(new Error('network'));
  await click(button('Confirmer')); await click(button('Confirmer'));
  expect(api.post).toHaveBeenCalledTimes(2); expect(api.post.mock.calls[0][1]).toEqual(api.post.mock.calls[1][1]);
});

test('conversation pages use server pagination rather than rendering all messages', async () => {
  mockCaseId = 'case-1'; await render(<ContactsStaffPage />);
  await click(button('Suivant'));
  expect(api.get).toHaveBeenLastCalledWith('/casework/case-1/messages', { params: { offset: 50, limit: 50, q: '' } });
});

test('wrong family never renders the returned private conversation', async () => {
  mockCaseId = 'case-1'; await render(<BullesPage />);
  expect(container.textContent).toContain('Ce dossier appartient à une autre famille.');
  expect(api.get.mock.calls.some(([url]) => url.endsWith('/messages'))).toBe(false);
});


test('a prepared archive does not claim a still-open Discord channel has disappeared', async () => {
  mockCaseId = 'case-1';
  api.get.mockImplementation(async url => ({ data: url.endsWith('/messages') ? { items: [], total: 0 } : {
    ...row, status: 'closing', archive: { complete: false }, closure: { error_type: 'HTTPException' },
  } }));
  await render(<ContactsStaffPage />);
  expect(container.textContent).toContain('La clôture demande une vérification');
  expect(container.textContent).not.toContain('Le salon Discord a disparu');
});

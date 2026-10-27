import { act } from 'react';
import { createRoot } from 'react-dom/client';
import SanctionAccessPage from './SanctionAccessPage';
import { api } from '../api/client';
import { toast } from 'sonner';
jest.mock('react-router-dom', () => ({
  Link: ({
    children,
    to,
    ...props
  }) => <a href={to} {...props}>{children}</a>
}), {
  virtual: true
});
jest.mock('../api/client', () => ({
  api: {
    get: jest.fn(),
    put: jest.fn(),
    delete: jest.fn()
  },
  getErrorMessage: () => 'Erreur d’accès'
}));
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn()
  }
}));
global.IS_REACT_ACT_ENVIRONMENT = true;
const members = [{
  id: '400000000000000001',
  display_name: 'Alex',
  username: 'alex',
  is_staff: true,
  access: null
}, {
  id: '400000000000000002',
  display_name: 'Camille',
  username: 'camille',
  is_staff: true,
  access: {
    enabled: true,
    version: 'v1',
    last_used_at: null
  }
}, {
  id: '400000000000000003',
  display_name: 'Ancien staff',
  username: 'ancien',
  is_staff: false,
  access: {
    enabled: true,
    version: 'old'
  }
}];
let container, root;
const button = (text, scope = document) => [...scope.querySelectorAll('button')].find(el => el.textContent.trim() === text);
const row = name => [...container.querySelectorAll('article')].find(el => el.textContent.includes(name));
async function change(el, text) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value').set.call(el, text);
    el.dispatchEvent(new Event(el.tagName === 'SELECT' ? 'change' : 'input', {
      bubbles: true
    }));
  });
}
beforeEach(async () => {
  jest.clearAllMocks();
  localStorage.clear();
  window.confirm = jest.fn(() => true);
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: {
      getRandomValues: values => {
        values.fill(0);
        return values;
      }
    }
  });
  api.get.mockResolvedValue({
    data: {
      items: members
    }
  });
  api.put.mockResolvedValue({
    data: {
      enabled: true,
      version: 'v2'
    }
  });
  api.delete.mockResolvedValue({});
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root.render(<SanctionAccessPage />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
it('liste les accès et les anciens membres avec un retour Accueil', () => {
  expect(container.querySelector('.cz-home').getAttribute('href')).toBe('/');
  expect(container.querySelectorAll('article')).toHaveLength(3);
  expect(container.textContent).toContain('6 caractères');
  expect(container.textContent).toContain('Codes stockés sous forme hachée');
  expect(button('Remplacer le code', row('Ancien staff')).disabled).toBe(true);
});
it('crée un code de six caractères, puis l’efface à la fermeture sans stockage local', async () => {
  await act(async () => button('Définir le code', row('Alex')).click());
  const input = document.querySelector('[aria-label="Code personnel de modération"]');
  expect(input.type).toBe('password');
  expect(input.value).toBe('');
  await change(input, 'abc12');
  expect(button('Enregistrer l’accès').disabled).toBe(true);
  await change(input, 'abc123');
  expect(input.value).toBe('ABC123');
  await act(async () => button('Enregistrer l’accès').click());
  expect(api.put).toHaveBeenCalledWith('/responsable/acces-sanctions/400000000000000001', {
    code: 'ABC123',
    expected_version: null
  });
  expect(document.querySelector('.sa-modal [role="status"]').textContent).toContain('nouveau code est actif');
  await act(async () => button('Terminer').click());
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(localStorage.length).toBe(0);
});
it('remplace avec une garde de version et propose un générateur de six caractères', async () => {
  await act(async () => button('Remplacer le code', row('Camille')).click());
  expect(document.querySelector('[aria-label="Code personnel de modération"]').value).toBe('');
  await act(async () => button('Générer un code sécurisé').click());
  const code = document.querySelector('[aria-label="Code personnel de modération"]').value;
  expect(code).toMatch(/^[A-Z2-9]{6}$/);
  await act(async () => button('Enregistrer l’accès').click());
  expect(api.put.mock.calls[0][1]).toEqual({
    code,
    expected_version: 'v1'
  });
});
it('révoque aussi les anciens staffs avec la version courante', async () => {
  await act(async () => button('Révoquer', row('Ancien staff')).click());
  expect(api.delete).toHaveBeenCalledWith('/responsable/acces-sanctions/400000000000000003', {
    params: {
      expected_version: 'old'
    }
  });
  expect(toast.success).toHaveBeenCalledWith('Accès révoqué.');
});
it('filtre la liste sans envoyer de code ni de recherche sur le réseau', async () => {
  await change(container.querySelector('[aria-label="Rechercher un membre du staff"]'), 'Camille');
  expect(container.querySelectorAll('article')).toHaveLength(1);
  expect(api.get).toHaveBeenCalledTimes(1);
  expect(api.put).not.toHaveBeenCalled();
});
it('garde le formulaire utilisable en cas de refus API', async () => {
  await act(async () => button('Définir le code', row('Alex')).click());
  await change(document.querySelector('[aria-label="Code personnel de modération"]'), 'ABC123');
  api.put.mockRejectedValueOnce(new Error('Conflict'));
  await act(async () => button('Enregistrer l’accès').click());
  expect(toast.error).toHaveBeenCalledWith('Erreur d’accès');
  expect(button('Enregistrer l’accès').disabled).toBe(false);
});

import { act } from 'react';
import { createRoot } from 'react-dom/client';
import ProjectsListPage from './ProjectsListPage';
import ProjectDetailPage from './ProjectDetailPage';
import ProjectCalendarPage from './ProjectCalendarPage';
import { api } from '../api/client';
jest.mock('react-router-dom', () => ({
  Link: ({
    to,
    children,
    ...props
  }) => <a href={to} {...props}>{children}</a>,
  useNavigate: () => jest.fn(),
  useParams: () => ({
    projectId: 'p'
  }),
  useSearchParams: () => [new URLSearchParams(), jest.fn()]
}), {
  virtual: true
});
jest.mock('../api/client', () => ({
  api: {
    get: jest.fn(),
    post: jest.fn(),
    patch: jest.fn(),
    put: jest.fn(),
    delete: jest.fn(),
    defaults: {
      baseURL: '/api'
    }
  },
  getErrorMessage: () => 'Erreur de projet'
}));
jest.mock('../components/SummaryReader', () => ({
  content
}) => <div>{content}</div>);
jest.mock('../components/TiptapSummaryEditor', () => ({
  value,
  onChange
}) => <textarea value={value} onChange={e => onChange(e.target.value)} />);
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn()
  }
}));
global.IS_REACT_ACT_ENVIRONMENT = true;
const project = {
  id: 'p',
  title: 'Soirée jeux',
  description: 'Jouons ensemble',
  status: 'en_cours',
  priority: 'haute',
  start_date: '2026-10-27',
  end_date: '2026-10-31',
  created_by: {
    id: 'owner',
    username: 'Pilote'
  },
  members: [{
    id: 'owner',
    username: 'Pilote'
  }, {
    id: 'member',
    username: 'Alex'
  }],
  content_markdown: 'Brief existant',
  task_counts: {
    a_faire: 1,
    rendu: 1
  },
  updated_at: '2026-10-27'
};
const tasks = [{
  id: 't',
  project_id: 'p',
  title: 'Préparer les jeux',
  status: 'a_faire',
  due_date: '2026-10-30',
  assignee: {
    id: 'member',
    username: 'Alex'
  }
}, {
  id: 'r',
  project_id: 'p',
  title: 'Les visuels',
  status: 'rendu',
  due_date: '2026-10-29',
  assignee: {
    id: 'member',
    username: 'Alex'
  }
}];
let root, container;
beforeEach(() => {
  jest.clearAllMocks();
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  api.get.mockImplementation(url => Promise.resolve({
    data: url.endsWith('/workspace/overview') ? {
      projects: [project],
      my_tasks: tasks
    } : url.endsWith('/tasks') ? tasks : url.endsWith('/resources') ? [] : url.endsWith('/activity') ? [] : url.endsWith('/calendar-events') ? {
      projects: [project],
      tasks
    } : project
  }));
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});
const click = async (text, where = container) => {
  const button = [...where.querySelectorAll('button')].find(b => b.textContent.includes(text));
  expect(button).toBeTruthy();
  await act(async () => button.click());
};
it('charge le carnet sans requêtes par projet et propose les archives', async () => {
  await act(async () => root.render(<ProjectsListPage helper={{
    id: 'member'
  }} />));
  expect(document.body.classList.contains('projects-no-nav')).toBe(true);
  expect(container.textContent).toContain('Soirée jeux');
  expect(container.querySelector('a[href="/"]')).not.toBeNull();
  expect(api.get).toHaveBeenCalledTimes(1);
  await click('Archives');
  expect(container.querySelectorAll('.pj-project-card')).toHaveLength(0);
});
it('ouvre une création accessible et restaure le focus', async () => {
  await act(async () => root.render(<ProjectsListPage helper={{
    id: 'member'
  }} />));
  const button = container.querySelector('[data-testid="new-project-button"]');
  button.focus();
  await click('Nouveau projet');
  expect(document.querySelector('[role="dialog"]')).not.toBeNull();
  await act(async () => document.querySelector('[aria-label="Fermer"]').click());
  expect(document.querySelector('[role="dialog"]')).toBeNull();
  expect(document.activeElement).toBe(button);
});
it('permet au pilote de consulter et valider un rendu depuis le tableau', async () => {
  await act(async () => root.render(<ProjectDetailPage helper={{
    id: 'owner'
  }} />));
  await click('Tâches');
  expect(container.querySelectorAll('.pj-board-column')).toHaveLength(4);
  await click('Les visuels');
  expect(document.querySelector('[role="dialog"]').textContent).toContain('Valider le rendu');
  api.put.mockResolvedValue({
    data: {
      ...tasks[1],
      status: 'valide'
    }
  });
  await click('Valider le rendu', document);
  expect(api.put).toHaveBeenCalledWith('/animateur/tasks/r/validate');
});
it('garde les archives en lecture seule', async () => {
  api.get.mockImplementation(url => Promise.resolve({
    data: url.endsWith('/tasks') ? tasks : url.endsWith('/resources') ? [] : {
      ...project,
      status: 'archive'
    }
  }));
  await act(async () => root.render(<ProjectDetailPage helper={{
    id: 'owner'
  }} />));
  expect(container.textContent).toContain('Restaurer le projet');
  await click('Tâches');
  expect([...container.querySelectorAll('button')].some(b => b.textContent.includes('Ajouter une tâche'))).toBe(false);
});
it('charge le journal à la demande et réserve les paramètres au pilote', async () => {
  await act(async () => root.render(<ProjectDetailPage helper={{
    id: 'member'
  }} />));
  expect(api.get.mock.calls.some(([url]) => url.endsWith('/activity'))).toBe(false);
  expect(container.textContent).not.toContain('Paramètres');
  await click('Journal');
  expect(api.get).toHaveBeenCalledWith('/animateur/projects/p/activity');
  expect(container.textContent).toContain('Publier dans le journal');
});
it('propose le mois, l’agenda et les échéances personnelles', async () => {
  await act(async () => root.render(<ProjectCalendarPage helper={{
    id: 'member'
  }} />));
  expect(container.querySelectorAll('.pj-day').length).toBeGreaterThanOrEqual(28);
  await click('Agenda');
  expect(container.querySelector('.pj-month-grid')).toBeNull();
  await act(async () => container.querySelector('input[type="checkbox"]').click());
  expect(container.textContent).not.toContain('Début du projet');
  expect(container.textContent).toContain('Échéance de tâche');
});

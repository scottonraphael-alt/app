"""Offline project lifecycle, authorization, validation and journal regressions."""
import security_harness as h
import pytest
from routers import animateur, animateur_calendar


@pytest.fixture(autouse=True)
def isolated():
    h.reset_db()
    h.reset_discord()


def client(role="animateur"):
    c = h.make_client(animateur.router, animateur.tasks_router, animateur.resources_router, animateur.members_router, animateur_calendar.router)
    c.cookies.update(h.session_cookies(role))
    return c


def create(c=None, **extra):
    c = c or client()
    r = c.post("/api/animateur/projects", json={"title":"Soirée jeux", "start_date":"2026-10-27", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def task(c, p, **extra):
    r = c.post(f"/api/animateur/projects/{p['id']}/tasks", json={"title":"Préparer les jeux", "assignee_id":h.USER_IDS["animateur"], "due_date":"2026-11-01", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def add_other(p):
    identity = {"id":h.USER_IDS["responsable"], "username":"test-responsable", "display_name":"Test responsable"}
    h.run(h.db.projects.update_one({"id":p["id"]}, {"$push":{"members":identity}}))
    h.fake_discord.member_roles[h.USER_IDS["responsable"]] = [h.ROLE_IDS["animateur"]]
    from services import auth_service
    auth_service._ROLE_CACHE.clear()
    return client("responsable")


def test_full_owner_lifecycle_and_overview():
    c=client(); p=create(c,priority="haute",tags=[" Jeux ","Jeux","Vocal"])
    assert p["tags"] == ["Jeux","Vocal"]
    t=task(c,p,priority="haute"); url=f"/api/animateur/tasks/{t['id']}"
    assert c.patch(url,json={"status":"en_cours","blocked_reason":"Besoin du visuel"}).status_code == 200
    overview=c.get("/api/animateur/projects/workspace/overview").json()
    assert overview["projects"][0]["task_counts"] == {"en_cours":1}
    assert overview["my_tasks"][0]["blocked_reason"]
    assert "content_markdown" not in overview["projects"][0]
    assert c.put(url+"/validate").status_code == 409
    assert c.put(url+"/submit",data={"submission_content":'[{"type":"paragraph","content":"Prêt"}]'}).status_code == 200
    assert c.put(url+"/submit").status_code == 409
    assert c.patch(url,json={"status":"en_cours"}).status_code == 409
    assert c.patch(url,json={"status":"en_cours","review_note":"Ajouter les horaires"}).status_code == 200
    assert c.put(url+"/submit").status_code == 200
    assert c.put(url+"/validate").json()["status"] == "valide"
    assert c.patch(f"/api/animateur/projects/{p['id']}/settings",json={"status":"termine"}).status_code == 200
    events=h.run(h.db.auth_logs.distinct("event_type"))
    assert {"project.created","project.task.created","project.task.updated","project.task.submitted","project.task.validated","project.settings.updated"} <= set(events)


def test_completion_requires_validation_and_archive_is_read_only():
    c=client(); p=create(c); t=task(c,p)
    url=f"/api/animateur/projects/{p['id']}/settings"
    assert c.patch(url,json={"status":"termine"}).status_code == 409
    assert c.patch(url,json={"status":"archive"}).status_code == 200
    assert c.patch(f"/api/animateur/tasks/{t['id']}",json={"status":"en_cours"}).status_code == 409
    assert c.put(f"/api/animateur/tasks/{t['id']}/submit").status_code == 409
    assert c.post(f"/api/animateur/projects/{p['id']}/activity",json={"message":"test"}).status_code == 409
    assert c.patch(url,json={"title":"oops"}).status_code == 409
    assert c.patch(url,json={"status":"en_cours"}).status_code == 200


@pytest.mark.parametrize("payload", [{"start_date":"wrong"},{"start_date":"2026-02-30"},{"end_date":"2026-10-26"},{"title":" "},{"title":"a"*161},{"priority":"urgent"},{"tags":["x"]*9}])
def test_create_rejects_invalid_values(payload):
    r=client().post("/api/animateur/projects",json={"title":"Projet","start_date":"2026-10-27",**payload})
    assert r.status_code == 422, r.text
    assert h.run(h.db.projects.count_documents({})) == 0


def test_partial_settings_preserve_brief_and_check_merged_dates():
    c=client(); p=create(c)
    h.run(h.db.projects.update_one({"id":p["id"]},{"$set":{"content_markdown":"rich-text-original"}}))
    url=f"/api/animateur/projects/{p['id']}/settings"
    r=c.patch(url,json={"priority":"haute","end_date":"2026-11-01"})
    assert r.status_code == 200 and r.json()["content_markdown"] == "rich-text-original"
    assert c.patch(url,json={"start_date":"2026-11-02"}).status_code == 422
    assert c.patch(url,json={"priority":None}).status_code == 422
    assert c.patch(url,json={"title":"   "}).status_code == 422
    assert c.patch(url,json={"end_date":None}).status_code == 200


def test_member_can_work_own_task_but_not_manage_or_work_others():
    owner=client(); p=create(owner); other=add_other(p); t=task(owner,p,assignee_id=h.USER_IDS["responsable"])
    url=f"/api/animateur/tasks/{t['id']}"
    assert other.patch(url,json={"status":"en_cours"}).status_code == 200
    assert other.patch(url,json={"title":"Renommée"}).status_code == 403
    assert other.post(f"/api/animateur/projects/{p['id']}/tasks",json={"title":"no","assignee_id":h.USER_IDS["responsable"],"due_date":"2026-11-01"}).status_code == 403
    assert other.patch(f"/api/animateur/projects/{p['id']}/settings",json={"status":"archive"}).status_code == 403
    assert other.delete(url).status_code == 403
    assert other.put(url+"/validate").status_code == 403
    owned=task(owner,p)
    assert other.patch(f"/api/animateur/tasks/{owned['id']}",json={"blocked_reason":"no"}).status_code == 403
    assert other.put(f"/api/animateur/tasks/{owned['id']}/submit").status_code == 403


def test_remove_requires_reassignment_and_preserves_creator():
    c=client(); p=create(c); add_other(p); t=task(c,p,assignee_id=h.USER_IDS["responsable"])
    url=f"/api/animateur/projects/{p['id']}/members"
    assert c.delete(url+"/"+h.USER_IDS["animateur"]).status_code == 409
    assert c.delete(url+"/"+h.USER_IDS["responsable"]).status_code == 409
    assert c.patch(f"/api/animateur/tasks/{t['id']}",json={"assignee_id":h.USER_IDS["animateur"]}).status_code == 200
    r=c.delete(url+"/"+h.USER_IDS["responsable"])
    assert r.status_code == 200 and len(r.json()["members"]) == 1
    assert c.patch(f"/api/animateur/tasks/{t['id']}",json={"assignee_id":"missing"}).status_code == 422


def test_journal_private_and_notes_survive_audit_expiry():
    c=client(); p=create(c); url=f"/api/animateur/projects/{p['id']}/activity"
    assert c.post(url,json={"message":"   "}).status_code == 422
    assert c.post(url,json={"message":"Décision : thème cinéma."}).status_code == 201
    entries=c.get(url).json()
    assert len(entries) == 2
    assert all("ip" not in e and "user_agent" not in e for e in entries)
    h.run(h.db.auth_logs.delete_many({}))
    assert c.get(url).json()[0]["details"]["message"] == "Décision : thème cinéma."
    h.fake_discord.member_roles[h.USER_IDS["staff"]]=[h.ROLE_IDS["animateur"]]
    assert client("staff").get(url).status_code == 403


def test_global_deletion_cascades_notes_and_tasks():
    c=client(); p=create(c); task(c,p)
    assert c.post(f"/api/animateur/projects/{p['id']}/activity",json={"message":"A garder"}).status_code == 201
    assert c.delete(f"/api/animateur/projects/{p['id']}").status_code == 403
    assert client("responsable").delete(f"/api/animateur/projects/{p['id']}").status_code == 204
    assert h.run(h.db.project_notes.count_documents({})) == 0
    assert h.run(h.db.project_tasks.count_documents({})) == 0


def test_calendar_omits_heavy_payloads_and_missing_ids_404():
    c=client(); p=create(c); t=task(c,p)
    r=c.get("/api/animateur/calendar-events")
    assert r.status_code == 200
    assert "content_markdown" not in r.json()["projects"][0]
    assert "submission_note" not in r.json()["tasks"][0]
    assert not r.json()["truncated"]
    assert c.patch("/api/animateur/projects/missing/settings",json={"title":"x"}).status_code == 404
    assert c.patch("/api/animateur/tasks/missing",json={"status":"en_cours"}).status_code == 404
    assert c.get("/api/animateur/projects/missing/activity").status_code == 404


def test_non_animator_cannot_use_workspace():
    c=client("helper")
    assert c.get("/api/animateur/projects/workspace/overview").status_code == 403
    assert c.get("/api/animateur/calendar-events").status_code == 403


def test_brief_patch_does_not_overwrite_settings_and_is_member_only():
    c=client(); p=create(c)
    url=f"/api/animateur/projects/{p['id']}"
    assert c.patch(url+"/settings",json={"priority":"haute","title":"Nouveau titre"}).status_code == 200
    r=c.patch(url+"/brief",json={"content_markdown":'[{"type":"paragraph","content":"Brief"}]'})
    assert r.status_code == 200 and r.json()["title"] == "Nouveau titre" and r.json()["priority"] == "haute"
    assert c.patch(url+"/settings",json={"status":"termine"}).status_code == 200
    assert c.patch(url+"/brief",json={"content_markdown":"oops"}).status_code == 409
    assert c.post(url+"/tasks",json={"title":"x","assignee_id":h.USER_IDS["animateur"],"due_date":"2026-11-01"}).status_code == 409
    assert c.patch(url+"/settings",json={"status":"en_cours"}).status_code == 200
    h.fake_discord.member_roles[h.USER_IDS["staff"]]=[h.ROLE_IDS["animateur"]]
    assert client("staff").patch(url+"/brief",json={"content_markdown":"oops"}).status_code == 403


def test_assignee_can_submit_without_staff_role():
    owner=client(); p=create(owner); other=add_other(p)
    t=task(owner,p,assignee_id=h.USER_IDS["responsable"])
    assert other.put(f"/api/animateur/tasks/{t['id']}/submit",data={"submission_content":"Prêt"}).status_code == 200


def test_ui_events_are_separate_from_server_mutations_and_require_project_access():
    c=client(); p=create(c)
    payload={"kind":"clicked","page":"project","project_id":p["id"],"label":"Modifier le brief"}
    assert c.post('/api/animateur/projects/workspace/events',json=payload).status_code == 204
    entry=h.run(h.db.auth_logs.find_one({"event_type":"project.ui.clicked"}))
    assert entry['helper_id'] == h.USER_IDS['animateur']
    assert entry['details']['source'] == 'client'
    assert entry['details']['project_title'] == p['title']
    assert c.post('/api/animateur/projects/workspace/events',json={**payload,"kind":"project.deleted"}).status_code == 422
    assert client('helper').post('/api/animateur/projects/workspace/events',json=payload).status_code == 403
    assert c.post('/api/animateur/projects/workspace/events',json={**payload,"project_id":"missing"}).status_code == 404


def test_reads_refusals_and_validation_errors_are_audited():
    c=client(); p=create(c); t=task(c,p)
    for suffix in ('tasks','resources','activity'):
        assert c.get(f'/api/animateur/projects/{p["id"]}/{suffix}').status_code == 200
    assert c.get('/api/animateur/projects/workspace/overview').status_code == 200
    assert c.get('/api/animateur/calendar-events').status_code == 200
    other=add_other(p)
    assert other.patch(f'/api/animateur/tasks/{t["id"]}',json={"title":"no"}).status_code == 403
    assert c.patch(f'/api/animateur/tasks/{t["id"]}',json={"priority":"unknown"}).status_code == 422
    events=set(h.run(h.db.auth_logs.distinct('event_type')))
    assert {'project.tasks.viewed','project.resources.viewed','project.activity.viewed','project.calendar.viewed','project.workspace.viewed'} <= events
    failures=h.run(h.db.auth_logs.find({'event_type':'project.action.failed'}).to_list(None))
    assert {entry['status_code'] for entry in failures} == {403,422}
    assert all(entry['details']['source'] == 'server' and entry['details']['project_id'] == p['id'] for entry in failures)


def test_downloads_are_audited_and_ui_events_do_not_pollute_team_journal(monkeypatch):
    from services import storage_service
    from pathlib import Path
    import tempfile
    c=client(); p=create(c); t=task(c,p)
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setattr(storage_service,'STORAGE_ROOT',Path(folder))
        file=b'%PDF test'
        uploaded=c.post(f'/api/animateur/projects/{p["id"]}/resources',data={'title':'Support'},files={'file':('support.pdf',file,'application/pdf')})
        assert uploaded.status_code == 201, uploaded.text
        resource=uploaded.json()
        assert c.get(f'/api/animateur/resources/{resource["id"]}/download').status_code == 200
        assert c.put(f'/api/animateur/tasks/{t["id"]}/submit',files={'file':('rendu.pdf',file,'application/pdf')}).status_code == 200
        assert c.get(f'/api/animateur/tasks/{t["id"]}/submission/download').status_code == 200
    assert c.post('/api/animateur/projects/workspace/events',json={'kind':'changed','page':'project','project_id':p['id'],'label':'Filtre','value':'En retard'}).status_code == 204
    events=set(h.run(h.db.auth_logs.distinct('event_type')))
    assert {'project.resource.downloaded','project.task.downloaded','project.ui.changed'} <= events
    journal=c.get(f'/api/animateur/projects/{p["id"]}/activity').json()
    assert not any(entry['event_type'].startswith('project.ui.') or entry['event_type'].endswith('.downloaded') for entry in journal)

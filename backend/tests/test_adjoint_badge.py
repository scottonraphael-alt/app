"""Badge « Adjoint » du tableau de bord : drapeau de session purement esthétique."""
import security_harness as h

from routers import auth, tickets

ADJOINT_ROLE_ID = "1502192430387040407"


def _setup():
    h.reset_db()
    h.reset_discord()


def test_session_flags_adjoint_role():
    _setup()
    h.fake_discord.member_roles[h.USER_IDS["helper"]].append(ADJOINT_ROLE_ID)
    client = h.make_client(auth.router)

    session = client.get("/api/auth/session", cookies=h.session_cookies("helper")).json()

    assert session["authenticated"] is True
    assert session["is_adjoint"] is True


def test_session_without_adjoint_role():
    _setup()
    client = h.make_client(auth.router)

    session = client.get("/api/auth/session", cookies=h.session_cookies("helper")).json()

    assert session["is_adjoint"] is False


def test_adjoint_role_alone_gives_no_access():
    _setup()
    h.fake_discord.member_roles[h.USER_IDS["member"]] = [ADJOINT_ROLE_ID]

    session = h.make_client(auth.router).get("/api/auth/session", cookies=h.session_cookies("member")).json()
    listing = h.make_client(tickets.router).get("/api/tickets", cookies=h.session_cookies("member"))

    assert session["authenticated"] is False
    assert listing.status_code == 403

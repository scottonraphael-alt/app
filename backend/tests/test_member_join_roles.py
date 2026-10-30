from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
import security_harness as h
from services import member_join_roles as roles


@pytest.fixture
def member(monkeypatch):
    class Role:
        managed=False
        def __init__(self,ident):self.id=ident
        def __ge__(self,other):return False
    catalog={ident:Role(ident) for ident in roles.ROLE_IDS}
    guild=SimpleNamespace(id=int(h.GUILD_ID),get_role=catalog.get,
        me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True),top_role=object()))
    monkeypatch.setattr(roles,'audit',AsyncMock())
    return SimpleNamespace(id=1,bot=False,guild=guild,roles=[],add_roles=AsyncMock())


def test_all_seven_roles_added_atomically(member):
    h.run(roles.assign(member))
    assert [call.args[0].id for call in member.add_roles.await_args_list]==list(roles.ROLE_IDS)
    assert all(call.kwargs['atomic'] for call in member.add_roles.await_args_list)
    assert roles.audit.await_args.kwargs['failed_role_ids']==[]


def test_existing_roles_preserved(member):
    member.roles=[member.guild.get_role(roles.ROLE_IDS[0]),SimpleNamespace(id=999)]
    h.run(roles.assign(member))
    assert member.add_roles.await_count==6
    assert [role.id for role in member.roles]==[roles.ROLE_IDS[0],999]


@pytest.mark.parametrize('other', ['bot','guild'])
def test_only_human_members_of_configured_guild(member,other):
    if other=='bot':member.bot=True
    else:member.guild.id=2
    h.run(roles.assign(member))
    member.add_roles.assert_not_awaited()


def test_one_missing_role_does_not_block_others(member):
    original=member.guild.get_role
    member.guild.get_role=lambda ident:None if ident==roles.ROLE_IDS[0] else original(ident)
    h.run(roles.assign(member))
    assert member.add_roles.await_count==6
    assert roles.audit.await_args.kwargs['failed_role_ids']==[str(roles.ROLE_IDS[0])]


def test_missing_manage_roles_is_logged_without_mutation(member):
    member.guild.me.guild_permissions.manage_roles=False
    h.run(roles.assign(member))
    member.add_roles.assert_not_awaited()
    assert len(roles.audit.await_args.kwargs['failed_role_ids'])==7

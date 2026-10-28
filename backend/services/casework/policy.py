"""One fresh role policy for API, archive files and member timeline."""
import os
from dataclasses import dataclass, field
from fastapi import HTTPException
import config
from services.discord_service import DiscordService

KINDS = ('verification', 'summons', 'contact_staff', 'bubble', 'support')
LABELS = {'verification': 'Vérifications', 'summons': 'Convocations',
          'contact_staff': 'Contacts Staff', 'bubble': 'Bulles d’échange', 'support': 'Soutiens'}
PREFIXES = {
    'verification': ('📋・｜verification-', '🎫・｜vérif-', '⚜️・｜vérif-'),
    'summons': ('🛡️・｜convocation-', '🎫・｜convoc-', '🚧・｜convoc-', '⚜️・｜convoc-'),
    'contact_staff': ('💬・｜contact-staff-', '🔒・｜contact-staff-', '🎫・｜cstaff-', '⚜️・｜cstaff-'),
    'bubble': ('🫧・｜discussion-', '🎫・｜bulle-', '🫧・｜bulle-', '⚜️・｜bulle-'),
    'support': ('🌸・｜soutien-', '🌸・｜iris-soutien-'),
}


def ids(value):
    return frozenset(x.strip() for x in value.split(',') if x.strip().isascii() and x.strip().isdigit())


@dataclass(frozen=True)
class Settings:
    enabled: bool = field(default_factory=lambda: os.getenv('CASEWORK_ENABLED', 'true').lower() == 'true')
    guild_id: str = field(default_factory=lambda: str(config.DISCORD_GUILD_ID or ''))
    contact_categories: frozenset = field(default_factory=lambda: ids(os.getenv('CASEWORK_CONTACT_CATEGORY_IDS', '1081957992896942166')))
    source_bot_ids: frozenset = field(default_factory=lambda: ids(os.getenv('CASEWORK_SOURCE_BOT_IDS', '1425117786354483263')))
    managed_kinds: frozenset = field(default_factory=lambda: frozenset(KINDS[:-1]))
    suspended_categories: frozenset = field(default_factory=lambda: ids(os.getenv('CASEWORK_SUSPENDED_CATEGORY_IDS', '')))
    max_file_bytes: int = 50 * 1024 * 1024

    def categories(self, kind):
        if kind == 'support':
            return frozenset(config.ALLOWED_TICKET_CATEGORY_IDS) | ids(os.getenv('CASEWORK_SUPPORT_CATEGORY_ID',''))
        return self.contact_categories | ids(os.getenv("CASEWORK_NATIVE_CATEGORY_ID",""))


def admin_role():
    # DISCORD_ADMIN_ROLE_ID historically designates the Helper coordinator in Iris.
    # Use the actual server Administrator role already used by permanent-ban protection.
    return os.getenv('CASEWORK_ADMIN_ROLE_ID', config.SANCTION_PERMANENT_BAN_ADMIN_ROLE_ID).strip()


def leadership(roles):
    return bool(roles & {admin_role(), str(config.DISCORD_RESPONSABLE_ROLE_ID or '')} - {''})


def can_read(roles, row):
    if row.get('kind') not in KINDS or row.get('visibility') not in ('staff', 'leadership', 'restricted'):
        return False
    if row.get('visibility') == 'restricted':
        return bool(admin_role() and admin_role() in roles)
    if row.get('visibility') == 'leadership':
        return leadership(roles)
    if row.get('kind') == 'support':
        return leadership(roles) or bool(roles & {
            str(config.DISCORD_STAFF_ROLE_ID or ''), str(config.DISCORD_HELPER_ROLE_ID or ''),
            str(config.DISCORD_HELPER_ROLE2_ID or '')} - {''})
    return leadership(roles) or bool(config.DISCORD_STAFF_ROLE_ID and str(config.DISCORD_STAFF_ROLE_ID) in roles)


async def fresh_roles(actor_id):
    return {str(x) for x in await DiscordService().fetch_member_role_ids(str(actor_id))}


async def authorize(actor_id, row):
    roles = await fresh_roles(actor_id)
    if not can_read(roles, row):
        # Same response for absent and inaccessible dossiers.
        raise HTTPException(404, 'Dossier introuvable ou inaccessible.')
    return roles


def scope(roles, guild_id, kind=None):
    allowed = [k for k in KINDS if can_read(roles, {'kind': k, 'visibility': 'staff'})]
    if kind is not None:
        allowed = [kind] if kind in allowed else []
    query = {'guild_id': guild_id, 'kind': {'$in': allowed}}
    visible = ['staff']
    if leadership(roles):
        visible.append('leadership')
    if admin_role() and admin_role() in roles:
        visible.append('restricted')
    query['visibility'] = {'$in': visible}
    return query


def detect(name):
    matches = [kind for kind, prefixes in PREFIXES.items() if any(name.startswith(p) for p in prefixes)]
    return matches[0] if len(matches) == 1 else None


def visibility(kind, name):
    if kind=='contact_staff' and name.startswith('🔒・｜contact-staff-'):return 'leadership'
    if name.startswith('⚜️'):
        return 'leadership' if kind == 'contact_staff' else 'restricted'
    return 'staff'


def can_assign(roles, row):
    if not can_read(roles, row):
        return False
    if row.get('kind') == 'support':
        return bool(roles & {str(config.DISCORD_HELPER_ROLE_ID or ''), str(config.DISCORD_HELPER_ROLE2_ID or '')} - {''})
    return True


def may_reassign(roles, row):
    return leadership(roles) or bool(row.get('kind') == 'support' and config.DISCORD_ADMIN_ROLE_ID
                                     and str(config.DISCORD_ADMIN_ROLE_ID) in roles)

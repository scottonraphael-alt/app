"""Conservative archive normalizer; consumes snapshots, never contacts Discord.

A future transport must enumerate active AND archived private threads with pagination.
Only explicitly identified members and trusted bot messages are accepted. Ambiguity is
reported for human review, never converted into a refusal or a fabricated submission date.
"""
import re
from datetime import datetime
from models.verification import Answers
from services import verification_service as service

ARCHIVE_PARENT='1226848987559100458'
LABELS={'nom':'name','pseudo':'name','âge':'age','age':'age','raison':'reason',
        'motif de venue':'reason','avis sur la psychiatrie':'psychiatry','avis':'psychiatry',
        'règlement':'rules','reglement':'rules'}


def text_blocks(message):
    parts=[message.get('content','')]
    for embed in message.get('embeds',[]):
        parts.extend([embed.get('title',''),embed.get('description','')])
        for field in embed.get('fields',[]):parts.append(f"{field.get('name','')} :\n{field.get('value','')}")
    def walk(components):
        for block in components:
            if block.get('type')==10:parts.append(block.get('content',''))
            walk(block.get('components',[]))
    walk(message.get('components',[]))
    return '\n'.join(part for part in parts if isinstance(part,str) and part).strip()


def normalize(message,thread,*,trusted_bot_ids):
    if str(thread.get('parent_id'))!=ARCHIVE_PARENT or str(thread.get('guild_id'))!=service.guild():
        return {'issue':'untrusted_location'}
    if str(message.get('author',{}).get('id')) not in {str(x) for x in trusted_bot_ids} or not message.get('author',{}).get('bot'):
        return {'issue':'untrusted_author'}
    if not str(message.get('id','')).isdigit() or str(message.get('channel_id'))!=str(thread.get('id')):
        return {'issue':'untrusted_source'}
    text=text_blocks(message)
    # Do not mistake the moderator mention or decision author for the candidate.
    ids=set(re.findall(r'(?im)^\s*(?:\*\*)?(?:ID(?: du membre)?|Identifiant(?: du membre)?)\s*:?\s*(?:\*\*)?\s*[` ]*(\d{17,20})\b',text))
    if len(ids)!=1:return {'issue':'missing_or_ambiguous_member'}
    clean=re.sub(r'\*\*|```(?:\w+)?|^>\s?', '',text,flags=re.M)
    labels='|'.join(re.escape(x) for x in sorted(LABELS,key=len,reverse=True))
    pattern=re.compile(rf'(?im)^\s*({labels})\s*:\s*')
    matches=list(pattern.finditer(clean));answers={}
    for index,match in enumerate(matches):
        value=clean[match.end():matches[index+1].start() if index+1<len(matches) else len(clean)].strip()
        # Only a standalone labelled section is parsed. Unknown trailing layout stays partial.
        answers[LABELS[match.group(1).lower()]]=value
    age=re.fullmatch(r'(13\s*[-–]\s*15|16\s*[-–]\s*17|18\s*[-–]\s*25|26\s*(?:\+|ans et plus))(?:\s*ans)?',answers.get('age',''),re.I)
    if age:answers['age']=re.sub(r'\s','',age[1]).replace('–','-').replace('ansetplus','+')
    if answers.get('rules','').lower() in ('oui','accepté','accepte','true','✅'):answers['rules']=True
    decisions=set()
    for label,status in [('validé','approved'),('accepté','approved'),('refusé','refused'),('sans réponse','closed'),('clôturé','closed')]:
        if re.search(rf'(?im)^\s*(?:statut|décision)\s*:\s*{label}\s*$',clean):decisions.add(status)
    status=next(iter(decisions)) if len(decisions)==1 else None
    submitted_at=None
    # Discord message date is the archive-copy date, not necessarily the submission date.
    source_date=message.get('verification_submitted_at')
    if source_date:
        try:
            parsed=datetime.fromisoformat(source_date.replace('Z','+00:00'))
            if parsed.tzinfo:submitted_at=parsed.isoformat()
        except (ValueError,TypeError):pass
    try:Answers.model_validate(answers);completeness='complete'
    except ValueError:completeness='partial'
    return {'member':{'id':ids.pop()},'answers':answers,'source':f'discord:{thread["id"]}:{message["id"]}',
            'submitted_at':submitted_at,'import_status':status,'completeness':completeness}


async def ingest(message,thread,*,trusted_bot_ids):
    parsed=normalize(message,thread,trusted_bot_ids=trusted_bot_ids)
    if 'issue' in parsed:return parsed
    completeness=parsed.pop('completeness')
    result=await service.submit(**parsed,imported=True)
    # Completeness is descriptive; it never auto-qualifies an archive as an AI example.
    return {'result':result,'parsed_completeness':completeness}

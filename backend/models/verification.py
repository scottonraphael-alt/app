"""Verification contracts. No client-supplied permissions or action origin."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

AGE_GROUPS=('13-15','16-17','18-25','26+')
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)

class Answers(Strict):
    name:str=Field(min_length=1,max_length=40)
    age:Literal['13-15','16-17','18-25','26+']
    reason:str=Field(min_length=50,max_length=250)
    psychiatry:str=Field(min_length=120,max_length=1000)
    rules:Literal[True]

class Action(Strict):
    action:Literal['claim','approve','ticket','close','clarify','refuse','kick','ban','second_opinion','training','assign']
    assignee_id:str|None=Field(default=None,pattern=r'^[0-9]{17,20}$')
    revision:int=Field(ge=0)
    request_id:str=Field(min_length=8,max_length=80,pattern=r'^[A-Za-z0-9_:\-]+$')
    reason:str=Field(default='',max_length=1500)
    rationale:str=Field(default='',max_length=4000)
    topics:list[Literal['reason','psychiatry']]=Field(default_factory=list,max_length=2)
    training:bool=False

    @field_validator('rationale','reason')
    @classmethod
    def printable(cls,value):
        if '\x00' in value:raise ValueError('Caractère non autorisé.')
        return value

class DeleteForm(Strict):
    revision:int=Field(ge=0)
    confirmation:str=Field(min_length=1,max_length=80)
    reason:str=Field(min_length=10,max_length=1000)

class ExampleReview(Strict):
    revision:int=Field(ge=0)
    enabled:bool
    reason:str=Field(min_length=20,max_length=1500)

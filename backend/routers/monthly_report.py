from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from models.ticket import AuthenticatedHelper
from services import monthly_report as svc
from services.auth_service import current_responsable

router = APIRouter(prefix="/responsable/reports", tags=["rapport-mensuel"])


def _month_or_default(month: str | None) -> str:
    if month is None:
        return svc.previous_month(svc.current_month())
    if not svc.valid_month(month):
        raise HTTPException(status_code=422, detail="Mois invalide (format YYYY-MM).")
    if month > svc.current_month():
        raise HTTPException(status_code=422, detail="Ce mois n'est pas encore commencé.")
    return month


@router.get("/months")
async def report_months(_: AuthenticatedHelper = Depends(current_responsable)):
    return {"months": await svc.list_months()}


@router.get("/monthly")
async def monthly_report(
    month: str | None = Query(default=None, max_length=7),
    refresh: int = Query(default=0, ge=0, le=1),
    _: AuthenticatedHelper = Depends(current_responsable),
):
    return await svc.get_report(_month_or_default(month), refresh=bool(refresh))


@router.get("/monthly.csv")
async def monthly_report_csv(
    month: str | None = Query(default=None, max_length=7),
    _: AuthenticatedHelper = Depends(current_responsable),
):
    month = _month_or_default(month)
    body = svc.report_to_csv(await svc.get_report(month))
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="rapport-{month}.csv"', "Cache-Control": "no-store"},
    )

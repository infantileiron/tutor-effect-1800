from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
import json
from src.config.database import get_db
from src.utils.security import current_user,editor
from src.schemas.business import SupplementDrawInput,SupplementResponseInput
from src.services import supplement
from src.models.entities import Plan
router=APIRouter()
def _plan_or_404(db,plan_id):
    if not db.get(Plan,plan_id): raise HTTPException(404,'辅导方案不存在')
@router.get('/supplements')
def listing(plan_id:int|None=None,db=Depends(get_db),user=Depends(current_user)):
    return [supplement.draw_payload(db,d) for d in supplement.list_draws(db,plan_id)]
@router.post('/supplements',status_code=201)
def create(data:SupplementDrawInput,db=Depends(get_db),user=Depends(editor)):
    _plan_or_404(db,data.plan_id)
    draw=supplement.create_draw(db,data.plan_id,data.per_stratum,user.email)
    return supplement.draw_payload(db,draw,include_roster=True)
@router.get('/supplements/{draw_id}')
def detail(draw_id:int,db=Depends(get_db),user=Depends(current_user)):
    return supplement.draw_payload(db,supplement.get_draw(db,draw_id),include_roster=True)
@router.post('/supplements/{draw_id}/execute')
def execute(draw_id:int,db=Depends(get_db),user=Depends(editor)):
    return supplement.draw_payload(db,supplement.execute_draw(db,supplement.get_draw(db,draw_id)),include_roster=True)
@router.post('/supplements/{draw_id}/issue')
def issue(draw_id:int,db=Depends(get_db),user=Depends(editor)):
    return supplement.draw_payload(db,supplement.issue_draw(db,supplement.get_draw(db,draw_id)),include_roster=True)
@router.get('/supplements/samples/{sample_id}')
def sample_detail(sample_id:int,db=Depends(get_db),user=Depends(current_user)):
    return supplement.sample_history(db,sample_id)
@router.post('/supplements/samples/{sample_id}/response')
def respond(sample_id:int,data:SupplementResponseInput,db=Depends(get_db),user=Depends(editor)):
    sample=supplement.register_response(db,sample_id,data.outcome,data.retest_score,data.note,user.email,data.expected_version)
    return supplement.draw_payload(db,supplement.get_draw(db,sample.draw_id),include_roster=True)
@router.get('/supplements/plans/{plan_id}/analysis')
def plan_analysis(plan_id:int,db=Depends(get_db),user=Depends(current_user)):
    result=supplement.analysis_for_plan(db,plan_id)
    if not result: raise HTTPException(404,'该方案还没有补测抽样')
    return result
@router.get('/supplements/{draw_id}/export')
def export(draw_id:int,db=Depends(get_db),user=Depends(current_user)):
    draw=supplement.get_draw(db,draw_id)
    payload=supplement.draw_payload(db,draw,include_roster=True)
    payload['design']=draw.design
    payload['exported_at']=supplement.now()
    return Response(json.dumps(payload,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="supplement-draw-{draw_id}.json"'})

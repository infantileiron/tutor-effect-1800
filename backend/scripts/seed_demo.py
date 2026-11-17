import random,json
from datetime import datetime,timezone
from sqlalchemy import select,func
from src.config.database import Base,engine,SessionLocal
from src.models.entities import User,Student,Plan,Report,SupplementDraw,SupplementSample
from src.utils.security import hash_password
from src.services.statistics import welch
from src.services import supplement

def seed():
    Base.metadata.create_all(engine)
    rng=random.Random(20261115)
    with SessionLocal() as db:
        for role in ('admin','analyst','viewer'):
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)): db.add(User(email=email,role=role,password_hash=hash_password('Demo123!')))
        for i in range(160):
            code=f'ZX-2026-{i+1:03}'
            group='control' if i<80 else 'intervention'
            score=round(min(100,max(0,rng.gauss(72 if group=='control' else 78,8))),1)
            absent=i%23==0
            if not db.scalar(select(Student).where(Student.code==code)):
                db.add(Student(code=code,name=f'学员{i+1:03}',campus=['城东','城西','滨江','高新'][i%4],group=group,score=None if absent else score,absent=absent))
        title='2026秋季 · 晚间小组辅导'
        plan=db.scalar(select(Plan).where(Plan.title==title))
        if not plan:
            plan=Plan(title=title,campus='全部',exclude_absent=True,description='评估每周两次小组辅导与常规自习的期末成绩差异。缺考学员排除；观察性结果不直接证明因果。');db.add(plan);db.flush()
        db.commit()
        # 演示：固定种子、每层 2 名，名单已抽取并发出，部分回应可覆盖空层、拒绝和未回应。
        if not db.scalar(select(SupplementDraw).where(SupplementDraw.plan_id==plan.id)):
            draw=supplement.create_draw(db,plan.id,2,'analyst@demo.local',seed='5eed20261115c0ffee5eed20261115c0')
            supplement.execute_draw(db,draw);supplement.issue_draw(db,draw)
            rows=sorted(supplement.draw_samples(db,draw.id),key=lambda r:r.id)
            if rows:
                supplement.register_response(db,rows[0].id,'responded',round(min(100,max(0,rng.gauss(80,6))),1),'演示：愿意返校补测。','analyst@demo.local',0)
            if len(rows)>1: supplement.register_response(db,rows[1].id,'refused',None,'演示：拒绝返校，不补抽。','analyst@demo.local',0)
            if len(rows)>2: supplement.register_response(db,rows[2].id,'unreachable',None,'演示：电话失联，不补抽。','analyst@demo.local',0)
        snapshot=supplement.analysis_for_plan(db,plan.id)
        if not db.scalar(select(Report).where(Report.plan_id==plan.id)):
            result=welch(db.scalars(select(Student).order_by(Student.code)).all(),plan)
            if snapshot:
                result['supplement']=snapshot
                result['supplement_method']='分层补测抽样+回应调整概率加权；未回应者不补抽，以 0–100 分识别区间报告组均差。'
                result['population_difference']=snapshot['difference']
            db.add(Report(plan_id=plan.id,status='completed',result=result,supplement_snapshot=snapshot,created_at=datetime.now(timezone.utc).isoformat(),conclusion='干预组均分较高。建议保留教学点分层观察，并在下一轮随机分组验证。',published=True));db.commit()
        print(json.dumps({table:db.scalar(select(func.count()).select_from(model)) for table,model in [('users',User),('students',Student),('plans',Plan),('reports',Report),('supplement_draws',SupplementDraw),('supplement_samples',SupplementSample)]}))
if __name__=='__main__': seed()

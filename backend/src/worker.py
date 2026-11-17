import time,traceback
from pathlib import Path
from sqlalchemy import select
from src.config.database import SessionLocal
from src.models.entities import Report,Plan,Student
from src.services.reports import queue
from src.services.statistics import welch
print('tutor effect worker started',flush=True)
while True:
    Path('/tmp/worker-heartbeat').touch()
    try:
        queue.brpop('tutor:reports',timeout=2)
        with SessionLocal() as db:
            task=db.scalar(select(Report).where(Report.status=='queued').order_by(Report.id).with_for_update(skip_locked=True))
            if not task: continue
            task.status='running';db.commit()
            try:
                plan=db.get(Plan,task.plan_id)
                result=welch(db.scalars(select(Student).order_by(Student.code)).all(),plan)
                # 聚合冻结应考名册与受理时封存的补测回应；补测者不当作全体缺考者。
                result['supplement']=task.supplement_snapshot
                if task.supplement_snapshot:
                    diff=task.supplement_snapshot['difference']
                    result['supplement_method']='分层补测抽样+回应调整概率加权；未回应者不补抽，以 0–100 分识别区间报告组均差。'
                    result['population_difference']=diff
                task.result=result
                task.status='completed'
            except Exception as e:
                task.error=str(e);task.status='failed'
            db.commit()
            print(f'report={task.id} status={task.status}',flush=True)
    except Exception:
        traceback.print_exc();time.sleep(2)

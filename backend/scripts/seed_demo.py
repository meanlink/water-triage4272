import time, json
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, PatrolBatch, Dispatch
from src.services.business import metadata, seed_records, analyze, FEATURES
from src.services.reports import deliver
from src.services import patrol as patrol_service
from src.services.triage_rule import validate_patrol_records
from src.utils.security import hash_password
from src.utils.serialization import checksum
def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        # 无标签待巡批次与首周派单：仅用已批准试验的规则快照，不重新训练。
        baseline=db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name']))
        patrol_name='城东无标签待巡批次 · 2026-11'
        pb=db.scalar(select(PatrolBatch).where(PatrolBatch.name==patrol_name))
        if not pb:
            raw=seed_records()
            unlabeled=[{'segment_id':f"NC-P{i+1:03}", **{k: r[k] for k in FEATURES}} for i,r in enumerate(raw[:90])]
            clean=validate_patrol_records(unlabeled)
            admin=db.scalar(select(User).where(User.role=='admin'))
            pb=PatrolBatch(name=patrol_name,source='patrol-2026-11-unlabeled.csv',records=clean,
                           checksum=checksum(clean),created_by=admin.id,created_at=time.time()-1800)
            db.add(pb);db.flush()
        if baseline and baseline.result.get('rule_artifact') and not db.scalar(select(Dispatch).where(Dispatch.name=='首周巡检派单 · 原规则快照')):
            admin=db.scalar(select(User).where(User.role=='admin'))
            class _Data: pass
            payload=_Data(); payload.name='首周巡检派单 · 原规则快照'; payload.job_id=baseline.id
            payload.patrol_batch_id=pb.id; payload.quota=12
            dispatch=patrol_service.create_dispatch(db,payload,admin)
            patrol_service.write_dispatch_files(dispatch)
            db.add(Audit(actor='seed',action='demo.dispatch',detail={'dispatch':dispatch.id},at=time.time()))
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit,PatrolBatch,Dispatch]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from src.config.database import get_db
from src.config.settings import ARTIFACT_DIR
from src.models import Dispatch, PatrolBatch
from src.schemas.patrol import DispatchInput, PatrolBatchInput
from src.middlewares.auth import can_write, current_user
from src.services import patrol
from src.services.audit import record
from src.utils.serialization import dispatch_dict, patrol_batch_dict

router = APIRouter()


@router.get('/patrol-batches')
def list_batches(db=Depends(get_db), user=Depends(current_user)):
    return [patrol_batch_dict(b)
            for b in db.scalars(select(PatrolBatch).order_by(PatrolBatch.id.desc()))]


@router.post('/patrol-batches', status_code=201)
def create_batch(data: PatrolBatchInput, db=Depends(get_db), user=Depends(can_write)):
    batch = patrol.create_batch(db, data, user)
    record(db, user.email, 'patrol_batch.create', {'id': batch.id, 'rows': len(batch.records)})
    db.commit()
    return patrol_batch_dict(batch)


@router.get('/patrol-batches/{id}')
def get_batch(id: int, db=Depends(get_db), user=Depends(current_user)):
    batch = db.get(PatrolBatch, id)
    if not batch:
        raise HTTPException(404, '待巡批次不存在')
    return {**patrol_batch_dict(batch), 'records': batch.records}


@router.get('/dispatches/list')
def list_dispatches(db=Depends(get_db), user=Depends(current_user)):
    return [dispatch_dict(d)
            for d in db.scalars(select(Dispatch).order_by(Dispatch.id.desc()).limit(100))]


@router.post('/dispatches', status_code=201)
def create_dispatch(data: DispatchInput, db=Depends(get_db), user=Depends(can_write)):
    dispatch = patrol.create_dispatch(db, data, user)
    record(db, user.email, 'dispatch.create',
           {'id': dispatch.id, 'job_id': dispatch.job_id,
            'patrol_batch_id': dispatch.patrol_batch_id, 'quota': dispatch.quota})
    db.commit()
    # 文件在事务提交后生成，内容只来自已落库的不可变快照。
    patrol.write_dispatch_files(dispatch)
    return dispatch_dict(dispatch)


@router.get('/dispatches/{id}')
def get_dispatch(id: int, db=Depends(get_db), user=Depends(current_user)):
    dispatch = db.get(Dispatch, id)
    if not dispatch:
        raise HTTPException(404, '派单不存在')
    return {**dispatch_dict(dispatch),
            'rule_snapshot': dispatch.rule_snapshot,
            'input_records': dispatch.input_records,
            'result': dispatch.result}


@router.get('/dispatches/{id}/download')
def download_dispatch(id: int, format: str = 'csv', db=Depends(get_db),
                      user=Depends(current_user)):
    dispatch = db.get(Dispatch, id)
    if not dispatch:
        raise HTTPException(404, '派单不存在')
    if format not in ('csv', 'json'):
        raise HTTPException(422, '支持 CSV 或 JSON')
    filename = f'dispatch-{id}.json' if format == 'json' else f'dispatch-{id}.csv'
    path = os.path.join(ARTIFACT_DIR, filename)
    if not os.path.exists(path):
        # 兼容历史派单：文件缺失时按库内不可变快照重新生成，结果不变。
        patrol.write_dispatch_files(dispatch)
    return FileResponse(
        path, filename=filename,
        media_type='application/json' if format == 'json' else 'text/csv; charset=utf-8',
    )

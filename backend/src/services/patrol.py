"""无标签待巡批次与巡检派单。

派单不可变：创建时把规则快照、输入记录副本、输入指纹和评分结果一并落库；
之后试验重训、批次新增或数据修改都不会改变已派结果。
"""
import csv
import hashlib
import io
import json
import os
import time

from fastapi import HTTPException
from sqlalchemy import select

from src.config.settings import ARTIFACT_DIR
from src.models import Dispatch, Job, PatrolBatch
from src.services.triage_rule import (
    RuleUnavailableError,
    format_rule_path,
    score_records,
    select_dispatch,
    validate_patrol_records,
)
from src.utils.serialization import checksum


def create_batch(db, data, user):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(PatrolBatch).where(PatrolBatch.name == name)):
        raise HTTPException(409, '该待巡批次名已存在，请修改名称')
    try:
        records = validate_patrol_records(data.records)
    except ValueError as exc:
        # 坏行或重复编号：整批拒绝，不写入任何数据。
        raise HTTPException(422, str(exc))
    batch = PatrolBatch(
        name=name,
        source=data.source,
        records=records,
        checksum=checksum(records),
        created_by=user.id,
        created_at=time.time(),
    )
    db.add(batch)
    db.flush()
    return batch


def _load_rule(job):
    """从已批准试验取规则快照；旧试验无快照时明确说明，绝不重训冒充。"""
    artifact = (job.result or {}).get('rule_artifact')
    if not artifact:
        raise RuleUnavailableError(
            f'试验「{job.name}」创建于规则快照功能上线前，结果中没有可复用的规则快照。'
            '系统不会重新训练来冒充当时的原规则；请新建试验、完成复核并由负责人批准后再派单。'
        )
    return artifact


def create_dispatch(db, data, user):
    job = db.get(Job, data.job_id)
    if not job:
        raise HTTPException(404, '分析任务不存在')
    if job.status != 'completed' or not job.approved:
        raise HTTPException(409, '仅已完成且获批准的试验规则可以用于派单')
    batch = db.get(PatrolBatch, data.patrol_batch_id)
    if not batch:
        raise HTTPException(404, '待巡批次不存在')
    if data.quota > len(batch.records):
        raise HTTPException(422, f'巡检名额 {data.quota} 超过待巡管段总数 {len(batch.records)}')
    try:
        artifact = _load_rule(job)
        scored = score_records(artifact, batch.records)
        ranking, selected = select_dispatch(scored, data.quota)
    except RuleUnavailableError as exc:
        raise HTTPException(422, str(exc))

    # 输入副本与规则快照完整冻结，后续任何改动都不影响本派单。
    input_records = [dict(row) for row in batch.records]
    input_checksum = checksum(input_records)
    for item in ranking:
        item['rule_path_text'] = format_rule_path(item['rule_path'])

    result = {
        'summary': (
            f'依据试验「{job.name}」的原规则快照，对 {len(batch.records)} 段无标签待巡管段评分，'
            f'按巡检名额 {data.quota} 段取风险最高者；入选清单按管段编号排序。'
        ),
        'quota': data.quota,
        'candidate_count': len(batch.records),
        'selected_count': len(selected),
        'tie_note': '风险相同时按管段编号升序决胜；入选清单按编号排序便于现场核对。',
        'columns': [
            {'key': 'rank', 'label': '风险排名'},
            {'key': 'segment_id', 'label': '管段编号'},
            {'key': 'risk_pct', 'label': '规则风险率(%)'},
            {'key': 'leaf_node', 'label': '命中叶节点'},
            {'key': 'selected', 'label': '是否入选'},
            {'key': 'reason', 'label': '入选/未入选原因'},
            {'key': 'rule_path_text', 'label': '命中规则路径'},
        ],
        'ranking': ranking,
        'selected': selected,
    }
    dispatch = Dispatch(
        name=data.name.strip(),
        job_id=job.id,
        patrol_batch_id=batch.id,
        quota=data.quota,
        status='issued',
        rule_snapshot=artifact,
        rule_params=dict(job.params),
        input_checksum=input_checksum,
        input_records=input_records,
        result=result,
        created_by=user.id,
        created_at=time.time(),
    )
    db.add(dispatch)
    db.flush()
    return dispatch


def _csv_escape(value):
    if isinstance(value, bool):
        value = '是' if value else '否'
    if isinstance(value, (int, float)):
        return value
    text = str(value)
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text


def dispatch_csv(dispatch):
    out = io.StringIO()
    out.write('﻿')
    cols = dispatch.result['columns']
    writer = csv.writer(out)
    writer.writerow([c['label'] for c in cols])
    for row in dispatch.result['ranking']:
        writer.writerow([_csv_escape(row.get(c['key'], '')) for c in cols])
    return out.getvalue().encode('utf-8')


def dispatch_json_payload(dispatch):
    return {
        'dispatch': {
            'id': dispatch.id,
            'name': dispatch.name,
            'job_id': dispatch.job_id,
            'patrol_batch_id': dispatch.patrol_batch_id,
            'quota': dispatch.quota,
            'status': dispatch.status,
            'input_checksum': dispatch.input_checksum,
            'created_at': dispatch.created_at,
        },
        'rule_params_at_issue': dispatch.rule_params,
        'rule_snapshot_at_issue': dispatch.rule_snapshot,
        'input_records_at_issue': dispatch.input_records,
        'result': dispatch.result,
    }


def write_dispatch_files(dispatch):
    """把派单快照写入与分发归档相同的产物目录，返回 (csv路径, json路径, 校验和)。"""
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    csv_name = f'dispatch-{dispatch.id}.csv'
    json_name = f'dispatch-{dispatch.id}.json'
    csv_bytes = dispatch_csv(dispatch)
    json_bytes = json.dumps(
        dispatch_json_payload(dispatch), ensure_ascii=False, allow_nan=False, indent=2
    ).encode('utf-8')
    with open(os.path.join(ARTIFACT_DIR, csv_name), 'wb') as f:
        f.write(csv_bytes)
    with open(os.path.join(ARTIFACT_DIR, json_name), 'wb') as f:
        f.write(json_bytes)
    checksum_hex = hashlib.sha256(csv_bytes).hexdigest()
    return csv_name, json_name, checksum_hex

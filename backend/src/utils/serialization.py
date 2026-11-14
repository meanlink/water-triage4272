import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j):
    return {k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def patrol_batch_dict(b):
    return {'id':b.id,'name':b.name,'source':b.source,'rows':len(b.records),'checksum':b.checksum,'created_at':b.created_at}
def dispatch_dict(d):
    return {'id':d.id,'name':d.name,'job_id':d.job_id,'patrol_batch_id':d.patrol_batch_id,
            'quota':d.quota,'status':d.status,'input_checksum':d.input_checksum,'rule_params':d.rule_params,
            'selected_count':d.result.get('selected_count'),'candidate_count':d.result.get('candidate_count'),
            'created_at':d.created_at}

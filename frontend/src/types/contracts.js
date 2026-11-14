/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} Dataset */
/** @typedef {{id:number,name:string,dataset_id:number,status:string,result:Object,approved:boolean}} AnalysisJob */
/** @typedef {{id:number,name:string,job_id:number,destination:string,next_run:number,enabled:boolean}} ReportSchedule */
/** @typedef {{id:number,name:string,source:string,rows:number,checksum:string}} PatrolBatch */
/** @typedef {{id:number,name:string,job_id:number,patrol_batch_id:number,quota:number,status:string,input_checksum:string,selected_count:number,candidate_count:number}} Dispatch */
export {};

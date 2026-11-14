import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const patrolBatches={list:()=>api('/patrol-batches'),get:id=>api('/patrol-batches/'+id),create:data=>api('/patrol-batches',{method:'POST',body:JSON.stringify(data)})};
export const dispatches={list:()=>api('/dispatches/list'),get:id=>api('/dispatches/'+id),create:data=>api('/dispatches',{method:'POST',body:JSON.stringify(data)})};

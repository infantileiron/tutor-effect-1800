import{request,post}from'./client.js';
export const getSupplements=()=>request('/supplements');
export const getSupplement=id=>request('/supplements/'+id);
export const drawSupplement=(data)=>post('/supplements',data);
export const executeSupplement=id=>post(`/supplements/${id}/execute`,{});
export const issueSupplement=id=>post(`/supplements/${id}/issue`,{});
export const respondSupplement=(sampleId,data)=>post(`/supplements/samples/${sampleId}/response`,data);
export const getSample=id=>request('/supplements/samples/'+id);

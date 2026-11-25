"use strict";
const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const state = {csrf:"", config:{}, presets:[], preset:"pose", scan:null, jobId:null, jobs:[], worker:{}, page:0, items:[], total:0, gridKey:"", stopped:false, connected:false, submitting:false};
let folderTarget = "folder", folderParent = "", folderCurrent = "", folderRequest = 0, timer, toastTimer;
const pageSize = 24;
const labels = {ready:"Ready",pending:"Waiting",running:"Processing",done:"Generated",cached:"Reused",failed:"Failed",queued:"Queued",completed:"Completed",completed_with_errors:"Completed with errors",paused:"Paused",pausing:"Pausing",cancelled:"Cancelled",cancelling:"Cancelling"};
function statusLabel(value) { return labels[value] || value; }
function alertError(error) { if(error.connection) return; $("errorBanner").textContent = error.message || String(error); $("errorBanner").hidden = false; }
function clearError() { $("errorBanner").hidden = true; }
function toast(text) { clearTimeout(toastTimer); $("toast").textContent=text; $("toast").hidden=false; toastTimer=setTimeout(() => $("toast").hidden=true, 3500); }
const launchInstructions = "Open D:\\Local_Image_Captioner\\Launch Caption Studio.cmd, then click Reconnect.";
function connectionError(message, title="Local server unavailable") {
  state.connected=false;
  $("connectionBanner").hidden=false;
  $("connectionTitle").textContent=title;
  $("connectionMessage").textContent=message;
  $("modelBadge").textContent=state.stopped?"App stopped":"Server disconnected";
  $("startButton").disabled=true;
  const error=new Error(message);
  error.connection=true;
  return error;
}
async function api(path, options={}) {
  let response;
  try {
    response = await fetch(path, {credentials:"same-origin", ...options, headers:{"Content-Type":"application/json", "X-CSRF-Token":state.csrf, ...(options.headers || {})}});
  } catch (_) {
    let message="Cannot reach Caption Studio's local server. "+launchInstructions;
    if(path==="/api/jobs" && options.method==="POST") message+=" Check batch history before submitting again; the request may have reached the server.";
    throw connectionError(message);
  }
  const data = await response.json().catch(()=>({detail:"The local server returned an unexpected response. Reconnect and try again."}));
  if(response.status===401 || (response.status===403 && String(data.detail).includes("session token"))) {
    throw connectionError("The local server restarted. Click Reconnect to restore your connection. Your saved batches and settings are preserved.", "Reconnect to Caption Studio");
  }
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : Array.isArray(data.detail) ? data.detail.map(x => x.msg).join("; ") : "The request could not be completed.";
    throw new Error(detail);
  }
  if(!state.connected) {
    state.connected=true;
    $("connectionBanner").hidden=true;
    $("startButton").disabled=state.submitting;
  }
  return data;
}
async function reconnect() {
  const buttons=[$("reconnectButton"),$("folderReconnect")];
  buttons.forEach(button=>{button.disabled=true;button.textContent="Connecting…";});
  try {
    // Refresh the local session cookie before reloading. Do not replay POSTs.
    const response=await fetch("/",{credentials:"same-origin",cache:"no-store"});
    if(!response.ok) throw new Error("Server unavailable");
    if(state.presets.length) saveDraft();
    location.reload();
  } catch (_) {
    const error=connectionError("Cannot reach Caption Studio's local server. "+launchInstructions);
    if($("folderDialog").open) {
      $("folderError").textContent=error.message;$("folderError").hidden=false;
      $("folderReconnect").hidden=false;
    }
  } finally {
    buttons.forEach(button=>{button.disabled=false;button.textContent="Reconnect";});
  }
}
function preset() { return state.presets.find(p => p.id === state.preset); }
function values() {
  return {folder:$("folder").value.trim(), recursive:$("recursive").checked, preset:state.preset,
    prompt:$("prompt").value, system_prompt:$("systemPrompt").value, model_path:$("modelPath").value.trim(),
    max_tokens:Number($("maxTokens").value), output_label:$("outputLabel").value.trim(),
    output_directory:$("outputDirectory").value.trim(), write_txt:$("writeTxt").checked,
    character_reference:$("characterReference").checked,
    gender_neutral:$("genderNeutral").checked,
    force:$("force").checked, keep_loaded:$("keepLoaded").checked};
}
function saveDraft() {
  try { const value=values(); value.force=false; localStorage.setItem("caption-studio-draft",JSON.stringify(value)); } catch (_) {}
}
function setPreset(id, keepInstructions=false) {
  state.preset=id;
  const p=preset();
  if (!p) return;
  $("presets").innerHTML=state.presets.map(item => '<button type="button" class="preset" data-preset="'+escapeHtml(item.id)+'" aria-pressed="'+(item.id===id)+'">'+escapeHtml(item.name)+'</button>').join("");
  $("presetSummary").textContent=p.summary;
  if (!keepInstructions) { $("prompt").value=p.prompt; $("systemPrompt").value=p.system_prompt; $("maxTokens").value=p.max_tokens; $("outputLabel").value=p.label; }
  outputHint();
}
function outputHint() {
  const p=state.presets.find(x => x.id==="pose");
  let label=$("outputLabel").value.trim() || "custom";
  const canonical=state.preset==="pose" && p && $("prompt").value.trim()===p.prompt && $("systemPrompt").value.trim()===p.system_prompt && Number($("maxTokens").value)===p.max_tokens && !$("characterReference").checked && !$("genderNeutral").checked;
  const modifiedPose=label==="pose" && !canonical;
  if (modifiedPose) label="pose-custom";
  $("outputExample").textContent="image.png."+label+".json"+($("writeTxt").checked?" + .txt":"");
  $("compatibilityHint").textContent=modifiedPose ? "Modified pose captions use a separate file, preserving the standard fashion-workflow caption." :
    canonical && label==="pose" ? "The standard Pose preset can reuse existing .pose.json files from your fashion workflow." :
    ($("outputDirectory").value.trim() ? "Saved in your output folder, preserving subfolders." : "Saved beside each image. Different output labels keep descriptions separate.");
  $("characterReferencePreview").hidden=!$("characterReference").checked;
}
function applyDraft(draft) {
  if (!draft || !state.presets.some(p=>p.id===draft.preset)) return;
  setPreset(draft.preset);
  const names={folder:"folder",prompt:"prompt",system_prompt:"systemPrompt",model_path:"modelPath",max_tokens:"maxTokens",output_label:"outputLabel",output_directory:"outputDirectory"};
  Object.entries(names).forEach(([key,id])=>{if(draft[key]!==undefined) $(id).value=draft[key];});
  const checks={recursive:"recursive",write_txt:"writeTxt",keep_loaded:"keepLoaded",character_reference:"characterReference",gender_neutral:"genderNeutral"};
  Object.entries(checks).forEach(([key,id])=>{if(draft[key]!==undefined) $(id).checked=draft[key];});
  outputHint();
}
async function scan() {
  clearError();
  const button=$("scanButton");button.disabled=true;button.textContent="Scanning…";
  try {
    state.scan=await api("/api/scan",{method:"POST",body:JSON.stringify({folder:$("folder").value.trim(),recursive:$("recursive").checked})});
    state.jobId=null;state.page=0;state.gridKey="";
    $("scanSummary").textContent=state.scan.total+" images found"+(state.scan.warnings.length?" · "+state.scan.warnings.length+" folders could not be read":"");
    renderBatch();renderHistory();await fetchItems();saveDraft();
  } catch(error) { alertError(error); }
  finally { button.disabled=false;button.textContent="Scan folder"; }
}
async function fetchItems() {
  const selection=(state.jobId || (state.scan && state.scan.id) || "")+":"+state.page;
  let path;
  if(state.jobId) path="/api/jobs/"+state.jobId+"/items";
  else if(state.scan) path="/api/scans/"+state.scan.id+"/items";
  else { state.items=[];state.total=0;renderGrid();return; }
  const data=await api(path+"?offset="+state.page*pageSize+"&limit="+pageSize);
  if(selection!==((state.jobId || (state.scan && state.scan.id) || "")+":"+state.page)) return;
  state.items=data.items;state.total=data.total;
  renderGrid();
}
function renderGrid() {
  const job=state.jobs.find(j=>j.id===state.jobId);
  $("galleryTitle").textContent=job ? "Descriptions" : "Folder preview";
  $("gallerySubtitle").textContent=job ? job.settings.folder : state.scan ? state.scan.folder : "Scan a folder to see your images here.";
  $("imageCount").textContent=state.total+" image"+(state.total===1?"":"s");
  $("emptyState").hidden=state.total>0;
  $("pagination").hidden=state.total===0;
  $("previousPage").disabled=state.page===0;
  $("nextPage").disabled=(state.page+1)*pageSize>=state.total;
  $("pageRange").textContent=(state.page*pageSize+1)+"–"+Math.min((state.page+1)*pageSize,state.total)+" of "+state.total;
  const key=JSON.stringify([state.jobId,state.scan && state.scan.id,state.page,state.items]);
  if(key===state.gridKey) return;
  state.gridKey=key;
  $("imageGrid").innerHTML=state.items.map((item,index)=>{
    const snippet=item.error || item.caption || (item.status==="ready"?"Ready to describe":item.status==="running"?"Reading this image…":"Waiting in the batch");
    return '<button class="image-card" data-index="'+index+'" aria-label="Review '+escapeHtml(item.relative)+'"><div class="thumbnail"><img loading="lazy" src="'+escapeHtml(item.thumbnail)+'" alt="'+escapeHtml(item.relative)+'"><span class="badge '+escapeHtml(item.status)+'">'+escapeHtml(statusLabel(item.status))+'</span></div><div class="image-info"><span class="image-name" title="'+escapeHtml(item.relative)+'">'+escapeHtml(item.relative)+'</span><p class="caption-snippet">'+escapeHtml(snippet)+'</p></div></button>';
  }).join("");
}
function renderHistory() {
  $("jobCount").textContent=state.jobs.length;
  const html=state.jobs.length ? state.jobs.map(job=>{
    const date=new Date(job.created_at).toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});
    return '<button class="history-row '+(job.id===state.jobId?"selected":"")+'" data-job="'+job.id+'"><span class="history-top"><span>'+escapeHtml(job.settings.profile_name)+'</span><span class="tiny-state">'+escapeHtml(statusLabel(job.status))+'</span></span><span class="history-bottom">'+job.processed+" / "+job.total+" images · "+escapeHtml(date)+'</span></button>';
  }).join("") : '<p class="muted empty-history">No batches yet. Your results and progress will be saved here.</p>';
  $("history").innerHTML=html;$("historyModalList").innerHTML=html;
}
function renderWorker() {
  const worker=state.worker;
  const name=worker.loaded_model ? worker.loaded_model.split(/[\\/]/).pop() : "";
  $("modelBadge").textContent=!state.connected?(state.stopped?"App stopped":"Server disconnected"):worker.phase==="loading"?"Loading local model…":worker.phase==="releasing"?"Releasing model…":name?"Model ready · local":"Model unloaded";
  $("loadedModelPath").textContent=worker.loaded_model || "No model loaded";
  $("unloadButton").disabled=!state.connected || !!worker.active_job || !worker.loaded_model;
  $("shutdownButton").disabled=!state.connected || !!worker.active_job;
  $("startButton").disabled=!state.connected || state.submitting;
  if(!state.submitting) $("startButton").textContent=worker.active_job?"Queue new batch":"Start batch";
}
function renderBatch() {
  const job=state.jobs.find(j=>j.id===state.jobId);
  $("batchPanel").hidden=!job;
  if(!job) return;
  $("batchTitle").textContent=job.settings.profile_name+" · "+job.total+" images";
  $("batchStatus").textContent=statusLabel(job.status);$("batchStatus").className="badge "+job.status;
  $("metricDone").textContent=job.counts.done || 0;$("metricCached").textContent=job.counts.cached || 0;
  $("metricErrors").textContent=job.counts.failed || 0;$("metricRemaining").textContent=job.total-job.processed;
  $("progress").max=job.total || 1;$("progress").value=job.processed;$("progressText").textContent=job.processed+" of "+job.total+" processed";
  $("eta").textContent=job.status==="running" && job.eta_seconds ? "~"+Math.max(1,Math.ceil(job.eta_seconds/60))+" min remaining":"";
  const phase=state.worker.active_job===job.id ? state.worker.phase : "";
  $("currentFile").textContent=phase==="loading"?"Loading the local model. A first load can take a few minutes.":
    job.status==="pausing"?"Pausing after the current image finishes.":job.status==="cancelling"?"Stopping after the current image finishes.":
    job.current_file || (job.status==="completed"?"All descriptions are saved. Select an image to review its text.":job.status==="paused"?"Saved progress is safe. Resume whenever you are ready.":job.status==="queued"?"Waiting for the current batch.":"");
  $("jobError").hidden=!job.error;$("jobError").textContent=job.error;
  $("pauseButton").hidden=!["running","queued"].includes(job.status);
  $("resumeButton").hidden=!["paused","cancelled","failed","completed_with_errors"].includes(job.status);
  $("resumeButton").textContent=job.status==="completed_with_errors"?"Retry failed images":"Resume batch";
  $("cancelButton").hidden=!["running","queued","paused","pausing"].includes(job.status);
  $("exportJson").href="/api/jobs/"+job.id+"/export?format=json";
  $("exportCsv").href="/api/jobs/"+job.id+"/export?format=csv";
}
async function poll() {
  if(state.stopped) return;
  try {
    const data=await api("/api/state");state.jobs=data.jobs;state.worker=data.worker;
    renderWorker();renderHistory();renderBatch();
    if(state.jobId) await fetchItems();
  } catch(error) { alertError(error); }
  finally { if(!state.stopped) timer=setTimeout(poll,document.hidden?8000:2000); }
}
async function selectJob(id) {
  state.jobId=id;state.page=0;state.gridKey="";clearError();
  renderHistory();renderBatch();
  try { await fetchItems(); } catch(error) { alertError(error); }
}
async function submit(event) {
  event.preventDefault();if(state.submitting) return;
  state.submitting=true;$("startButton").disabled=true;$("startButton").textContent="Creating batch…";clearError();saveDraft();
  try {
    const job=await api("/api/jobs",{method:"POST",body:JSON.stringify(values())});
    state.jobs.unshift(job);await selectJob(job.id);toast("Batch queued. Each result is saved as it finishes.");
  } catch(error) { alertError(error); }
  finally { state.submitting=false;$("startButton").disabled=false;renderWorker(); }
}
async function jobAction(action) {
  if(!state.jobId) return;
  try {
    const job=await api("/api/jobs/"+state.jobId+"/"+action,{method:"POST"});
    state.jobs=state.jobs.map(x=>x.id===job.id?job:x);renderBatch();renderHistory();
    toast(action==="pause"?"The current image will finish before pausing.":action==="resume"?"Batch queued to resume.":"Stopping after the current image.");
  } catch(error) { alertError(error); }
}
async function browse(path) {
  const request=++folderRequest;
  folderCurrent="";folderParent=null;
  $("folderError").hidden=true;
  $("folderReconnect").hidden=true;
  $("selectFolder").disabled=true;$("folderParent").disabled=true;
  $("selectedFolder").textContent="Loading folders…";
  $("folderList").innerHTML="";
  try {
    const data=await api("/api/folders?"+new URLSearchParams({path:path || ""}));
    if(request!==folderRequest) return;
    folderCurrent=data.path;folderParent=data.parent;$("folderLocation").value=data.path;
    $("selectedFolder").textContent=data.path || "Choose a drive or folder.";
    $("selectFolder").disabled=!data.path;$("folderParent").disabled=data.parent===null;
    $("folderList").innerHTML=data.folders.length ? data.folders.map(folder=>'<button type="button" class="folder-row" data-path="'+escapeHtml(folder.path)+'">'+escapeHtml(folder.name)+'</button>').join(""):'<p class="muted empty-history">No subfolders. You can select this folder.</p>';
  } catch(error) {
    if(request!==folderRequest) return;
    $("folderError").textContent=error.message;$("folderError").hidden=false;
    $("selectedFolder").textContent="Choose a folder after reconnecting or correcting the path.";
    $("folderReconnect").hidden=!error.connection;
  }
}
function openFolder(target) { folderTarget=target;$("folderDialog").showModal();browse($(target).value.trim()); }
async function detail(index) {
  const selected=state.items[index];if(!selected) return;
  let item=selected;
  try { if(state.jobId) item=await api("/api/items/"+selected.id); } catch(error) { alertError(error);return; }
  $("detailName").textContent=item.relative;$("detailStatus").textContent=statusLabel(item.status);$("detailStatus").className="badge "+item.status;
  $("detailImage").src=state.jobId?"/api/items/"+item.id+"/image":selected.thumbnail;
  $("detailCaption").value=item.caption || (item.status==="ready"?"Start a batch to generate this description.":"No description has been saved for this image yet.");
  $("copyCaption").disabled=!item.caption;$("detailError").hidden=!item.error;$("detailError").textContent=item.error || "";
  $("detailSource").textContent=item.path;$("detailOutput").textContent=item.output_json || "Not saved yet";
  $("detailDialog").showModal();
}
async function boot() {
  try {
    const data=await api("/api/bootstrap");state.csrf=data.csrf;state.config=data.config;state.presets=data.presets;state.jobs=data.jobs;state.worker=data.worker;
    $("characterReferencePreview").textContent=data.character_reference_guidance || "";
    $("folder").value=data.config.default_folder;$("modelPath").value=data.config.default_model;$("runtimePath").textContent=data.config.runtime_directory;
    setPreset("pose");
    try { applyDraft(JSON.parse(localStorage.getItem("caption-studio-draft") || "null")); } catch(_) {}
    renderHistory();renderWorker();
    if(data.worker.active_job) await selectJob(data.worker.active_job);else await scan();
    poll();
  } catch(error) { alertError(error); }
}
$("batchForm").addEventListener("submit",submit);
$("batchForm").addEventListener("input",()=>{outputHint();saveDraft();});
$("presets").addEventListener("click",event=>{const button=event.target.closest("[data-preset]");if(button){setPreset(button.dataset.preset);saveDraft();}});
$("scanButton").addEventListener("click",scan);
$("browseSource").addEventListener("click",()=>openFolder("folder"));
$("browseOutput").addEventListener("click",()=>openFolder("outputDirectory"));
$("reconnectButton").addEventListener("click",reconnect);
$("folderReconnect").addEventListener("click",reconnect);
$("folderLocationForm").addEventListener("submit",event=>{event.preventDefault();browse($("folderLocation").value);});
$("folderDrives").addEventListener("click",()=>browse(""));
$("folderParent").addEventListener("click",()=>browse(folderParent));
$("folderList").addEventListener("click",event=>{const button=event.target.closest("[data-path]");if(button) browse(button.dataset.path);});
$("selectFolder").addEventListener("click",()=>{if(!folderCurrent)return;$(folderTarget).value=folderCurrent;$("folderDialog").close();outputHint();saveDraft();if(folderTarget==="folder")scan();});
$("previousPage").addEventListener("click",()=>{state.page--;fetchItems().catch(alertError);});
$("nextPage").addEventListener("click",()=>{state.page++;fetchItems().catch(alertError);});
$("imageGrid").addEventListener("click",event=>{const button=event.target.closest("[data-index]");if(button)detail(Number(button.dataset.index));});
for(const id of ["history","historyModalList"]) $(id).addEventListener("click",event=>{const button=event.target.closest("[data-job]");if(button){$("historyDialog").close();selectJob(button.dataset.job);}});
for(const id of ["newBatch","newBatchLarge"]) $(id).addEventListener("click",()=>{state.jobId=null;scan();$("folder").focus();});
$("historyButton").addEventListener("click",()=>$("historyDialog").showModal());
$("settingsButton").addEventListener("click",()=>{renderWorker();$("settingsDialog").showModal();});
$("pauseButton").addEventListener("click",()=>jobAction("pause"));
$("resumeButton").addEventListener("click",()=>jobAction("resume"));
$("cancelButton").addEventListener("click",()=>jobAction("cancel"));
$("copyCaption").addEventListener("click",async()=>{try{await navigator.clipboard.writeText($("detailCaption").value);toast("Description copied.");}catch(_){$("detailCaption").select();toast("Select and copy the highlighted description.");}});
$("unloadButton").addEventListener("click",async()=>{try{await api("/api/model/unload",{method:"POST"});toast("Releasing the model from GPU memory.");}catch(error){alertError(error);}});
$("shutdownButton").addEventListener("click",async()=>{try{await api("/api/shutdown",{method:"POST"});state.stopped=true;clearTimeout(timer);$("settingsDialog").close();clearError();connectionError("Your batches are saved. "+launchInstructions,"App stopped");}catch(error){alertError(error);}});
document.querySelectorAll("[data-close]").forEach(button=>button.addEventListener("click",()=>$(button.dataset.close).close()));
boot();

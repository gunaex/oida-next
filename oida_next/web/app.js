"use strict";
let token = "";
let refreshing = false;
const $ = (id) => document.getElementById(id);
document.querySelector("#login .muted").textContent = "Your secure session expires after one hour. Lock session to sign out.";
const message = (text) => { $("message").textContent = text; };
async function api(path, method = "GET", body) {
  const response = await fetch(`/api/v1${path}`, {method, credentials:"same-origin", headers: {"Content-Type":"application/json", ...(token && !token.startsWith("cookie:") ? {Authorization:`Bearer ${token}`} : {})}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const contentType = response.headers.get("content-type") || "";
  const text = await response.text();
  let value;
  if (contentType.includes("application/json")) {
    try { value = JSON.parse(text); }
    catch { throw new Error("The OIDA service returned an invalid response. Please refresh and retry."); }
  } else {
    throw new Error(response.ok ? "The OIDA service returned an unexpected response." : "The OIDA service is temporarily unavailable. Please retry.");
  }
  if (response.status === 401 && token) {
    token = ""; $("workspace").hidden = true; $("login").hidden = false; $("logout").hidden = true;
  }
  if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "Request rejected; check the supplied fields.");
  return value;
}
function node(tag, text, cls) { const el = document.createElement(tag); if (text !== undefined) el.textContent=text; if(cls)el.className=cls; return el; }
function action(label, fn, cls="secondary") { const b=node("button",label,cls); b.type="button"; b.onclick=async()=>{b.disabled=true;try{await fn();await refresh();}catch(e){message(e.message);}finally{b.disabled=false;}};return b; }
$("login-form").onsubmit=async(e)=>{e.preventDefault();try{const r=await api("/login","POST",{password:$("password").value});token=r.access_token;$("password").value="";$("login").hidden=true;$("workspace").hidden=false;$("logout").hidden=false;message("");await refresh();}catch(error){message(error.message);}};
$("logout").onclick=async()=>{try{await api("/logout","POST");}finally{token="";$("workspace").hidden=true;$("login").hidden=false;$("logout").hidden=true;$("jobs").replaceChildren();$("events").replaceChildren();}};
$("goal-form").onsubmit=async(e)=>{e.preventDefault();const button=e.submitter;button.disabled=true;try{const body={goal:$("goal").value,target:$("target").value,idempotency_key:crypto.randomUUID(),timeout:60};if($("recipe").value)body.recipe=$("recipe").value;const job=await api("/goals","POST",body);message(job.state==="WAITING_APPROVAL"?"Plan prepared. Review the exact action below before approving.":"Job queued. The agent will return progress and evidence automatically.");await refresh();}catch(error){message(error.message);}finally{button.disabled=false;}};
async function refresh(){if(!token||refreshing)return;refreshing=true;try{const [agents,jobs,events]=await Promise.all([api("/agents"),api("/jobs"),api("/events")]);$("connection").textContent="Control plane connected";$("agent-count").textContent=`${agents.filter(a=>a.online).length} online`;const selected=$("target").value;$("target").replaceChildren();$("agents").replaceChildren();for(const a of agents){const option=node("option",`${a.name}${a.online?"":" · offline"}`);option.value=a.id;$("target").append(option);const c=node("article",undefined,"card");c.append(node("h3",a.name),node("p",a.online?"Online":"Offline","badge"),node("p",`${a.capabilities.os} · ${a.capabilities.architecture} · ${a.capabilities.cpu_count} CPU`,"meta"),node("p",`Python ${a.capabilities.python} · ${(a.capabilities.disk_free_bytes/1073741824).toFixed(1)} GiB free`,"meta"));c.append(action("Capabilities",()=>show(a)));$("agents").append(c);}if(agents.some(a=>a.id===selected))$("target").value=selected;if(!agents.length)$("agents").append(node("p","No agents enrolled yet. Follow the secure pairing guide.","muted"));$("jobs").replaceChildren();for(const j of jobs){const c=node("article",undefined,"card");c.append(node("h3",j.goal));const meta=node("div",undefined,"meta");meta.append(node("span",j.state,`badge ${j.state==="SUCCEEDED"?"success":j.state==="WAITING_APPROVAL"?"wait":""}`),node("span",j.action.recipe));c.append(meta);const actions=node("div",undefined,"actions");actions.append(action("Plan & evidence",()=>show(j)));if(j.state==="WAITING_APPROVAL"){actions.append(action("Review approval",()=>{show(j.action);const detail=$("detail");const existing=detail.querySelector(".actions");if(existing)existing.remove();const controls=node("div",undefined,"actions");controls.append(action("Approve this exact plan",async()=>{await api(`/jobs/${j.id}/approval`,"POST",{action_hash:j.action_hash,approve:true});controls.remove();},""),action("Reject",async()=>{await api(`/jobs/${j.id}/approval`,"POST",{action_hash:j.action_hash,approve:false});controls.remove();}));detail.append(controls);}));}if(!["SUCCEEDED","FAILED","CANCELLED","TIMED_OUT"].includes(j.state))actions.append(action("Cancel",()=>api(`/jobs/${j.id}/cancel`,"POST")));c.append(actions);$("jobs").append(c);}if(!jobs.length)$("jobs").append(node("p","Your first goal starts here. Nothing is running.","muted"));$("events").replaceChildren(...events.slice(-20).reverse().map(e=>{const row=node("div",undefined,"event");row.append(node("time",new Date(e.timestamp*1000).toLocaleTimeString()),node("span",`${e.type} ${e.job?e.job.slice(0,8):""}`));return row;}));}catch(error){$("connection").textContent="Connection interrupted";message(error.message);}finally{refreshing=false;}}
function show(value){$("detail").hidden=false;$("detail-text").textContent=JSON.stringify(value,null,2);$("detail").scrollIntoView({behavior:"smooth",block:"nearest"});}
setInterval(refresh,2500);
let resumeCancelled = false;
$("login-form").addEventListener("submit", () => { resumeCancelled = true; });
$("logout").addEventListener("click", () => {
  resumeCancelled = true;
  $("detail").hidden = true; $("detail-text").textContent = "";
  $("detail").querySelector(".actions")?.remove();
});
api("/session").then(() => {
  if (resumeCancelled || token) return;
  token = `cookie:${crypto.randomUUID()}`;
  $("login").hidden = true; $("workspace").hidden = false; $("logout").hidden = false;
  refresh();
}).catch(() => {});

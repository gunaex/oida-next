"use strict";
const moduleNames = {pm:"PM", qa:"QA", document:"Document", infra:"Infra"};
let pendingIdempotency = null;

function targetCard(name, target) {
  const card = node("div", undefined, "target-card");
  const state = target?.status || "PENDING";
  card.append(node("strong", moduleNames[name]), node("span", state, `badge ${state === "CREATED" ? "success" : state === "FAILED" ? "failure" : "wait"}`));
  if (target?.error) card.append(node("small", target.error));
  return card;
}

function renderOrchestrations(records) {
  const container = $("orchestrations"); container.replaceChildren();
  for (const record of records) {
    const card = node("article", undefined, "card orchestration-card");
    const heading = node("div", undefined, "section-title");
    heading.append(node("h3", record.title), node("span", record.status, `badge ${record.status === "COMPLETE" ? "success" : "wait"}`));
    card.append(heading, node("p", record.requirement, "requirement-preview"));
    const targets = node("div", undefined, "target-grid");
    for (const name of ["pm", "qa", "document", "infra"]) targets.append(targetCard(name, record.targets[name]));
    card.append(targets);
    if (record.status !== "COMPLETE") card.append(action("Retry unfinished modules", async () => submitOrchestration(record.title, record.requirement, record.idempotency_key)));
    container.append(card);
  }
  if (!records.length) container.append(node("p", "No requirements have been distributed yet.", "muted"));
}

async function loadOrchestrations() {
  const session = token;
  const [identity, records] = await Promise.all([api("/identity"), api("/orchestrations")]);
  if (!session || session !== token) return;
  $("identity-state").textContent = identity.connected ? `Signed in as ${identity.email}` : "Account connection unavailable";
  renderOrchestrations(records);
}

async function submitOrchestration(title, requirement, idempotencyKey) {
  const result = await api("/orchestrations", "POST", {title, requirement, idempotency_key:idempotencyKey});
  pendingIdempotency = null;
  message(result.status === "COMPLETE" ? "Created and distributed to all four workspaces." : "Some workspaces need another attempt. Successful work was kept.");
  await loadOrchestrations();
}

$("orchestration-form").onsubmit = async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  pendingIdempotency ||= crypto.randomUUID();
  try {
    await submitOrchestration($("orchestration-title").value.trim(), $("orchestration-requirement").value.trim(), pendingIdempotency);
    $("orchestration-form").reset();
  } catch (error) { message(error.message); }
  finally { button.disabled = false; }
};

new MutationObserver(() => {
  if (!$("workspace").hidden && token) loadOrchestrations().catch(error => message(error.message));
  else $("orchestrations").replaceChildren();
}).observe($("workspace"), {attributes:true, attributeFilter:["hidden"]});

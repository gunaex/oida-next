"use strict";
const moduleNames = {pm:"PM", qa:"QA", document:"Document", infra:"Infra"};
let pendingIdempotency = null;

function workflowButton(label, fn, cls="secondary") {
  const button = node("button", label, cls); button.type = "button";
  button.onclick = async () => {
    button.disabled = true;
    try { await fn(); await loadWorkspace(); }
    catch (error) { message(error.message); }
    finally { button.disabled = false; }
  };
  return button;
}

function itemStatus(items, name) {
  const own = items.filter(item => item.module === name);
  if (!own.length) return "PENDING";
  return own.every(item => item.status === "CREATED") ? "CREATED" : "FAILED";
}

function targetCard(name, record) {
  const card = node("div", undefined, "target-card");
  const state = itemStatus(record.items, name);
  card.append(node("strong", moduleNames[name]), node("span", state,
    `badge ${state === "CREATED" ? "success" : state === "FAILED" ? "failure" : "wait"}`));
  const failed = record.items.find(item => item.module === name && item.error);
  if (failed) card.append(node("small", failed.error));
  return card;
}

function renderDrafts(records) {
  const container = $("orchestrations"); container.replaceChildren();
  for (const record of records) {
    const card = node("article", undefined, "card orchestration-card");
    const heading = node("div", undefined, "section-title");
    const statusClass = record.status === "APPROVED" ? "success" : record.status === "PARTIAL" ? "failure" : "wait";
    heading.append(node("h3", record.title), node("span", record.status, `badge ${statusClass}`));
    const counts = node("div", undefined, "draft-summary");
    counts.append(
      node("span", `${record.plan.pm_tasks.length} PM tasks`),
      node("span", `${record.plan.qa_suites.length} QA suites`),
      node("span", `${record.plan.document_requirements.length} requirements`),
      node("span", `${record.plan.infra.components.length} infra components`)
    );
    card.append(heading, node("p", record.requirement, "requirement-preview"), counts);
    if (record.status === "DRAFT") {
      const editor = node("textarea", undefined, "draft-plan");
      editor.value = JSON.stringify(record.plan, null, 2);
      const controls = node("div", undefined, "actions");
      controls.append(
        workflowButton("Save edited draft", async () => {
          let plan;
          try { plan = JSON.parse(editor.value); }
          catch { throw new Error("Draft JSON is invalid. Fix it before saving."); }
          await api(`/ai/drafts/${record.id}`, "PUT", {plan});
          message("Draft saved. Review the updated content before approval.");
        }),
        workflowButton("Approve and distribute", async () => {
          const result = await api(`/ai/drafts/${record.id}/approve`, "POST", {plan_hash:record.plan_hash});
          message(result.status === "APPROVED" ? "Approved work was created in all four workspaces." : "Some workspaces failed. Successful work was kept; retry the unfinished items.");
        }, "")
      );
      card.append(editor, controls);
    } else {
      const targets = node("div", undefined, "target-grid");
      for (const name of ["pm", "qa", "document", "infra"]) targets.append(targetCard(name, record));
      card.append(targets);
      if (record.status === "PARTIAL") card.append(workflowButton("Retry unfinished items", async () => {
        await api(`/ai/drafts/${record.id}/approve`, "POST", {plan_hash:record.plan_hash});
        message("Retry completed. Existing records were not duplicated.");
      }));
    }
    container.append(card);
  }
  if (!records.length) container.append(node("p", "No AI drafts yet. Describe a project above to begin.", "muted"));
}

async function loadWorkspace() {
  const session = token;
  const [identity, settings, drafts] = await Promise.all([
    api("/identity"), api("/ai/settings"), api("/ai/drafts")
  ]);
  if (!session || session !== token) return;
  $("identity-state").textContent = identity.connected ? `Signed in as ${identity.email}` : "Account connection unavailable";
  $("ai-provider").value = settings.provider;
  $("ai-model").value = settings.model;
  $("ai-key-state").textContent = settings.has_api_key ? "A DeepSeek key is saved securely on the server." : "No DeepSeek key is saved.";
  renderDrafts(drafts);
}

$("orchestration-form").onsubmit = async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  pendingIdempotency ||= crypto.randomUUID();
  try {
    await api("/ai/drafts", "POST", {
      title:$("orchestration-title").value.trim(),
      requirement:$("orchestration-requirement").value.trim(),
      idempotency_key:pendingIdempotency
    });
    pendingIdempotency = null; $("orchestration-form").reset();
    message("AI draft created. Review or edit it, then approve distribution.");
    await loadWorkspace();
  } catch (error) { message(error.message); }
  finally { button.disabled = false; }
};

$("ai-settings-form").onsubmit = async event => {
  event.preventDefault(); const button = event.submitter; button.disabled = true;
  try {
    const key = $("ai-key").value.trim();
    await api("/ai/settings", "PUT", {
      provider:$("ai-provider").value,
      model:$("ai-model").value.trim(),
      api_key:key || null
    });
    $("ai-key").value = ""; message("AI provider settings saved."); await loadWorkspace();
  } catch (error) { message(error.message); }
  finally { button.disabled = false; }
};

new MutationObserver(() => {
  if (!$("workspace").hidden && token) loadWorkspace().catch(error => message(error.message));
  else $("orchestrations").replaceChildren();
}).observe($("workspace"), {attributes:true, attributeFilter:["hidden"]});

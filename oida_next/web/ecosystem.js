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

function renderVerification(verification) {
  const section = node("div", undefined, "live-check");
  const heading = node("div", undefined, "section-title");
  heading.append(
    node("strong", "Full-loop verification"),
    node("span", verification.healthy ? "PASS" : "FAIL", `badge ${verification.healthy ? "success" : "failure"}`)
  );
  const modules = node("div", undefined, "live-grid");
  for (const name of ["pm", "qa", "document", "infra"]) {
    const value = verification.modules[name];
    const card = node("a", undefined, "live-module"); card.href = value.url || "#";
    card.append(node("strong", moduleNames[name]), node("span", value.state || "UNKNOWN"));
    if (name === "qa" && value.suites) card.append(node("small", `${value.suites.found}/${value.suites.expected} suites · ${value.cases.found}/${value.cases.expected} cases`));
    else if (value.expected !== undefined) card.append(node("small", `${value.found}/${value.expected} records verified`));
    else if (name === "infra") card.append(node("small", value.linked ? "Workspace linked to design" : "Workspace link missing"));
    if (value.message) card.append(node("small", value.message, "draft-error"));
    modules.append(card);
  }
  section.append(heading, modules, node("small", `Checked ${new Date(verification.checked * 1000).toLocaleString()}`, "muted"));
  return section;
}

function renderDiff(diff) {
  const section = node("div", undefined, "revision-diff");
  section.append(node("strong", "Changes from the approved plan"));
  for (const name of ["pm", "qa", "document", "infra"]) {
    const value = diff[name];
    const changes = value.changed === true ? ["architecture changed"] : [
      ...(value.added || []).map(item => `+ ${item}`),
      ...(value.changed || []).map(item => `~ ${item}`),
      ...(value.removed || []).map(item => `− ${item} (manual removal)`)
    ];
    section.append(node("p", `${moduleNames[name]}: ${changes.length ? changes.join(" · ") : "No change"}`));
  }
  return section;
}

function revisionForm(record) {
  const details = node("details", undefined, "revision-request");
  details.append(node("summary", "Request an AI revision"));
  const field = node("textarea"); field.placeholder = "Describe the approved requirement change…";
  const button = workflowButton("Generate revision draft", async () => {
    const changeRequest = field.value.trim();
    if (!changeRequest) throw new Error("Describe the requested change first.");
    await api(`/ai/drafts/${record.id}/revisions`, "POST", {
      change_request:changeRequest, idempotency_key:crypto.randomUUID()
    });
    message("AI revision is being generated. Existing work remains unchanged until approval.");
  });
  details.append(field, button);
  return details;
}

function renderDrafts(records) {
  const container = $("orchestrations"); container.replaceChildren();
  for (const record of records) {
    const card = node("article", undefined, "card orchestration-card");
    const heading = node("div", undefined, "section-title");
    const statusClass = record.status === "APPROVED" ? "success" : record.status === "PARTIAL" ? "failure" : "wait";
    heading.append(node("h3", record.title), node("span", record.status, `badge ${statusClass}`));
    const counts = node("div", undefined, "draft-summary");
    if (record.status === "GENERATING") counts.append(node("span", "Local AI is preparing the draft…"));
    else if (record.status === "FAILED") counts.append(node("span", record.error || "AI generation failed", "draft-error"));
    else counts.append(
      node("span", `${record.plan.pm_tasks.length} PM tasks`),
      node("span", `${record.plan.qa_suites.length} QA suites`),
      node("span", `${record.plan.document_requirements.length} requirements`),
      node("span", `${record.plan.infra.components.length} infra components`)
    );
    card.append(heading, node("p", record.requirement, "requirement-preview"), counts);
    if (record.diff) card.append(renderDiff(record.diff));
    if (record.status === "DRAFT") {
      const editor = node("textarea", undefined, "draft-plan");
      editor.value = JSON.stringify(record.plan, null, 2);
      const controls = node("div", undefined, "actions");
      controls.append(workflowButton("Save edited draft", async () => {
          let plan;
          try { plan = JSON.parse(editor.value); }
          catch { throw new Error("Draft JSON is invalid. Fix it before saving."); }
          await api(`/ai/drafts/${record.id}`, "PUT", {plan});
          message("Draft saved. Review the updated content before approval.");
        }));
      if (record.parent_id) {
        const choices = node("div", undefined, "module-choices");
        for (const name of ["pm", "qa", "document", "infra"]) {
          const label = node("label"); const checkbox = node("input"); checkbox.type = "checkbox";
          checkbox.value = name; checkbox.checked = record.diff[name].changed === true ||
            record.diff[name].added.length > 0 || record.diff[name].changed.length > 0;
          label.append(checkbox, document.createTextNode(` ${moduleNames[name]}`)); choices.append(label);
        }
        controls.append(choices, workflowButton("Approve selected changes", async () => {
          const modules = [...choices.querySelectorAll("input:checked")].map(input => input.value);
          if (!modules.length) throw new Error("Select at least one module to update.");
          const result = await api(`/ai/drafts/${record.id}/approve-revision`, "POST", {plan_hash:record.plan_hash, modules});
          message(result.status === "APPROVED" ? "Selected revision changes were applied." : "Some selected changes need a retry.");
        }, ""));
      } else controls.append(workflowButton("Approve and distribute", async () => {
        const result = await api(`/ai/drafts/${record.id}/approve`, "POST", {plan_hash:record.plan_hash});
        message(result.status === "APPROVED" ? "Approved work was created in all four workspaces." : "Some workspaces failed. Successful work was kept; retry the unfinished items.");
      }, ""));
      card.append(editor, controls);
    } else if (record.status === "FAILED") {
      card.append(workflowButton("Retry AI generation", async () => {
        await api(`/ai/drafts/${record.id}/retry-generation`, "POST");
        message("AI generation restarted. Existing approved work remains unchanged.");
      }));
    } else if (record.status !== "GENERATING") {
      const targets = node("div", undefined, "target-grid");
      for (const name of ["pm", "qa", "document", "infra"]) targets.append(targetCard(name, record));
      card.append(targets);
      if (record.verification) card.append(renderVerification(record.verification));
      if (record.status === "APPROVED" && !record.parent_id) card.append(workflowButton("Run full-loop check", async () => {
        const result = await api(`/ai/drafts/${record.id}/verify`, "POST");
        message(result.healthy ? "Full-loop check passed across all four workspaces." : "Full-loop check found a missing or unavailable record.");
      }));
      if (record.status === "APPROVED" && !record.parent_id) card.append(revisionForm(record));
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

setInterval(() => {
  if (!$("workspace").hidden && token) loadWorkspace().catch(error => message(error.message));
}, 5000);

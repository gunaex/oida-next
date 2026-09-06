"use strict";
const ecosystemSection = document.createElement("section");
ecosystemSection.innerHTML = `<h2>Ecosystem work</h2><p class="muted">PM · QA · Document · Infra — reference tracking only. No automatic remote sync.</p><form id="work-form"><label>Work title<input id="work-title" required maxlength="200"></label><button>Create work</button></form><button id="load-work" type="button">Refresh work</button><div id="ecosystem-work"></div>`;
$("workspace").append(ecosystemSection);
const projectSection = node("section");
projectSection.innerHTML = `<h2>Shared projects</h2><p class="muted">Link existing module project IDs without changing their data. Mappings are not yet remotely verified.</p><form id="project-form"><label>Project name<input id="project-name" required maxlength="200"></label><button>Create shared project</button></form><div id="shared-projects"></div>`;
ecosystemSection.before(projectSection);
const identitySection = node("section");
identitySection.innerHTML = `<h2>Module identity</h2><p id="identity-state" class="muted">Checking configuration…</p><form id="identity-form" hidden><label>Account Again email<input id="identity-email" type="email" autocomplete="username" required></label><label>Account Again password<input id="identity-password" type="password" autocomplete="current-password" required></label><button>Connect this session</button></form><div id="identity-actions"></div><div id="remote-projects"></div>`;
projectSection.before(identitySection);
async function loadIdentity() {
  const session = token;
  const state = await api("/identity");
  if (!session || token !== session) return;
  $("identity-state").textContent = !state.configured ? "Shared identity service is not configured yet." : state.connected ? `Connected as ${state.email} until ${new Date(state.expires * 1000).toLocaleTimeString()}` : "Connect Account Again to read projects you are permitted to access. This is separate from your OIDA owner session for now.";
  $("identity-form").hidden = !state.configured || state.connected;
  $("identity-actions").replaceChildren();
  if (state.connected) {
    const pairing = node("details");
    pairing.append(node("summary", "Connect an existing PM or QA account"), node("p", "Confirm the existing account password once. Its email and permissions stay unchanged. This creates a permanent identity link; disconnecting this session does not remove that link."));
    const form = node("form");
    const moduleSelect = node("select");
    for (const value of ["pm", "qa"]) { const option = node("option", value.toUpperCase()); option.value = value; moduleSelect.append(option); }
    const email = node("input"); email.type = "email"; email.required = true; email.autocomplete = "username";
    const password = node("input"); password.type = "password"; password.required = true; password.maxLength = 256; password.autocomplete = "current-password";
    for (const [title, input] of [["Application", moduleSelect], ["Existing account email", email], ["Existing account password", password]]) {
      const label = node("label", title); label.append(input); form.append(label);
    }
    const submit = node("button", "Verify and link account"); submit.type = "submit"; form.append(submit);
    form.onsubmit = async e => {
      e.preventDefault(); submit.disabled = true;
      const body = {email: email.value, password: password.value};
      const module = moduleSelect.value; password.value = "";
      try {
        await api(`/modules/${module}/pair`, "POST", body);
        if (token !== session) return;
        form.reset(); pairing.open = false;
        message(`${module.toUpperCase()} account linked. Existing permissions are unchanged.`);
      } catch (error) { if (token === session) message(error.message); }
      finally { body.password = ""; submit.disabled = false; }
    };
    pairing.append(form); $("identity-actions").append(pairing);
    for (const module of ["pm", "qa"]) $("identity-actions").append(action(`Read ${module.toUpperCase()} projects`, async () => {
      const records = await api(`/modules/${module}/projects`);
      if (token !== session) return;
      $("remote-projects").replaceChildren();
      for (const record of records) {
        const card = node("article", undefined, "card");
        card.append(node("h3", record.name), node("p", `${module}: ${record.external_id}`), action("Import project reference", async () => {
          await api(`/modules/${module}/projects/${encodeURIComponent(record.external_id)}/import`, "POST");
          await loadWork(); message("Project reference imported. Source project data was not changed.");
        }));
        $("remote-projects").append(card);
      }
      if (!records.length) $("remote-projects").append(node("p", "No projects visible to this identity."));
    }));
    $("identity-actions").append(action("Disconnect modules", async () => {
      await api("/identity", "DELETE"); $("remote-projects").replaceChildren(); await loadIdentity();
    }));
  }
}
$("identity-form").onsubmit = async e => {
  e.preventDefault(); e.submitter.disabled = true;
  const credentials = {email: $("identity-email").value, password: $("identity-password").value};
  $("identity-password").value = "";
  try { await api("/identity", "POST", credentials); await loadIdentity(); }
  catch (error) { message(error.message); }
  finally { credentials.password = ""; e.submitter.disabled = false; }
};
async function loadProjects() {
  const session = token;
  const projects = await api("/projects");
  if (!session || session !== token) return [];
  $("shared-projects").replaceChildren();
  for (const project of projects) {
    const card = node("article", undefined, "card");
    card.append(node("h3", project.name), node("p", `${project.work_ids.length} linked work items`));
    for (const link of project.links) card.append(node("p", `${link.system}: ${link.external_id} · not remotely verified`));
    const system = node("select"); system.setAttribute("aria-label", "Module to map");
    for (const value of ["pm", "qa", "document", "infra"]) {
      const option = node("option", value); option.value = value; system.append(option);
    }
    const reference = node("input"); reference.maxLength = 200; reference.placeholder = "Existing module project ID";
    reference.setAttribute("aria-label", "Existing module project ID");
    card.append(system, reference, action("Map project", async () => {
      await api(`/projects/${project.id}/links`, "PUT", {system: system.value, external_id: reference.value});
      await loadProjects();
    }));
    $("shared-projects").append(card);
  }
  if (!projects.length) $("shared-projects").append(node("p", "No shared projects yet."));
  return projects;
}
$("project-form").onsubmit = async e => {
  e.preventDefault(); e.submitter.disabled = true;
  try { await api("/projects", "POST", {name: $("project-name").value}); $("project-name").value = ""; await loadWork(); }
  catch (error) { message(error.message); }
  finally { e.submitter.disabled = false; }
};
async function loadWork() {
  const session = token;
  const projects = await loadProjects();
  if (!session || session !== token) return;
  const records = await api("/work");
  if (session !== token) return;
  const container = $("ecosystem-work");
  container.replaceChildren();
  for (const work of records) {
    const card = node("article", undefined, "card");
    card.append(node("h3", work.title), node("p", work.status, "badge"));
    const parent = projects.find(p => p.work_ids.includes(work.id));
    if (parent) card.append(node("p", `Project: ${parent.name}`));
    else if (projects.length) {
      const selector = node("select"); selector.setAttribute("aria-label", "Parent project");
      for (const project of projects) { const option = node("option", project.name); option.value = project.id; selector.append(option); }
      card.append(selector, action("Assign project", async () => {
        await api(`/projects/${selector.value}/work/${work.id}`, "PUT"); await loadWork();
      }));
    }
    const job = node("input"); job.placeholder = "Existing OIDA job ID"; job.setAttribute("aria-label", "Existing OIDA job ID");
    card.append(job, action("Link execution", async () => {
      await api(`/work/${work.id}/jobs/${encodeURIComponent(job.value)}`, "PUT"); await loadWork();
    }), action("Execution evidence", async () => show(await api(`/work/${work.id}/execution`))));
    const state = node("select");
    state.setAttribute("aria-label", "Work status");
    for (const value of ["OPEN", "IN_PROGRESS", "BLOCKED", "DONE"]) {
      const option = node("option", value); option.value = value; state.append(option);
    }
    state.value = work.status;
    card.append(state, action("Save status", async () => {
      await api(`/work/${work.id}`, "PATCH", {status: state.value}); await loadWork();
    }));
    for (const ref of work.references) card.append(node("p", `${ref.system}: ${ref.external_id} — ${ref.note}`));
    const system = node("select"); system.setAttribute("aria-label", "Related application");
    for (const value of ["pm", "qa", "document", "infra"]) {
      const option = node("option", value); option.value = value; system.append(option);
    }
    const reference = node("input"); reference.placeholder = "External record ID"; reference.maxLength = 200;
    reference.setAttribute("aria-label", "External record ID");
    card.append(system, reference, action("Attach reference", async () => {
      await api(`/work/${work.id}/references`, "PUT", {system: system.value, external_id: reference.value});
      await loadWork();
    }));
    container.append(card);
  }
  if (!records.length) container.append(node("p", "No ecosystem work yet."));
}
$("load-work").onclick = () => loadWork().catch(e => message(e.message));
new MutationObserver(() => {
  if (!$("workspace").hidden && token) {
    loadWork().catch(e => message(e.message)); loadIdentity().catch(e => message(e.message));
  }
  else {
    $("shared-projects").replaceChildren(); $("ecosystem-work").replaceChildren();
    $("project-form").reset(); $("work-form").reset();
    $("identity-form").reset(); $("identity-form").hidden = true;
    $("identity-actions").replaceChildren(); $("remote-projects").replaceChildren();
    $("identity-state").textContent = "Session locked";
  }
}).observe($("workspace"), {attributes: true, attributeFilter: ["hidden"]});
$("work-form").onsubmit = async e => {
  e.preventDefault(); e.submitter.disabled = true;
  try { await api("/work", "POST", {title: $("work-title").value}); $("work-title").value = ""; await loadWork(); }
  catch (error) { message(error.message); }
  finally { e.submitter.disabled = false; }
};

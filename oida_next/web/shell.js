"use strict";
// Static same-origin navigation only: identity and access stay server-owned.
const shell = document.createElement("nav");
shell.className = "oida-shell";
shell.setAttribute("aria-label", "OIDA applications");
const enabledModules = document.currentScript?.dataset.modules?.split(",");
for (const [label, path] of [["OIDA Next", "/"], ["PM", "/pm/"], ["QA", "/qa/"], ["Document", "/documents/"], ["Infra", "/infra/"]]) {
  if (path !== "/" && enabledModules && !enabledModules.includes(path.split("/")[1])) continue;
  const link = document.createElement("a"); link.textContent = label; link.href = path;
  if (path === "/" ? location.pathname === "/" : location.pathname.startsWith(path)) link.setAttribute("aria-current", "page");
  shell.append(link);
}
document.body.prepend(shell);

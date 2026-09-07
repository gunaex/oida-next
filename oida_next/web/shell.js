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
const guides = {
  oida: {
    title: "คู่มือ OIDA Next",
    intro: "ศูนย์สั่งงานกลางสำหรับเปลี่ยน requirement เป็นงานของทุกทีม",
    steps: [
      "ตั้งค่า Local LLM หรือ DeepSeek แล้วกด Test connection ให้ผ่าน",
      "กรอกชื่อโครงการและ requirement ที่มีขอบเขต ข้อจำกัด และเกณฑ์ยอมรับ",
      "กด Generate AI draft แล้วตรวจ PM, QA, Document และ Infra ให้ครบ",
      "แก้ draft หากจำเป็น ก่อนกด Approve and distribute",
      "เมื่ออนุมัติแล้ว กด Run full-loop check และต้องเห็น PASS",
    ],
    note: "การแก้งานที่อนุมัติแล้วให้ใช้ Request an AI revision ระบบจะเก็บประวัติและส่งเฉพาะส่วนที่เลือก",
  },
  pm: {
    title: "คู่มือ PM",
    intro: "ใช้วางแผน ติดตามงาน เจ้าของงาน กำหนดเวลา และความคืบหน้าของโครงการ",
    steps: [
      "เลือกโครงการที่ OIDA สร้างให้จากหน้า Projects",
      "เปิด Tasks เพื่อตรวจรายละเอียด ลำดับความสำคัญ และ acceptance criteria",
      "กำหนดผู้รับผิดชอบ วันที่ และสถานะตามการทำงานจริง",
      "บันทึก issue หรือ blocker ที่กระทบแผน และติดตามงานค้างจาก dashboard",
      "กลับ OIDA เพื่อรัน full-loop check หลังรับ revision ใหม่",
    ],
    note: "งานที่ OIDA ส่งสำเร็จแล้วจะไม่ถูกสร้างซ้ำเมื่อกด retry",
  },
  qa: {
    title: "คู่มือ QA",
    intro: "ใช้จัดชุดทดสอบ test case ผลการทดสอบ และหลักฐานคุณภาพ",
    steps: [
      "เลือกโครงการ แล้วเปิด Test Suites ที่ OIDA สร้างให้",
      "ตรวจ precondition, steps และ expected result ของแต่ละ test case",
      "รันทดสอบทั้งเส้นทางปกติ สิทธิ์ไม่ถูกต้อง recovery และ performance",
      "บันทึก PASS/FAIL พร้อมหลักฐานและ defect ที่เชื่อมโยง",
      "ยืนยันจำนวน suite/case กับผล Run full-loop check ใน OIDA",
    ],
    note: "อย่าลบ suite ที่มีประวัติผลทดสอบ ให้ archive เมื่อเลิกใช้งาน",
  },
  document: {
    title: "คู่มือ Document",
    intro: "ใช้ดูแล requirement, acceptance criteria, เอกสารออกแบบ และหลักฐานอนุมัติ",
    steps: [
      "เปิด Requirements แล้วเลือกโครงการหรือรายการที่ OIDA ส่งมา",
      "ตรวจข้อความ requirement และเกณฑ์ยอมรับว่าทดสอบและวัดผลได้",
      "แก้รายละเอียดหรือเพิ่มหลักฐาน โดยรักษาความเชื่อมโยงกับโครงการ",
      "ทบทวนเอกสารเมื่อ OIDA ส่ง revision และเก็บเหตุผลการเปลี่ยนแปลง",
      "ตรวจจำนวนรายการกับผล full-loop ก่อนปิดรอบอนุมัติ",
    ],
    note: "API key, password และข้อมูลลับต้องไม่อยู่ใน requirement หรือเอกสารหลักฐาน",
  },
  infra: {
    title: "คู่มือ Infra",
    intro: "ใช้ตรวจและปรับสถาปัตยกรรม components, connections และข้อกำหนดการเดินระบบ",
    steps: [
      "เลือก workspace ที่เชื่อมกับโครงการจาก OIDA",
      "ตรวจ component, dependency, network boundary และ data flow",
      "เติม monitoring, backup, recovery, security และ capacity ที่จำเป็น",
      "ตรวจการเปลี่ยนแปลงของ revision ก่อนนำไปใช้จริง",
      "กลับ OIDA เพื่อยืนยันว่า Infra workspace linked และ full-loop เป็น PASS",
    ],
    note: "แบบ Infra เป็น design สำหรับ review การเปลี่ยน production ยังต้องผ่านขั้นอนุมัติของผู้ดูแล",
  },
};
const section = location.pathname.startsWith("/pm") ? "pm"
  : location.pathname.startsWith("/qa") ? "qa"
  : location.pathname.startsWith("/documents") ? "document"
  : location.pathname.startsWith("/infra") ? "infra" : "oida";
const guide = guides[section];
const guideButton = document.createElement("button");
guideButton.type = "button";
guideButton.className = "oida-guide-button";
guideButton.textContent = "คู่มือ";
guideButton.setAttribute("aria-haspopup", "dialog");
shell.append(guideButton);
document.body.prepend(shell);

const dialog = document.createElement("dialog");
dialog.className = "oida-guide";
dialog.setAttribute("aria-labelledby", "oida-guide-title");
const panel = document.createElement("article");
const title = document.createElement("h2");
title.id = "oida-guide-title";
title.textContent = guide.title;
const intro = document.createElement("p");
intro.className = "oida-guide-intro";
intro.textContent = guide.intro;
const list = document.createElement("ol");
for (const value of guide.steps) {
  const item = document.createElement("li");
  item.textContent = value;
  list.append(item);
}
const note = document.createElement("p");
note.className = "oida-guide-note";
note.textContent = guide.note;
const close = document.createElement("button");
close.type = "button";
close.className = "oida-guide-close";
close.textContent = "ปิดคู่มือ";
close.addEventListener("click", () => dialog.close());
panel.append(title, intro, list, note, close);
dialog.append(panel);
dialog.addEventListener("click", event => { if (event.target === dialog) dialog.close(); });
guideButton.addEventListener("click", () => dialog.showModal());
document.body.append(dialog);

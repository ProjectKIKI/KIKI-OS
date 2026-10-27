"use strict";

const menuToggle = document.querySelector(".tl-menu-toggle");
function closeBuildMenu() {
  document.body.classList.remove("tl-menu-open");
  menuToggle?.setAttribute("aria-expanded", "false");
  menuToggle?.setAttribute("aria-label", "메뉴 열기");
}
menuToggle?.addEventListener("click", () => {
  const expanded = document.body.classList.toggle("tl-menu-open");
  menuToggle.setAttribute("aria-expanded", String(expanded));
  menuToggle.setAttribute("aria-label", expanded ? "메뉴 닫기" : "메뉴 열기");
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && document.body.classList.contains("tl-menu-open")) {
    closeBuildMenu(); menuToggle?.focus();
  }
});
document.addEventListener("click", event => {
  if (!event.target.closest(".tl-sidebar,.tl-menu-toggle")) closeBuildMenu();
});
document.querySelectorAll(".tl-content table").forEach(table => {
  if (table.parentElement.matches(".tl-table-scroll,.table-wrap")) return;
  const wrapper = document.createElement("div");
  wrapper.className = "tl-table-scroll";
  wrapper.tabIndex = 0;
  wrapper.setAttribute("role", "region");
  wrapper.setAttribute("aria-label", "표 · 가로로 스크롤할 수 있습니다");
  table.before(wrapper);
  wrapper.append(table);
});

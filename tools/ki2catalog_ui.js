"use strict";
document.querySelectorAll('[data-picker]').forEach(picker => {
  const source = picker.querySelector('textarea');
  const input = picker.querySelector('[data-picker-input]');
  const selected = picker.querySelector('[data-picker-items]');
  const choices = new Set(Array.from(picker.querySelectorAll('option'), x => x.value));
  const values = () => [...new Set(source.value.trim().split(/[\s,]+/).filter(Boolean))];
  function render() {
    selected.replaceChildren();
    for (const value of values()) {
      const chip = document.createElement('span'); chip.className = 'catalog-chip';
      chip.append(document.createTextNode(value));
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×';
      remove.setAttribute('aria-label', value + ' 제거');
      remove.addEventListener('click', () => {source.value = values().filter(x => x !== value).join('\n'); render();});
      chip.append(remove); selected.append(chip);
    }
  }
  function add() {
    const value = input.value.trim();
    if (!value) return;
    if (!choices.has(value)) {input.setCustomValidity('목록에 등록된 이름을 선택하세요.'); input.reportValidity(); return;}
    source.value = [...new Set([...values(), value])].join('\n'); input.value = ''; input.setCustomValidity(''); render(); input.focus();
  }
  picker.querySelector('[data-picker-add]').addEventListener('click', add);
  input.addEventListener('input', () => input.setCustomValidity(''));
  input.addEventListener('keydown', event => {if (event.key === 'Enter') {event.preventDefault(); add();}});
  source.addEventListener('input', render); render();
});
const kind = document.querySelector('select[name=kind]');
if (kind) {
  const update = () => document.querySelectorAll('[data-registration-kind]').forEach(section => {
    section.hidden = section.dataset.registrationKind !== kind.value;
  });
  kind.addEventListener('change', update); update();
}

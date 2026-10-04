"use strict";

document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

document.querySelectorAll(".field-error").forEach((error) => {
  const input = document.getElementById(error.id.replace("error-", ""));
  if (input) {
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", error.id);
  }
});

const courseForm = document.querySelector('[data-course-form]');
if (courseForm) {
  const wrapper = courseForm.querySelector('[data-autocomplete]');
  const input = wrapper.querySelector('input');
  const list = wrapper.querySelector('[role=listbox]');
  const status = wrapper.querySelector('[data-search-status]');
  const code = courseForm.querySelector('#course_code_snapshot');
  const title = courseForm.querySelector('#course_title_snapshot');
  const version = courseForm.querySelector('#course_version_id');
  const identity = courseForm.querySelector('#course_id');
  const source = document.querySelector('[data-course-source]');
  const level = document.querySelector('[data-course-level]');
  let timer, controller, results = [], active = -1, generation = 0;
  const close = () => {
    generation += 1;
    clearTimeout(timer);
    if (controller) controller.abort();
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    active = -1;
  };
  const clearSelection = () => {
    version.value = '';
    identity.value = '';
    source.textContent = 'Manual entry';
    level.textContent = 'Unknown';
    const link = document.querySelector('[data-provenance-link]');
    if (link) link.hidden = true;
  };
  [code, title].forEach((field) => field.addEventListener('input', clearSelection));
  const highlight = (index) => {
    active = index;
    [...list.children].forEach((option, i) => option.setAttribute('aria-selected', String(i === index)));
    if (index >= 0) {
      input.setAttribute('aria-activedescendant', list.children[index].id);
      list.children[index].scrollIntoView({block: 'nearest'});
    }
  };
  const choose = (index) => {
    const result = results[index];
    if (!result) return;
    code.value = result.code;
    title.value = result.title;
    courseForm.querySelector('#units').value = result.units;
    identity.value = result.course_id;
    version.value = result.version_id;
    source.textContent = (result.data_status === 'official_imported' ? 'HKBU Handbook' : 'Unverified catalogue') + ' / ' + (result.academic_year || 'Unknown year');
    level.textContent = result.level ?? 'Unknown';
    input.value = result.code + ' / ' + result.title;
    status.textContent = '';
    close();
    input.focus();
  };
  input.addEventListener('input', () => {
    close();
    clearSelection();
    const query = input.value.trim();
    status.textContent = '';
    if (!query) return;
    const current = generation;
    timer = setTimeout(async () => {
      controller = new AbortController();
      try {
        const params = new URLSearchParams({q: query, academic_year: wrapper.dataset.year, limit: '12'});
        const response = await fetch('/api/catalogue/search?' + params, {signal: controller.signal});
        if (!response.ok || response.redirected) throw new Error('Search unavailable');
        const data = await response.json();
        if (current !== generation) return;
        results = data;
        list.replaceChildren();
        results.forEach((result, index) => {
          const option = document.createElement('li');
          option.id = 'catalogue-option-' + index;
          option.setAttribute('role', 'option');
          option.setAttribute('aria-selected', 'false');
          option.dataset.index = index;
          const strong = document.createElement('strong');
          strong.textContent = result.code;
          const label = document.createElement('span');
          label.textContent = result.title;
          const meta = document.createElement('small');
          meta.textContent = result.units + ' units / Level ' + (result.level ?? 'unknown') + ' / ' + (result.academic_year || 'Unknown year');
          option.append(strong, label, meta);
          list.append(option);
        });
        list.hidden = results.length === 0;
        input.setAttribute('aria-expanded', String(results.length > 0));
        status.textContent = results.length ? results.length + ' matches' : 'No catalogue matches';
      } catch (error) {
        if (error.name !== 'AbortError' && current === generation) status.textContent = 'Catalogue search unavailable';
      }
    }, 180);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' || event.key === 'Tab') { close(); return; }
    if (list.hidden || !results.length) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      highlight((active + (event.key === 'ArrowDown' ? 1 : -1) + results.length) % results.length);
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (active >= 0) choose(active);
    }
  });
  list.addEventListener('mousedown', (event) => event.preventDefault());
  list.addEventListener('click', (event) => {
    const option = event.target.closest('[role=option]');
    if (option) choose(Number(option.dataset.index));
  });
  document.addEventListener('click', (event) => { if (!wrapper.contains(event.target)) close(); });
}

const allocationList = document.querySelector('[data-allocations]');
if (allocationList) {
  const prototype = allocationList.firstElementChild.cloneNode(true);
  let nextId = allocationList.children.length;
  document.querySelector('[data-add-allocation]').addEventListener('click', () => {
    const row = prototype.cloneNode(true);
    nextId += 1;
    row.querySelectorAll('input, select').forEach((input) => {
      input.value = '';
      const label = row.querySelector(`label[for="${input.id}"]`);
      input.id = `${input.name}-${nextId}`;
      label.htmlFor = input.id;
    });
    allocationList.appendChild(row);
  });
  allocationList.addEventListener('click', (event) => {
    const button = event.target.closest('[data-remove-allocation]');
    if (!button) return;
    const row = button.closest('.allocation-row');
    if (allocationList.children.length > 1) row.remove();
    else row.querySelectorAll('input, select').forEach((input) => { input.value = ''; });
  });
}

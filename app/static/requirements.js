"use strict";
document.querySelectorAll('[data-collapse-root]').forEach((root) => {
  const key = 'planner-collapse:' + root.dataset.collapseRoot;
  let saved = [];
  try { const value = JSON.parse(localStorage.getItem(key) || '[]'); if (Array.isArray(value)) saved = value; } catch (_) {}
  const buttons = [...root.querySelectorAll('[data-collapse]')];
  const apply = () => {
    const collapsed = buttons.filter((b) => b.getAttribute('aria-expanded') === 'false').map((b) => b.dataset.collapse.replace('group-', ''));
    root.querySelectorAll('[data-tree-item]').forEach((row) => {
      row.hidden = row.dataset.ancestors.split(',').some((id) => collapsed.includes(id));
    });
    buttons.forEach((button) => {
      const name = button.closest('[data-tree-item]').querySelector('strong').textContent;
      button.setAttribute('aria-label', (button.getAttribute('aria-expanded') === 'true' ? 'Collapse ' : 'Expand ') + name);
      button.title = button.getAttribute('aria-label');
    });
    try { localStorage.setItem(key, JSON.stringify(collapsed)); } catch (_) {}
  };
  buttons.forEach((button) => {
    button.setAttribute('aria-expanded', String(!saved.includes(button.dataset.collapse.replace('group-', ''))));
    button.addEventListener('click', () => {
      button.setAttribute('aria-expanded', String(button.getAttribute('aria-expanded') !== 'true'));
      apply();
    });
  });
  apply();
});

document.querySelectorAll('[data-open-dialog]').forEach((button) => {
  button.addEventListener('click', () => {
    button.closest('details').open = false;
    const dialog = document.getElementById(button.dataset.openDialog);
    dialog.showModal();
  });
});
document.querySelectorAll('[data-close-dialog]').forEach((button) => {
  button.addEventListener('click', () => button.closest('dialog').close());
});
document.addEventListener('click', (event) => {
  document.querySelectorAll('.target-menu[open]').forEach((menu) => {
    if (!menu.contains(event.target)) menu.open = false;
  });
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') document.querySelectorAll('.target-menu[open]').forEach((menu) => {
    menu.open = false;
    menu.querySelector('summary').focus();
  });
});

document.querySelectorAll('[data-target-mode]').forEach((select) => {
  select.addEventListener('change', () => {
    const container = select.value === 'sum_children';
    const input = select.form.querySelector('[name=required_units]');
    input.readOnly = container;
    const output = select.form.querySelector('[data-derived-target]');
    if (output) { input.hidden = container; output.hidden = !container; }
  });
});

const tree = document.querySelector('[data-requirement-tree]');
if (tree) {
  const nodes = [...tree.querySelectorAll('[data-node-id]')];
  const status = document.querySelector('[data-tree-status]');
  const rootDrop = document.querySelector('[data-root-drop]');
  const placements = () => nodes.map((n) => ({id: Number(n.dataset.nodeId), parent_id: n.dataset.parent ? Number(n.dataset.parent) : null}));
  let dragged = null, dirty = false, saving = false;
  tree.querySelectorAll('dialog').forEach((dialog) => dialog.addEventListener('close', () => {
    dialog.querySelector('form').reset();
    dialog.querySelector('[data-target-mode]')?.dispatchEvent(new Event('change'));
    dirty = false;
  }));
  tree.addEventListener('input', () => { dirty = true; });
  const resetTargets = () => document.querySelectorAll('[data-drop]').forEach((node) => delete node.dataset.drop);
  tree.addEventListener('dragstart', (event) => {
    const handle = event.target.closest('.drag-handle');
    if (!handle || dirty || saving) {
      event.preventDefault();
      if (dirty) status.textContent = 'Save your edits before moving a target.';
      return;
    }
    dragged = handle.closest('[data-node-id]');
    event.dataTransfer.setData('text/plain', dragged.dataset.nodeId);
    event.dataTransfer.effectAllowed = 'move';
    tree.classList.add('dragging');
    rootDrop.classList.add('active');
  });
  tree.addEventListener('dragend', () => {
    dragged = null;
    resetTargets();
    tree.classList.remove('dragging');
    rootDrop.classList.remove('active');
  });
  const save = async (ordered) => {
    saving = true;
    status.textContent = 'Saving order...';
    const form = new FormData();
    form.set('csrf_token', tree.dataset.csrf);
    form.set('placements', JSON.stringify(ordered));
    try {
      const response = await fetch('/requirements/tree/reorder', {method: 'POST', body: form});
      if (!response.ok || response.redirected) {
        const html = new DOMParser().parseFromString(await response.text(), 'text/html');
        throw new Error(html.querySelector('.notice')?.textContent.trim() || 'Move rejected. Check parent, sibling names and direct allocations.');
      }
      window.location.reload();
    } catch (error) { status.textContent = error.message; saving = false; }
  };
  const targetPosition = (event, node) => {
    const bounds = node.getBoundingClientRect();
    const ratio = (event.clientY - bounds.top) / bounds.height;
    return ratio < .25 ? 'before' : ratio > .75 ? 'after' : 'inside';
  };
  nodes.forEach((node) => {
    node.addEventListener('dragover', (event) => {
      if (!dragged || node === dragged) return;
      event.preventDefault();
      resetTargets();
      node.dataset.drop = targetPosition(event, node);
    });
    node.addEventListener('drop', (event) => {
      event.preventDefault();
      if (!dragged || node === dragged || saving) return;
      const mode = targetPosition(event, node);
      const ordered = placements();
      const moved = ordered.splice(ordered.findIndex((n) => n.id === Number(dragged.dataset.nodeId)), 1)[0];
      const target = ordered.findIndex((n) => n.id === Number(node.dataset.nodeId));
      moved.parent_id = mode === 'inside' ? Number(node.dataset.nodeId) : ordered[target].parent_id;
      ordered.splice(target + (mode === 'before' ? 0 : 1), 0, moved);
      resetTargets();
      save(ordered);
    });
  });
  rootDrop.addEventListener('dragover', (event) => {
    if (!dragged) return;
    event.preventDefault(); resetTargets(); rootDrop.dataset.drop = 'inside';
  });
  rootDrop.addEventListener('drop', (event) => {
    event.preventDefault();
    if (!dragged || saving) return;
    const ordered = placements();
    const moved = ordered.splice(ordered.findIndex((n) => n.id === Number(dragged.dataset.nodeId)), 1)[0];
    moved.parent_id = null;
    ordered.push(moved);
    save(ordered);
  });
  const suggestions = document.querySelector('#group-suggestions');
  const names = [...suggestions.children].map((option) => option.value);
  const parent = document.querySelector('#new-group-parent');
  const updateSuggestions = () => {
    const existing = new Set(nodes.filter((n) => n.dataset.parent === parent.value).map((n) => n.dataset.nodeName.toLowerCase()));
    suggestions.replaceChildren(...names.filter((name) => !existing.has(name.toLowerCase())).map((name) => {
      const option = document.createElement('option'); option.value = name; return option;
    }));
  };
  parent.addEventListener('change', updateSuggestions);
  updateSuggestions();
}

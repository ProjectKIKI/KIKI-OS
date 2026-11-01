"use strict";

const releaseForm = document.querySelector('[data-release-packages]');
if (releaseForm) {
  const packages = Array.from(releaseForm.querySelectorAll('[data-package-name]'));
  const changes = releaseForm.querySelector('[name="changes"]');
  function updateReleaseSelection() {
    const selected = Object.fromEntries(packages.filter(select => select.value !== select.dataset.original)
      .map(select => [select.dataset.packageName, select.value]));
    changes.value = JSON.stringify(selected);
    releaseForm.querySelector('[data-release-change-count]').textContent = `기준 구성에서 ${Object.keys(selected).length}개 변경 · 등록 시 의존성과 CPU 대상을 다시 검사합니다.`;
  }
  for (const select of packages) select.disabled = false;
  releaseForm.querySelector('[data-release-register]').disabled = releaseForm.dataset.ready !== '1';
  releaseForm.addEventListener('change', updateReleaseSelection);
  releaseForm.addEventListener('submit', updateReleaseSelection);
  releaseForm.querySelector('[data-release-package-search]').addEventListener('input', event => {
    const query = event.target.value.toLowerCase();
    for (const row of releaseForm.querySelectorAll('[data-release-package-row]')) {
      row.hidden = !row.querySelector('[data-package-name]').dataset.packageName.toLowerCase().includes(query);
    }
  });
  updateReleaseSelection();
}

const isoForm = document.querySelector('[data-iso-build]');
if (isoForm) {
  const snapshot = isoForm.querySelector('[name="snapshot"]');
  const target = isoForm.querySelector('[name="cpu_profile"]');
  function updateCpuTargets() {
    const allowed = JSON.parse(snapshot.selectedOptions[0]?.dataset.cpuTargets || '[]');
    for (const option of target.options) {
      option.dataset.baseLabel ||= option.textContent.replace(/ · 준비 중$/, '');
      option.disabled = !allowed.includes(option.value);
      option.textContent = option.dataset.baseLabel + (option.disabled ? ' · 준비 중' : '');
    }
    if (!allowed.includes(target.value)) target.value = allowed[0] || '';
    isoForm.querySelector('button').disabled = !allowed.length;
  }
  snapshot.addEventListener('change', updateCpuTargets);
  updateCpuTargets();
}

// Native browser APIs keep the bootstrap builder free of frontend dependencies.
async function readJson(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`요청 실패 (${response.status})`);
  return response.json();
}

const releaseOverview = document.getElementById("release-overview");
if (releaseOverview) {
  readJson("/api/releases/summary").then(library => {
    const {isos,active} = library;
    releaseOverview.textContent = `보관 바이너리 ${library.binaries}개 · 소스·관련 파일 ${library.sources}개 · 고정 버전 ${library.snapshots}개 · 완료 ISO ${isos}개 · 대기·실행 작업 ${active}개`;
    for (const [key, value] of Object.entries({packages:library.binaries, isos, active})) {
      const metric = document.querySelector(`[data-release="${key}"] .metric-value`);
      if (metric) metric.textContent = String(value);
    }
  }).catch(() => {
    releaseOverview.textContent = "보관소 상태를 불러오지 못했습니다. 후보 버전·ISO 페이지에서 작업 상태를 확인하세요.";
    document.querySelectorAll('[data-release] .metric-value').forEach(metric => {if(metric.textContent === '—') metric.textContent = '연결 확인';});
  });
}

const planForm = document.querySelector("[data-build-plan]");
if (planForm) {
  let revision = 0;
  const select = planForm.querySelector("select");
  const error = planForm.querySelector("[data-plan-error]");
  async function preview() {
    const request = ++revision;
    const button = planForm.querySelector("button");
    button.disabled = true;
    error.textContent = "실행 계획을 불러오는 중…";
    try {
      const steps = await readJson(`/api/plan?pipeline=${encodeURIComponent(select.value)}`);
      if (request !== revision) return;
      const rows = steps.map(step => {
        const row = document.createElement("li");
        row.textContent = (step.display_name || step.name) + (step.allow_failure ? " (선택 검사)" : "");
        const command = document.createElement("code");
        command.textContent = step.command.map(value => JSON.stringify(value)).join(" ");
        row.append(command);
        return row;
      });
      planForm.querySelector("[data-plan-steps]").replaceChildren(...rows);
      error.textContent = `${steps.length}단계 · 요청한 작업이 대기열에 추가됩니다.`;
      error.className = "muted";
      button.disabled = false;
    } catch (failure) {
      if (request !== revision) return;
      error.textContent = `${failure.message}. 빌드 절차를 다시 선택해 주세요.`;
      error.className = "bad";
    }
  }
  select.addEventListener("change", preview);
  preview();
}

for (const form of document.querySelectorAll("form[method='post']")) {
  form.addEventListener("submit", () => {
    const button = form.querySelector("button");
    if (button) { button.disabled = true; button.textContent = "요청 중…"; }
  });
}

const jobPanel = document.querySelector("[data-job-id]");
if (jobPanel) {
  const id = jobPanel.dataset.jobId;
  const log = document.getElementById("live-log");
  const connection = document.getElementById("connection-state");
  let offset = Number(jobPanel.dataset.logOffset);
  const terminal = new Set(["succeeded", "failed", "cancelled", "interrupted"]);
  async function poll() {
    try {
      const job = await readJson(`/api/jobs/${id}`);
      const status = document.getElementById("job-status");
      status.textContent = job.status_label || job.status;
      status.className = `status ${job.status}`;
      document.getElementById("job-error").textContent = job.error || "";
      const steps = job.steps || [];
      const finished = steps.filter(step => ["succeeded", "failed"].includes(step.status)).length;
      const current = steps.find(step => step.status === "running");
      const seconds = job.started_at ? Math.max(0, Math.floor((Date.parse(job.finished_at || new Date().toISOString()) - Date.parse(job.started_at)) / 1000)) : 0;
      document.getElementById("job-summary").textContent = job.status === "pending"
        ? `대기 순서 ${job.queue_position || "…"} · 빌드 실행 대기 중`
        : `${steps.length}단계 중 ${finished}단계 완료 · ${seconds}초${current ? " · " + (current.display_name || current.name) : ""}`;
      const progress = document.getElementById("job-progress");
      progress.max = Math.max(steps.length, 1);
      progress.value = finished;
      document.getElementById("cancel-job").hidden = !["pending", "running"].includes(job.status);
      document.querySelector("#cancel-job button").disabled = Boolean(job.cancel_requested);
      document.querySelector("#cancel-job button").textContent = job.cancel_requested ? "취소 처리 중…" : "빌드 취소 요청";
      document.getElementById("retry-job").hidden = !terminal.has(job.status);
      document.getElementById("job-steps").replaceChildren(...steps.map(step => {
        const row = document.createElement("tr");
        for (const value of [step.display_name || step.name, step.status_label || step.status, step.exit_code ?? "—"]) {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.append(cell);
        }
        row.children[1].className = `status ${step.status}`;
        return row;
      }));
      const chunk = await readJson(`/api/jobs/${id}/log?offset=${offset}`);
      const advanced = chunk.offset > offset;
      offset = chunk.offset;
      // Bound both transfer size and the browser's log buffer for long builds.
      if (chunk.text) log.textContent = (log.textContent + chunk.text).slice(-120000);
      if (document.getElementById("follow-log").checked) log.scrollTop = log.scrollHeight;
      connection.textContent = terminal.has(job.status) ? "작업 종료" : "실시간 · 매초 갱신";
      if (jobPanel.dataset.initialStatus && terminal.has(job.status) && !terminal.has(jobPanel.dataset.initialStatus)) {
        window.location.reload(); return;
      }
      if (!terminal.has(job.status) || advanced) window.setTimeout(poll, advanced ? 250 : 1000);
    } catch (failure) {
      connection.textContent = `${failure.message} · 다시 연결하는 중…`;
      window.setTimeout(poll, 3000);
    }
  }
  poll();
}

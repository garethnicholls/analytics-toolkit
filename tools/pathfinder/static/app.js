"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  meta: null,
  requestNumber: 0,
  firstAnalysis: true,
};

const dom = {
  sourceName: $("#sourceName"),
  sourceDetail: $("#sourceDetail"),
  event: $("#eventSelect"),
  platform: $("#platformSelect"),
  journey: $("#journeySelect"),
  identity: $("#identitySelect"),
  context: $("#contextSelect"),
  filterCount: $("#filterCount"),
  decision: {
    title: $("#decisionTitle"),
    body: $("#decisionBody"),
    confidence: $("#decisionConfidence"),
    route: $("#decisionRoute"),
  },
  error: $("#errorNotice"),
  empty: $("#emptyNotice"),
  metrics: {
    sessions: $("#metricSessions"),
    previous: $("#metricPrevious"),
    continued: $("#metricContinued"),
    outcome: $("#metricOutcome"),
  },
  insights: $("#insights"),
  timeline: $("#timeline"),
  paths: $("#pathList"),
  loadingLayer: $("#loadingLayer"),
  loadingText: $("#loadingText"),
  dataDialog: $("#dataDialog"),
  dataMessage: $("#dataMessage"),
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-GB").format(Number(value || 0));
}

function formatPercent(value) {
  const number = Number(value || 0);
  return `${number.toFixed(number % 1 === 0 ? 0 : 1)}%`;
}

async function api(path, payload, signal) {
  const options = payload === undefined
    ? { headers: { Accept: "application/json" }, signal }
    : {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
        signal,
      };
  const response = await fetch(path, options);
  let data;
  try {
    data = await response.json();
  } catch (_) {
    throw new Error(`PathFinder returned an invalid response (${response.status}).`);
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status}).`);
  return data;
}

function setPageLoading(active, text = "Building routes…") {
  dom.loadingText.textContent = text;
  dom.loadingLayer.hidden = !active;
}

function showError(message) {
  dom.error.textContent = message || "Something went wrong.";
  dom.error.hidden = false;
}

function clearError() {
  dom.error.hidden = true;
  dom.error.textContent = "";
}

function fillSelect(select, items, allLabel, getValue, getLabel) {
  const previous = select.value;
  select.replaceChildren();
  if (allLabel) {
    const option = element("option", "", allLabel);
    option.value = "all";
    select.append(option);
  }
  for (const item of items) {
    const option = element("option", "", getLabel(item));
    option.value = getValue(item);
    select.append(option);
  }
  if ([...select.options].some((option) => option.value === previous)) {
    select.value = previous;
  }
}

function renderMeta(meta, preferredEvent) {
  state.meta = meta;
  dom.sourceName.textContent = meta.source;
  dom.sourceDetail.textContent = `· ${formatNumber(meta.sessions)} sessions · ${formatNumber(meta.route_steps)} steps`;

  const wantedEvent = preferredEvent || dom.event.value || meta.recommended_event;
  fillSelect(
    dom.event,
    meta.events,
    null,
    (item) => item.name,
    (item) => `${item.name} · ${formatNumber(item.sessions)} sessions`,
  );
  if ([...dom.event.options].some((option) => option.value === wantedEvent)) {
    dom.event.value = wantedEvent;
  } else if (meta.recommended_event) {
    dom.event.value = meta.recommended_event;
  }

  fillSelect(dom.platform, meta.platforms, "All platforms", (item) => item, (item) => item);
  fillSelect(dom.journey, meta.journeys, "All journeys", (item) => item, (item) => item);
  fillSelect(
    dom.identity,
    meta.identity_states,
    "All identity states",
    (item) => item,
    (item) => item.replaceAll("_", " "),
  );

  if (!$("#eventNames").value) {
    $("#eventNames").value = meta.default_event_names.join("\n");
  }
  updateFilterCount();
}

function updateFilterCount() {
  const filters = [dom.platform.value, dom.journey.value, dom.identity.value].filter(
    (value) => value && value !== "all",
  );
  dom.filterCount.textContent = filters.length ? `${filters.length} active` : "All data";
}

function analysisPayload() {
  return {
    event: dom.event.value,
    platform: dom.platform.value,
    journey: dom.journey.value,
    identity: dom.identity.value,
    context_steps: Number(dom.context.value),
  };
}

function renderMetrics(summary) {
  dom.metrics.sessions.textContent = formatNumber(summary.sessions);
  dom.metrics.previous.textContent = formatPercent(summary.has_previous_pct);
  dom.metrics.continued.textContent = formatPercent(summary.continued_pct);
  dom.metrics.outcome.textContent = formatPercent(summary.outcome_after_pct);
}

function dominantRoute(data, offset) {
  return data.steps.find((step) => step.offset === offset)?.routes?.[0] || null;
}

function renderDecision(data) {
  const summary = data.summary;
  const before = dominantRoute(data, -1);
  const after = dominantRoute(data, 1);
  const stopRate = Number(summary.stopped_pct || 0);
  const outcomeRate = Number(summary.outcome_after_pct || 0);
  const continuedRate = Number(summary.continued_pct || 0);

  let title = "Most sessions keep moving after this event";
  let body = `${formatPercent(continuedRate)} continue to another recorded step, while ${formatPercent(outcomeRate)} reach a configured outcome.`;
  if (stopRate >= 50) {
    title = "This event is a common journey endpoint";
    body = `${formatPercent(stopRate)} of focused sessions stop here. Check whether that is expected completion or a point of friction.`;
  } else if (outcomeRate >= 50) {
    title = "This event strongly signals an outcome";
    body = `${formatPercent(outcomeRate)} reach a configured outcome at or after it, across ${formatNumber(summary.sessions)} focused sessions.`;
  }

  dom.decision.title.textContent = title;
  dom.decision.body.textContent = body;
  dom.decision.confidence.textContent = `${formatNumber(summary.sessions)} focused sessions`;
  dom.decision.route.replaceChildren();
  const nodes = [
    before ? { label: "Before", value: before.route, share: before.share_focus_pct } : null,
    { label: "Focus", value: data.selection.event, focus: true },
    after ? { label: "After", value: after.route, share: after.share_focus_pct } : null,
  ].filter(Boolean);
  nodes.forEach((item, index) => {
    if (index) dom.decision.route.append(element("span", "decision-arrow", "→"));
    const node = element("div", item.focus ? "decision-node decision-node--focus" : "decision-node");
    node.append(element("span", "", item.label));
    node.append(element("strong", "", item.value));
    if (item.share !== undefined) node.append(element("small", "", `${formatPercent(item.share)} of focused sessions`));
    dom.decision.route.append(node);
  });
}

function renderInsights(items) {
  dom.insights.replaceChildren();
  const icons = ["←", "→", "×"];
  items.forEach((item, index) => {
    const card = element("article", "insight-card");
    card.append(element("span", "insight-icon", icons[index] || "•"));
    const copy = element("div", "insight-copy");
    copy.append(element("span", "", item.label));
    copy.append(element("strong", "", item.value));
    copy.append(element("small", "", item.detail));
    card.append(copy);
    dom.insights.append(card);
  });
}

function offsetLabel(offset) {
  if (offset === 0) return "Selected event";
  if (offset === -1) return "Immediately before";
  if (offset === 1) return "Immediately after";
  return offset < 0 ? `${Math.abs(offset)} steps before` : `${offset} steps after`;
}

function renderAlternatives(routes) {
  if (routes.length < 2) return null;
  const details = element("details", "alternatives");
  details.append(element("summary", "", `${routes.length - 1} alternative route${routes.length > 2 ? "s" : ""}`));
  routes.slice(1).forEach((route) => {
    const row = element("div", "alternative-row");
    row.append(element("span", "", route.route));
    row.append(element("span", "", `${formatPercent(route.share_focus_pct)} · ${formatNumber(route.sessions)}`));
    details.append(row);
  });
  return details;
}

function renderTimeline(data) {
  dom.timeline.replaceChildren();
  const selectedEvent = data.selection.event;
  for (const step of data.steps) {
    const primary = step.routes[0];
    const kind = step.offset < 0 ? "before" : step.offset > 0 ? "after" : "focus";
    const row = element("article", `step-row step-row--${kind}`);
    const nodeLabel = step.offset === 0 ? "●" : String(Math.abs(step.offset));
    row.append(element("span", "step-node", nodeLabel));

    const card = element("div", "step-card");
    const position = element("div", "step-position");
    position.append(element("span", "", offsetLabel(step.offset)));
    position.append(element("span", "", `${formatPercent(step.coverage_pct)} coverage`));
    card.append(position);

    card.append(element("h3", "step-title", step.offset === 0 ? selectedEvent : primary.route));
    const stat = element("div", "step-stat");
    if (step.offset === 0 && primary.route !== selectedEvent) {
      stat.append(element("span", "", `Mapped route: ${primary.route}`));
    } else {
      stat.append(element("span", "", `${formatNumber(primary.sessions)} sessions`));
    }
    stat.append(element("strong", "", formatPercent(primary.share_focus_pct)));
    card.append(stat);

    const bar = element("div", "route-bar");
    const fill = element("span");
    fill.style.width = `${Math.max(1, Math.min(100, primary.share_focus_pct))}%`;
    bar.append(fill);
    card.append(bar);

    const alternatives = renderAlternatives(step.routes);
    if (alternatives) card.append(alternatives);
    row.append(card);
    dom.timeline.append(row);
  }
}

function renderPaths(data) {
  dom.paths.replaceChildren();
  const focusStep = data.steps.find((step) => step.offset === 0);
  const focusRoute = focusStep?.routes?.[0]?.route;
  data.paths.forEach((path, index) => {
    const card = element("article", "path-card");
    const head = element("div", "path-head");
    head.append(element("strong", "", `Route ${index + 1}`));
    head.append(element("span", "", `${formatNumber(path.sessions)} sessions · ${formatPercent(path.share_pct)}`));
    card.append(head);

    const chips = element("div", "route-chips");
    path.routes.forEach((route, routeIndex) => {
      if (routeIndex) chips.append(element("span", "route-arrow", "→"));
      const className = route === focusRoute ? "route-chip route-chip--focus" : "route-chip";
      chips.append(element("span", className, route));
    });
    card.append(chips);

    const foot = element("div", "path-foot");
    foot.append(element("span", "", `${formatPercent(path.outcome_rate_pct)} outcome rate`));
    foot.append(element("span", "", `${path.routes.length} recorded steps`));
    card.append(foot);
    dom.paths.append(card);
  });
}

function renderAnalysis(data) {
  renderMetrics(data.summary);
  if (data.empty_message) {
    dom.empty.textContent = data.empty_message;
    dom.empty.hidden = false;
    dom.insights.replaceChildren();
    dom.timeline.replaceChildren();
    dom.paths.replaceChildren();
    return;
  }
  dom.empty.hidden = true;
  renderDecision(data);
  renderInsights(data.insights);
  renderTimeline(data);
  renderPaths(data);
}

async function analyse() {
  if (!dom.event.value) return;
  const requestNumber = ++state.requestNumber;
  clearError();
  updateFilterCount();
  document.body.classList.add("analysing");
  if (state.firstAnalysis) setPageLoading(true, "Building event routes…");
  try {
    const data = await api("/api/analyse", analysisPayload());
    if (requestNumber !== state.requestNumber) return;
    renderAnalysis(data);
    state.firstAnalysis = false;
  } catch (error) {
    if (requestNumber === state.requestNumber) showError(error.message);
  } finally {
    if (requestNumber === state.requestNumber) {
      document.body.classList.remove("analysing");
      setPageLoading(false);
    }
  }
}

async function refreshMeta(preferredEvent) {
  const meta = await api("/api/meta");
  renderMeta(meta, preferredEvent);
  return meta;
}

function dateString(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function setDefaultDates() {
  const end = new Date();
  end.setDate(end.getDate() - 1);
  const start = new Date(end);
  start.setDate(start.getDate() - 1);
  $("#startDate").value = dateString(start);
  $("#endDate").value = dateString(end);
}

function dataPayload() {
  return {
    project_id: $("#projectId").value.trim(),
    dataset_id: $("#datasetId").value.trim(),
    table_pattern: $("#tablePattern").value.trim(),
    location: $("#location").value.trim(),
    max_gb: Number($("#maxGb").value),
    start_date: $("#startDate").value,
    end_date: $("#endDate").value,
    event_names: $("#eventNames").value,
    consent_values: ["Yes"],
    collapse_consecutive: $("#collapseConsecutive").checked,
    inactivity_minutes: 30,
  };
}

function showDataMessage(message, isError = false) {
  dom.dataMessage.textContent = message;
  dom.dataMessage.classList.toggle("notice--error", isError);
  dom.dataMessage.hidden = false;
}

function clearDataMessage() {
  dom.dataMessage.hidden = true;
  dom.dataMessage.textContent = "";
  dom.dataMessage.classList.remove("notice--error");
}

async function runButton(button, workingLabel, action) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = workingLabel;
  clearDataMessage();
  try {
    await action();
  } catch (error) {
    showDataMessage(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function resetFilters() {
  dom.platform.value = "all";
  dom.journey.value = "all";
  dom.identity.value = "all";
  dom.context.value = "3";
  updateFilterCount();
  analyse();
}

async function initialise() {
  setDefaultDates();
  setPageLoading(true, "Opening PathFinder…");
  clearError();
  try {
    await refreshMeta();
    await analyse();
  } catch (error) {
    showError(error.message);
    setPageLoading(false);
  }
}

[dom.event, dom.platform, dom.journey, dom.identity, dom.context].forEach((control) => {
  control.addEventListener("change", analyse);
});

$("#resetFilters").addEventListener("click", resetFilters);
$("#openData").addEventListener("click", () => {
  clearDataMessage();
  dom.dataDialog.showModal();
});
$("#closeData").addEventListener("click", () => dom.dataDialog.close());

$("#loadDemo").addEventListener("click", (event) => {
  runButton(event.currentTarget, "Loading…", async () => {
    const preferredEvent = dom.event.value;
    const meta = await api("/api/load-demo", {});
    renderMeta(meta, preferredEvent);
    showDataMessage("Sample data loaded.");
    dom.dataDialog.close();
    await analyse();
  });
});

$("#estimateQuery").addEventListener("click", (event) => {
  runButton(event.currentTarget, "Estimating…", async () => {
    const result = await api("/api/estimate", dataPayload());
    const guard = result.within_guard ? "within" : "above";
    showDataMessage(
      `Estimated scan: ${result.estimated_display}. This is ${guard} the ${result.guard_display} safety guard.`,
      !result.within_guard,
    );
  });
});

$("#loadBigQuery").addEventListener("click", (event) => {
  runButton(event.currentTarget, "Loading…", async () => {
    showDataMessage("Reading raw GA4 and building event routes. Keep this window open.");
    const meta = await api("/api/load-bigquery", dataPayload());
    renderMeta(meta);
    dom.dataDialog.close();
    await analyse();
  });
});

dom.dataDialog.addEventListener("click", (event) => {
  if (event.target === dom.dataDialog) dom.dataDialog.close();
});

initialise();

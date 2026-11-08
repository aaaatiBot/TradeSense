/**
 * TradeSense Frontend Application Scripts
 * Manages live budget calculations, Chart.js SHAP visualizer, and HTMX status bindings.
 */

document.addEventListener("DOMContentLoaded", function () {
  initBudgetCalculator();
  initTradeModeHorizonFilter();
  initShapCharts();
  initHealthCheckListener();
  initAnchoringStatusListener();
});

/**
 * Live Budget Buffer Calculator (SRS §4.2 / §10.3)
 * Live calculation of 0.5% cash buffer and effective deployable capital.
 */
function initBudgetCalculator() {
  const budgetInput = document.getElementById("budget-input");
  const bufferDisplay = document.getElementById("buffer-display");
  const effectiveDisplay = document.getElementById("effective-budget-display");

  if (!budgetInput || !effectiveDisplay) return;

  function update() {
    const rawVal = parseFloat(budgetInput.value) || 0;
    const buffer = rawVal * 0.005; // 0.5% cash buffer
    const effective = Math.max(0, rawVal - buffer);

    if (bufferDisplay) {
      bufferDisplay.textContent = formatINR(buffer);
    }
    effectiveDisplay.textContent = formatINR(effective);
  }

  budgetInput.addEventListener("input", update);
  update();
}

/**
 * Trade Mode & Horizon selector filtering (CNC vs MIS)
 */
function initTradeModeHorizonFilter() {
  const modeRadios = document.querySelectorAll('input[name="trade_mode"]');
  const horizonSelect = document.getElementById("horizon-select");

  if (!horizonSelect || modeRadios.length === 0) return;

  const horizons = {
    CNC: [
      { value: "1d", label: "1 Day (Overnight)" },
      { value: "3d", label: "3 Days (Swing)" },
      { value: "1w", label: "1 Week (Positional)" },
    ],
    MIS: [
      { value: "15m", label: "15 Minutes (Scalp)" },
      { value: "1h", label: "1 Hour (Intraday Momentum)" },
      { value: "intraday", label: "End of Day (3:20 PM Square-off)" },
    ],
  };

  function updateHorizons(mode) {
    const opts = horizons[mode] || horizons.CNC;
    horizonSelect.innerHTML = "";
    opts.forEach(function (opt) {
      const el = document.createElement("option");
      el.value = opt.value;
      el.textContent = opt.label;
      horizonSelect.appendChild(el);
    });
  }

  modeRadios.forEach(function (radio) {
    radio.addEventListener("change", function () {
      if (radio.checked) {
        updateHorizons(radio.value);
      }
    });
    if (radio.checked) {
      updateHorizons(radio.value);
    }
  });
}

/**
 * Format number to Indian Numbering System currency string (₹1,23,456.78)
 */
function formatINR(amount) {
  const num = Math.abs(amount).toFixed(2);
  const parts = num.split(".");
  let intPart = parts[0];
  const decPart = parts[1];

  let lastThree = intPart.substring(intPart.length - 3);
  const otherNumbers = intPart.substring(0, intPart.length - 3);
  if (otherNumbers !== "") {
    lastThree = "," + lastThree;
  }
  const formattedInt = otherNumbers.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + lastThree;
  const prefix = amount < 0 ? "-₹" : "₹";
  return prefix + formattedInt + "." + decPart;
}

/**
 * Chart.js Top-10 Signed Feature Contributions Horizontal Bar Chart (SRS §10.3 / Step 4)
 */
function initShapCharts() {
  if (typeof Chart === "undefined") return;

  const canvasList = document.querySelectorAll(".shap-chart");
  canvasList.forEach(function (canvas) {
    const rawData = canvas.getAttribute("data-features");
    if (!rawData) return;

    try {
      const features = JSON.parse(rawData);
      if (!Array.isArray(features) || features.length === 0) return;

      const labels = features.map(function (f) { return f.name || f.feature || "Feature"; });
      const values = features.map(function (f) { return parseFloat(f.value || f.weight || 0); });
      const bgColors = values.map(function (v) { return v >= 0 ? "rgba(45, 206, 137, 0.75)" : "rgba(245, 54, 92, 0.75)"; });
      const borderColors = values.map(function (v) { return v >= 0 ? "#2dce89" : "#f5365c"; });

      new Chart(canvas.getContext("2d"), {
        type: "bar",
        data: {
          labels: labels,
          datasets: [{
            label: "SHAP Impact",
            data: values,
            backgroundColor: bgColors,
            borderColor: borderColors,
            borderWidth: 1,
            borderRadius: 4,
          }]
        },
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: function (ctx) {
                  const val = ctx.parsed.x;
                  return (val >= 0 ? "+" : "") + val.toFixed(4);
                }
              }
            }
          },
          scales: {
            x: {
              grid: { color: "rgba(0,0,0,0.05)" },
              ticks: { font: { size: 10 } }
            },
            y: {
              grid: { display: false },
              ticks: { font: { size: 11, weight: 600 } }
            }
          }
        }
      });
    } catch (e) {
      console.error("Failed to render SHAP chart", e);
    }
  });
}

/**
 * HTMX & Blockchain status listener
 * Enables the "Open Paper Trade" button ONLY when status == "ANCHORED" (SRS §10.3 and §13 AT-28)
 */
function initAnchoringStatusListener() {
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    checkAnchoringState();
  });
  checkAnchoringState();
}

function checkAnchoringState() {
  const chips = document.querySelectorAll(".blockchain-status-chip");
  const tradeBtns = document.querySelectorAll(".btn-open-paper-trade");

  chips.forEach(function (chip) {
    const status = (chip.getAttribute("data-status") || chip.textContent || "").trim().toUpperCase();
    if (status.includes("ANCHORED")) {
      tradeBtns.forEach(function (btn) {
        btn.removeAttribute("disabled");
        btn.classList.remove("disabled");
      });
    }
  });
}

/**
 * Health check listener for HTMX /api/v1/health updates
 */
function initHealthCheckListener() {
  document.body.addEventListener("htmx:afterRequest", function (evt) {
    if (evt.detail && evt.detail.path === "/api/v1/health") {
      try {
        const resp = JSON.parse(evt.detail.xhr.responseText);
        const data = resp.data || resp;
        const deps = data.dependencies || {};
        
        renderHealthChip("health-chip-database", deps.database);
        renderHealthChip("health-chip-market_data", deps.market_data);
        renderHealthChip("health-chip-gemini", deps.gemini);
        renderHealthChip("health-chip-blockchain", deps.blockchain);
      } catch (e) {
        // Non-JSON or standard swap
      }
    }
  });
}

function renderHealthChip(elemId, dep) {
  const el = document.getElementById(elemId);
  if (!el || !dep) return;
  const status = (dep.status || "unknown").toLowerCase();
  el.className = "status-chip ";
  if (status === "ok") {
    el.className += "status-chip-anchored";
    el.innerHTML = '<i class="bi bi-check-circle-fill"></i> OK';
  } else if (status === "degraded") {
    el.className += "status-chip-pending";
    el.innerHTML = '<i class="bi bi-exclamation-triangle-fill"></i> Degraded';
  } else {
    el.className += "status-chip-failed";
    el.innerHTML = '<i class="bi bi-x-circle-fill"></i> Down';
  }
}

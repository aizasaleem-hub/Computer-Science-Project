let lastAnalysis = null;
let accessToken = null;

function setStatus(text) {
  document.getElementById("result-box").textContent = text;
}

function setAuthStatus(text) {
  document.getElementById("auth-status").textContent = text;
}

function renderWeaknesses(weaknesses) {
  const container = document.getElementById("weakness-list");
  container.innerHTML = "";

  if (!weaknesses || !weaknesses.length) {
    container.innerHTML = "<p class='hint'>No weaknesses found.</p>";
    document.getElementById("refine-btn").disabled = true;
    return;
  }

  weaknesses.forEach((w) => {
    const wrapper = document.createElement("div");
    wrapper.className = "weakness-item";

    const header = document.createElement("header");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = w.id;
    checkbox.checked = true;
    checkbox.className = "change-checkbox";

    const title = document.createElement("span");
    title.textContent = `${w.id}: ${w.issue}`;

    header.appendChild(checkbox);
    header.appendChild(title);

    const why = document.createElement("p");
    why.innerHTML = `<strong>Why it matters:</strong> ${w.why_it_matters}`;

    const suggestion = document.createElement("p");
    suggestion.innerHTML = `<strong>Suggested change:</strong> ${w.suggestion}`;

    const citation = document.createElement("p");
    citation.className = "meta";
    citation.textContent = w.citation ? `Citation: ${w.citation}` : "Citation: context gap";

    wrapper.appendChild(header);
    wrapper.appendChild(why);
    wrapper.appendChild(suggestion);
    wrapper.appendChild(citation);

    container.appendChild(wrapper);
  });

  document.getElementById("refine-btn").disabled = false;
}

async function analyzeReport() {
  const input = document.getElementById("report-input");
  const fileInput = document.getElementById("report-file");
  const resultBox = document.getElementById("result-box");
  const refineBtn = document.getElementById("refine-btn");

  const report = input.value.trim();
  resultBox.textContent = "Analyzing...";
  refineBtn.disabled = true;
  lastAnalysis = null;
  document.getElementById("weakness-list").innerHTML = "";

  const formData = new FormData();
  if (report) formData.append("report", report);
  if (fileInput.files.length) formData.append("file", fileInput.files[0]);

  const response = await fetch("http://localhost:8000/analyze", {
    method: "POST",
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    body: formData
  });

  const data = await response.json();
  if (response.ok) {
    lastAnalysis = data;
    renderWeaknesses(data.weaknesses);
    resultBox.textContent = `Overview: ${data.overview}`;
  } else {
    resultBox.textContent = data.detail || "Analysis failed.";
  }
}

async function generateRefined() {
  if (!lastAnalysis) {
    setStatus("Run analysis first.");
    return;
  }

  const checkboxes = document.querySelectorAll(".change-checkbox:checked");
  const selectedIds = Array.from(checkboxes).map((c) => c.value);
  const selectedChanges = (lastAnalysis.weaknesses || []).filter((w) =>
    selectedIds.includes(w.id)
  );

  setStatus("Generating refined report...");

  const response = await fetch("http://localhost:8000/refine", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {})
    },
    body: JSON.stringify({
      report: lastAnalysis.normalized_report,
      selected_changes: selectedChanges
    })
  });

  const data = await response.json();
  if (response.ok) {
    setStatus(data.refined_report);
  } else {
    setStatus(data.detail || "Refinement failed.");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const fileInput = document.getElementById("report-file");
  const label = document.getElementById("file-label");
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) {
      label.textContent = fileInput.files[0].name;
    } else {
      label.textContent = "";
    }
  });
});

async function signUp() {
  const username = document.getElementById("username").value.trim();
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value.trim();
  if (!username || !email || !password) {
    setAuthStatus("Username, email, and password required to sign up.");
    return;
  }
  const resp = await fetch("http://localhost:8000/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password })
  });
  if (resp.ok) {
    setAuthStatus("Signup success. Now login.");
  } else {
    const data = await resp.json().catch(() => ({}));
    setAuthStatus(data.detail || "Signup failed");
  }
}

async function login() {
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value.trim();
  if (!username || !password) {
    setAuthStatus("Username/email and password required.");
    return;
  }
  const resp = await fetch("http://localhost:8000/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username_or_email: username, password })
  });
  const data = await resp.json().catch(() => ({}));
  if (resp.ok && data.access_token) {
    accessToken = data.access_token;
    setAuthStatus("Logged in");
  } else {
    setAuthStatus(data.detail || "Login failed");
  }
}

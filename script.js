async function analyzeReport() {
  const input = document.getElementById("report-input");
  const fileInput = document.getElementById("report-file");
  const resultBox = document.getElementById("result-box");

  const report = input.value.trim();
  resultBox.textContent = "Analyzing...";

  const formData = new FormData();
  if (report) formData.append("report", report);
  if (fileInput.files.length) formData.append("file", fileInput.files[0]);

  const response = await fetch("http://localhost:8000/analyze", {
    method: "POST",
    body: formData
  });

  const data = await response.json();
  if (response.ok) {
    resultBox.textContent = data.analysis;
  } else {
    resultBox.textContent = data.detail || "Analysis failed.";
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

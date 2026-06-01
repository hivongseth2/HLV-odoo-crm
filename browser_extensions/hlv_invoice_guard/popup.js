const odooBaseUrl = document.getElementById("odooBaseUrl");
const apiToken = document.getElementById("apiToken");
const saved = document.getElementById("saved");

chrome.storage.sync.get(["odooBaseUrl", "apiToken"], (config) => {
  odooBaseUrl.value = config.odooBaseUrl || "";
  apiToken.value = config.apiToken || "";
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set({
    odooBaseUrl: odooBaseUrl.value.trim().replace(/\/+$/, ""),
    apiToken: apiToken.value.trim(),
  }, () => {
    saved.textContent = "Đã lưu.";
    setTimeout(() => { saved.textContent = ""; }, 1800);
  });
});

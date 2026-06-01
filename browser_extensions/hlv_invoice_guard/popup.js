const apiToken = document.getElementById("apiToken");
const saved = document.getElementById("saved");

chrome.storage.sync.get(["apiToken"], (config) => {
  apiToken.value = config.apiToken || "";
});

document.getElementById("save").addEventListener("click", () => {
  chrome.storage.sync.set({
    apiToken: apiToken.value.trim(),
  }, () => {
    saved.textContent = "Đã lưu.";
    setTimeout(() => { saved.textContent = ""; }, 1800);
  });
});

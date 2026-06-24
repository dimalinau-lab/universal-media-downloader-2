// Функция отправки ссылки в нашу программу
function sendToUMD(url) {
  fetch('http://127.0.0.1:65432/download', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ url: url })
  })
  .then(response => response.json())
  .then(data => {
    console.log("Успех:", data);
    chrome.action.setBadgeText({text: "OK!"});
    setTimeout(() => chrome.action.setBadgeText({text: ""}), 2000);
  })
  .catch(err => {
    console.error("Ошибка (Программа не запущена?):", err);
    chrome.action.setBadgeText({text: "ERR"});
  });
}

chrome.action.onClicked.addListener((tab) => {
  if (tab.url) {
    chrome.action.setBadgeText({text: "..."});
    sendToUMD(tab.url);
  }
});
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "send_to_umd",
    title: "Скачать через UMD",
    contexts: ["page", "link", "video"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "send_to_umd") {
    let targetUrl = info.linkUrl || info.pageUrl;

    if (targetUrl) {
      chrome.action.setBadgeText({text: "..."});
      sendToUMD(targetUrl);
    }
  }
});